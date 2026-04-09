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
        raise PdfProxyError("source must be an object")

    kind = source.get("kind")
    if kind == "gdrive":
        return _resolve_gdrive(current_user, source)
    if kind == "onedrive":
        return _resolve_onedrive(source)
    if kind == "url":
        return _resolve_public_url(source)

    raise PdfProxyError(f"Unknown source kind: {kind!r}")


# ──────────────────────────────────────────────────────────────────────────
# Google Drive
# ──────────────────────────────────────────────────────────────────────────
def _resolve_gdrive(current_user, source: dict) -> Tuple[bytes, str]:
    file_id = (source.get("fileId") or "").strip()
    if not file_id:
        raise PdfProxyError("gdrive source requires fileId")

    # Ownership check: the file must be synced into this user's DriveFile table.
    drive_file = DriveFile.query.filter_by(id=file_id, user_id=current_user.id).first()
    if not drive_file:
        logger.warning(
            "PDF proxy: user %s attempted to access unowned gdrive file %s",
            current_user.id,
            file_id,
        )
        raise PdfProxyError("File not found or access denied", status_code=403)

    try:
        data = fetch_file_bytes(file_id)
    except Exception as e:
        logger.exception("PDF proxy: gdrive fetch failed for %s", file_id)
        raise PdfProxyError(f"Failed to fetch from Google Drive: {e}", status_code=502)

    _enforce_size(data)
    _enforce_pdf_magic(data)
    return data, drive_file.name or "document.pdf"


# ──────────────────────────────────────────────────────────────────────────
# OneDrive (v1: public share links only)
# ──────────────────────────────────────────────────────────────────────────
def _resolve_onedrive(source: dict) -> Tuple[bytes, str]:
    share_url = (source.get("shareUrl") or "").strip()
    if not share_url:
        raise PdfProxyError("onedrive source requires shareUrl")

    # Convert a "view" share URL into a direct-download URL by appending
    # ?download=1 (the documented pattern for anyone-with-link shares).
    # NOTE: this only works for PUBLIC links. Private OneDrive files are
    # out of scope for v1 — supporting them requires a full Microsoft Graph
    # OAuth flow which we haven't built. Document as known limitation.
    parsed = urllib.parse.urlparse(share_url)
    if parsed.scheme not in ("http", "https"):
        raise PdfProxyError("shareUrl must be http(s)")

    host = (parsed.hostname or "").lower()
    if not (host.endswith("1drv.ms") or host.endswith("onedrive.live.com") or host.endswith("sharepoint.com")):
        raise PdfProxyError("shareUrl must point to a OneDrive/SharePoint host")

    # Append ?download=1 (or &download=1 if there are existing params).
    query = parsed.query
    if "download=1" not in query:
        query = (query + "&download=1") if query else "download=1"
    download_url = urllib.parse.urlunparse(parsed._replace(query=query))

    return _fetch_public(download_url, allow_redirects=True)


# ──────────────────────────────────────────────────────────────────────────
# Arbitrary public URL (with SSRF guard)
# ──────────────────────────────────────────────────────────────────────────
def _resolve_public_url(source: dict) -> Tuple[bytes, str]:
    url = (source.get("url") or "").strip()
    if not url:
        raise PdfProxyError("url source requires url")
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
        raise PdfProxyError("url must use http or https")

    host = parsed.hostname
    if not host:
        raise PdfProxyError("url has no host")
    _ssrf_guard(host)

    req = urllib.request.Request(url, headers={"User-Agent": "DriveC-PdfProxy/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            # Re-check the post-redirect host if redirects happened
            final_host = urllib.parse.urlparse(resp.url).hostname
            if final_host and final_host != host:
                _ssrf_guard(final_host)

            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_PDF_BYTES:
                raise PdfProxyError(f"PDF exceeds max size of {MAX_PDF_BYTES} bytes", status_code=413)

            # Read with a hard cap to protect against liars
            data = resp.read(MAX_PDF_BYTES + 1)
            if len(data) > MAX_PDF_BYTES:
                raise PdfProxyError(f"PDF exceeds max size of {MAX_PDF_BYTES} bytes", status_code=413)
    except PdfProxyError:
        raise
    except Exception as e:
        logger.exception("PDF proxy: public fetch failed for %s", url)
        raise PdfProxyError(f"Failed to fetch URL: {e}", status_code=502)

    # Content-type check is advisory; magic bytes are authoritative.
    if content_type and content_type not in ALLOWED_CONTENT_TYPES and not content_type.endswith("/pdf"):
        # Some hosts return text/html for the download landing page. We still
        # accept if the body starts with %PDF-.
        if not data.startswith(PDF_MAGIC):
            raise PdfProxyError(f"URL did not return a PDF (content-type: {content_type})")

    _enforce_pdf_magic(data)
    filename = _filename_from_url(parsed) or "document.pdf"
    return data, filename


def _ssrf_guard(host: str) -> None:
    """Reject hosts that resolve to loopback, link-local, or private IP ranges."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise PdfProxyError(f"Could not resolve host: {host}") from e

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise PdfProxyError(f"Refusing to fetch from non-public address: {ip_str}", status_code=403)


def _enforce_size(data: bytes) -> None:
    if len(data) > MAX_PDF_BYTES:
        raise PdfProxyError(f"PDF exceeds max size of {MAX_PDF_BYTES} bytes", status_code=413)


def _enforce_pdf_magic(data: bytes) -> None:
    if not data.startswith(PDF_MAGIC):
        raise PdfProxyError("Fetched content is not a valid PDF")


def _filename_from_url(parsed: urllib.parse.ParseResult) -> str:
    path = parsed.path or ""
    tail = path.rstrip("/").rsplit("/", 1)[-1]
    return tail if tail else ""
