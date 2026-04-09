"""
PDF proxy resolver — fetches PDF bytes from various sources on behalf of the
workspace PDF viewer.

Supported source kinds (v1):
  - gdrive:   Google Drive file_id that the user owns (verified against DriveFile)
  - onedrive: "anyone with link" share URL (public). Private OneDrive files are
              OUT OF SCOPE for v1 — requires OAuth setup, which we haven't built.
  - url:      Arbitrary public HTTPS PDF URL, with strict SSRF / size / type guards

This module is deliberately isolated from existing workspace routes/services.
It exposes a single public function, resolve_to_bytes(), that route handlers
call. No existing function is modified.
"""

from __future__ import annotations

import base64
import ipaddress
import logging
import socket
import urllib.parse
import urllib.request
from typing import Tuple

from services.db_config import DriveFile
from services.drive_connect import fetch_file_bytes

logger = logging.getLogger(__name__)

# Hard limits to protect the proxy from abuse / accidents
MAX_PDF_BYTES = 50 * 1024 * 1024  # 50 MB
FETCH_TIMEOUT_SECONDS = 15
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "binary/octet-stream",  # some CDNs mislabel; we also sniff the magic bytes below
}
PDF_MAGIC = b"%PDF-"


class PdfProxyError(Exception):
    """Raised when a PDF source cannot be resolved. Message is user-safe."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def resolve_to_bytes(current_user, source: dict) -> Tuple[bytes, str]:
    """
    Resolve a PdfContent.source dict to raw PDF bytes.

    Returns:
        (pdf_bytes, filename_hint)

    Raises:
        PdfProxyError: any user-facing failure (bad source, forbidden, too big, etc.)
    """
    if not isinstance(source, dict):
        raise PdfProxyError("Källan måste vara ett objekt.")

    kind = source.get("kind")
    logger.info("PDF proxy: resolving source kind=%s for user=%s", kind, getattr(current_user, "id", "?"))

    if kind == "gdrive":
        return _resolve_gdrive(current_user, source)
    if kind == "onedrive":
        return _resolve_onedrive(source)
    if kind == "url":
        return _resolve_public_url(source)

    raise PdfProxyError(f"Okänd källtyp: {kind!r}")


# ──────────────────────────────────────────────────────────────────────────
# Google Drive
# ──────────────────────────────────────────────────────────────────────────
def _resolve_gdrive(current_user, source: dict) -> Tuple[bytes, str]:
    file_id = (source.get("fileId") or "").strip()
    if not file_id:
        raise PdfProxyError("Google Drive-källa kräver fileId.")

    # Ownership check: the file must be synced into this user's DriveFile table.
    drive_file = DriveFile.query.filter_by(id=file_id, user_id=current_user.id).first()
    if not drive_file:
        logger.warning(
            "PDF proxy: user %s attempted to access unowned gdrive file %s",
            current_user.id,
            file_id,
        )
        raise PdfProxyError(
            "Filen hittades inte eller saknar behörighet. "
            "Den måste vara synkad till ditt Drive C-konto.",
            status_code=403,
        )

    try:
        data = fetch_file_bytes(file_id)
    except Exception as e:
        logger.exception("PDF proxy: gdrive fetch failed for %s", file_id)
        raise PdfProxyError(f"Kunde inte hämta från Google Drive: {e}", status_code=502)

    _enforce_size(data)
    _enforce_pdf_magic(data)
    return data, drive_file.name or "document.pdf"


# ──────────────────────────────────────────────────────────────────────────
# OneDrive (v1: public "anyone with link" share URLs only)
# ──────────────────────────────────────────────────────────────────────────
#
# IMPLEMENTATION NOTE — why we use the shares API:
#
# The naive "?download=1" trick doesn't work for 1drv.ms shortlinks because
# they 302-redirect to onedrive.live.com and the query string from the
# original URL is dropped on the redirect, leaving us at the HTML viewer.
#
# The correct path is Microsoft's public shares API, which accepts a base64url-
# encoded share URL and returns the file bytes directly:
#
#   https://api.onedrive.com/v1.0/shares/u!{base64url(share_url)}/root/content
#
# This endpoint requires NO auth for "anyone with link" shares, follows the
# standard Microsoft Graph encoding rules (u! prefix + base64url, padding
# stripped), and works for both 1drv.ms shortlinks and full onedrive.live.com
# / SharePoint URLs.
#
# OUT OF SCOPE FOR v1: private OneDrive files (require Microsoft Graph OAuth).
# Users with private files must change the share to "Anyone with the link".
def _resolve_onedrive(source: dict) -> Tuple[bytes, str]:
    share_url = (source.get("shareUrl") or "").strip()
    if not share_url:
        raise PdfProxyError("OneDrive-källa kräver shareUrl.")

    parsed = urllib.parse.urlparse(share_url)
    if parsed.scheme not in ("http", "https"):
        raise PdfProxyError("shareUrl måste vara http(s).")

    host = (parsed.hostname or "").lower()
    if not (
        host.endswith("1drv.ms")
        or host.endswith("onedrive.live.com")
        or host.endswith("sharepoint.com")
    ):
        raise PdfProxyError("shareUrl måste peka på en OneDrive- eller SharePoint-värd.")

    api_url = _onedrive_share_to_api_url(share_url)
    logger.info("PDF proxy: onedrive share -> shares API URL")
    return _fetch_public(api_url, allow_redirects=True)


def _onedrive_share_to_api_url(share_url: str) -> str:
    """
    Convert a OneDrive/SharePoint share URL into the Microsoft shares API URL
    that returns file bytes directly. Format documented by Microsoft as:

        u!{base64url(share_url) with padding stripped}

    Reference: https://learn.microsoft.com/en-us/onedrive/developer/rest-api/api/shares_get
    """
    encoded = base64.urlsafe_b64encode(share_url.encode("utf-8")).decode("ascii")
    encoded = encoded.rstrip("=")
    return f"https://api.onedrive.com/v1.0/shares/u!{encoded}/root/content"


# ──────────────────────────────────────────────────────────────────────────
# Arbitrary public URL (with SSRF guard)
# ──────────────────────────────────────────────────────────────────────────
def _resolve_public_url(source: dict) -> Tuple[bytes, str]:
    url = (source.get("url") or "").strip()
    if not url:
        raise PdfProxyError("URL-källa kräver url.")
    return _fetch_public(url, allow_redirects=True)


def _fetch_public(url: str, allow_redirects: bool = True) -> Tuple[bytes, str]:
    """
    Fetch a PDF from a public URL, enforcing:
      - https or http only
      - SSRF guard: host must resolve to a non-private, non-loopback IP
      - content-type must be pdf-ish OR magic bytes must match
      - size limit (MAX_PDF_BYTES)
      - timeout (FETCH_TIMEOUT_SECONDS)
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise PdfProxyError("URL måste använda http eller https.")

    host = parsed.hostname
    if not host:
        raise PdfProxyError("URL saknar värdnamn.")
    _ssrf_guard(host)

    logger.info("PDF proxy: fetching %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "DriveC-PdfProxy/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            # Re-check the post-redirect host if redirects happened
            final_url = resp.url
            final_host = urllib.parse.urlparse(final_url).hostname
            if final_host and final_host != host:
                logger.info("PDF proxy: redirected to %s", final_url)
                _ssrf_guard(final_host)

            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_PDF_BYTES:
                raise PdfProxyError(
                    f"PDF överskrider maxstorleken på {MAX_PDF_BYTES // (1024 * 1024)} MB.",
                    status_code=413,
                )

            # Read with a hard cap to protect against liars
            data = resp.read(MAX_PDF_BYTES + 1)
            if len(data) > MAX_PDF_BYTES:
                raise PdfProxyError(
                    f"PDF överskrider maxstorleken på {MAX_PDF_BYTES // (1024 * 1024)} MB.",
                    status_code=413,
                )
    except PdfProxyError:
        raise
    except Exception as e:
        logger.exception("PDF proxy: public fetch failed for %s", url)
        raise PdfProxyError(f"Kunde inte hämta URL: {e}", status_code=502)

    # Content-type check is advisory; magic bytes are authoritative.
    if content_type and content_type not in ALLOWED_CONTENT_TYPES and not content_type.endswith("/pdf"):
        # Some hosts return text/html for the download landing page. We still
        # accept if the body starts with %PDF-.
        if not data.startswith(PDF_MAGIC):
            logger.warning(
                "PDF proxy: non-PDF response from %s (content-type=%s, %d bytes)",
                url,
                content_type,
                len(data),
            )
            raise PdfProxyError(
                "Länken returnerade en HTML-sida istället för en PDF-fil. "
                "Kontrollera att delningsläget är satt till \"Alla med länken\" "
                "och att länken pekar direkt på en fil (inte en mapp eller en webbvy)."
            )

    _enforce_pdf_magic(data)
    filename = _filename_from_url(parsed) or "document.pdf"
    return data, filename


def _ssrf_guard(host: str) -> None:
    """Reject hosts that resolve to loopback, link-local, or private IP ranges."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise PdfProxyError(f"Kunde inte slå upp värd: {host}") from e

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise PdfProxyError(
                f"Vägrar hämta från icke-publik adress: {ip_str}",
                status_code=403,
            )


def _enforce_size(data: bytes) -> None:
    if len(data) > MAX_PDF_BYTES:
        raise PdfProxyError(
            f"PDF överskrider maxstorleken på {MAX_PDF_BYTES // (1024 * 1024)} MB.",
            status_code=413,
        )


def _enforce_pdf_magic(data: bytes) -> None:
    if not data.startswith(PDF_MAGIC):
        raise PdfProxyError("Det hämtade innehållet är inte en giltig PDF.")


def _filename_from_url(parsed: urllib.parse.ParseResult) -> str:
    path = parsed.path or ""
    tail = path.rstrip("/").rsplit("/", 1)[-1]
    return tail if tail else ""
