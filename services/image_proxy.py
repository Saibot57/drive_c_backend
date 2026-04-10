"""
Image proxy resolver — fetches image bytes from various sources on behalf of
the workspace image viewer.

Supported source kinds (mirrors pdf_proxy):
  - gdrive:   Google Drive file_id that the user owns (verified against DriveFile)
  - onedrive: "anyone with link" share URL (public)
  - url:      Arbitrary public HTTPS image URL, with strict SSRF / size / type guards

This module is deliberately isolated from existing workspace routes/services.
"""

from __future__ import annotations

import base64
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Tuple

from services.db_config import DriveFile
from services.drive_connect import fetch_file_bytes
from services.pdf_proxy import _ssrf_guard, PdfProxyError

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB
FETCH_TIMEOUT_SECONDS = 15

ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "binary/octet-stream",
}

# Magic bytes for common image formats
_MAGIC_TABLE: list[Tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP — we check the "WEBP" part separately
]


class ImageProxyError(Exception):
    """Raised when an image source cannot be resolved. Message is user-safe."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def resolve_to_bytes(current_user, source: dict) -> Tuple[bytes, str, str]:
    """
    Resolve an ImageContent.source dict to raw image bytes.

    Returns:
        (image_bytes, content_type, filename_hint)

    Raises:
        ImageProxyError: any user-facing failure
    """
    if not isinstance(source, dict):
        raise ImageProxyError("Källan måste vara ett objekt.")

    kind = source.get("kind")
    logger.info("Image proxy: resolving source kind=%s for user=%s", kind, getattr(current_user, "id", "?"))

    if kind == "gdrive":
        return _resolve_gdrive(current_user, source)
    if kind == "onedrive":
        return _resolve_onedrive(source)
    if kind == "url":
        return _resolve_public_url(source)

    raise ImageProxyError(f"Okänd källtyp: {kind!r}")


# ──────────────────────────────────────────────────────────────────────────
# Google Drive
# ──────────────────────────────────────────────────────────────────────────
def _resolve_gdrive(current_user, source: dict) -> Tuple[bytes, str, str]:
    file_id = (source.get("fileId") or "").strip()
    if not file_id:
        raise ImageProxyError("Google Drive-källa kräver fileId.")

    drive_file = DriveFile.query.filter_by(id=file_id, user_id=current_user.id).first()
    if not drive_file:
        logger.warning(
            "Image proxy: user %s attempted to access unowned gdrive file %s",
            current_user.id,
            file_id,
        )
        raise ImageProxyError(
            "Google Drive-filen hittades inte i ditt Drive C-konto. "
            "Bildvisaren kan bara öppna filer som är synkade till din "
            "Drive C-filmapp. Öppna filen direkt via filhanteraren istället, "
            "eller synka mappen som innehåller filen.",
            status_code=403,
        )

    try:
        data = fetch_file_bytes(file_id)
    except Exception as e:
        logger.exception("Image proxy: gdrive fetch failed for %s", file_id)
        raise ImageProxyError(f"Kunde inte hämta från Google Drive: {e}", status_code=502)

    _enforce_size(data)
    content_type = _detect_image_type(data)
    return data, content_type, drive_file.name or "image.png"


# ──────────────────────────────────────────────────────────────────────────
# OneDrive (public "anyone with link" share URLs only)
# ──────────────────────────────────────────────────────────────────────────
def _resolve_onedrive(source: dict) -> Tuple[bytes, str, str]:
    share_url = (source.get("shareUrl") or "").strip()
    if not share_url:
        raise ImageProxyError("OneDrive-källa kräver shareUrl.")

    parsed = urllib.parse.urlparse(share_url)
    if parsed.scheme not in ("http", "https"):
        raise ImageProxyError("shareUrl måste vara http(s).")

    host = (parsed.hostname or "").lower()
    if not (
        host.endswith("1drv.ms")
        or host.endswith("onedrive.live.com")
        or host.endswith("sharepoint.com")
    ):
        raise ImageProxyError("shareUrl måste peka på en OneDrive- eller SharePoint-värd.")

    api_url = _onedrive_share_to_api_url(share_url)
    logger.info("Image proxy: onedrive share -> shares API URL")

    try:
        return _fetch_public(api_url, allow_redirects=True)
    except ImageProxyError as e:
        msg = str(e)
        if "401" in msg or "403" in msg:
            logger.warning("Image proxy: OneDrive shares API returned auth error for %s", share_url)
            raise ImageProxyError(
                "OneDrive nekade åtkomst. Filen måste delas som "
                "\"Alla med länken\" (Anyone with the link). "
                "Öppna delningsinställningarna i OneDrive och ändra "
                "till \"Alla med länken\" innan du kopierar länken.",
                status_code=403,
            )
        raise


def _onedrive_share_to_api_url(share_url: str) -> str:
    encoded = base64.urlsafe_b64encode(share_url.encode("utf-8")).decode("ascii")
    encoded = encoded.rstrip("=")
    return f"https://api.onedrive.com/v1.0/shares/u!{encoded}/root/content"


# ──────────────────────────────────────────────────────────────────────────
# Arbitrary public URL (with SSRF guard)
# ──────────────────────────────────────────────────────────────────────────
def _resolve_public_url(source: dict) -> Tuple[bytes, str, str]:
    url = (source.get("url") or "").strip()
    if not url:
        raise ImageProxyError("URL-källa kräver url.")
    return _fetch_public(url, allow_redirects=True)


def _fetch_public(url: str, allow_redirects: bool = True) -> Tuple[bytes, str, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ImageProxyError("URL måste använda http eller https.")

    host = parsed.hostname
    if not host:
        raise ImageProxyError("URL saknar värdnamn.")
    _ssrf_guard(host)

    logger.info("Image proxy: fetching %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "DriveC-ImageProxy/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            final_url = resp.url
            final_host = urllib.parse.urlparse(final_url).hostname
            if final_host and final_host != host:
                logger.info("Image proxy: redirected to %s", final_url)
                _ssrf_guard(final_host)

            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_IMAGE_BYTES:
                raise ImageProxyError(
                    f"Bilden överskrider maxstorleken på {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
                    status_code=413,
                )

            data = resp.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                raise ImageProxyError(
                    f"Bilden överskrider maxstorleken på {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
                    status_code=413,
                )
    except ImageProxyError:
        raise
    except urllib.error.HTTPError as e:
        logger.warning("Image proxy: HTTP %s from %s — %s", e.code, url, e.reason)
        raise ImageProxyError(
            f"Kunde inte hämta URL (HTTP {e.code}: {e.reason}).",
            status_code=502,
        )
    except Exception as e:
        logger.exception("Image proxy: public fetch failed for %s", url)
        raise ImageProxyError(f"Kunde inte hämta URL: {e}", status_code=502)

    # Detect actual image type from content
    detected_type = _detect_image_type(data, content_type)

    # If the server said it's an image type we recognise, prefer that for SVG
    # (SVG has no reliable magic bytes).
    if content_type == "image/svg+xml":
        detected_type = "image/svg+xml"

    filename = _filename_from_url(parsed) or "image.png"
    return data, detected_type, filename


def _detect_image_type(data: bytes, fallback_content_type: str = "") -> str:
    """Detect image type from magic bytes. Raises if not a recognised image."""
    for magic, mime in _MAGIC_TABLE:
        if data.startswith(magic):
            # Extra check for WEBP: bytes 8-12 must be "WEBP"
            if magic == b"RIFF" and data[8:12] != b"WEBP":
                continue
            return mime

    # SVG is text-based — check for an svg tag
    head = data[:1024].lower()
    if b"<svg" in head:
        return "image/svg+xml"

    # If the server's content-type is an image type we trust, accept it
    if fallback_content_type in ALLOWED_CONTENT_TYPES and fallback_content_type != "binary/octet-stream":
        return fallback_content_type

    raise ImageProxyError("Det hämtade innehållet är inte en giltig bildfil.")


def _enforce_size(data: bytes) -> None:
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageProxyError(
            f"Bilden överskrider maxstorleken på {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
            status_code=413,
        )


def _filename_from_url(parsed: urllib.parse.ParseResult) -> str:
    path = parsed.path or ""
    tail = path.rstrip("/").rsplit("/", 1)[-1]
    return tail if tail else ""
