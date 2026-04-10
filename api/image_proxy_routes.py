"""
Image proxy blueprint — isolated endpoint that streams image bytes back to the
workspace image viewer. Mirrors pdf_proxy_routes.py structure.

Route: POST /api/workspace/image-proxy
Body:  { "source": { "kind": "gdrive"|"onedrive"|"url", ... } }
Auth:  JWT (token_required)
"""

import logging
import urllib.parse

from flask import Blueprint, Response, request

from api.auth_routes import token_required
from api.routes import error_response
from services.image_proxy import ImageProxyError, resolve_to_bytes

logger = logging.getLogger(__name__)

image_proxy_api = Blueprint("image_proxy_api", __name__)


@image_proxy_api.route("/image-proxy", methods=["POST"])
@token_required
def proxy_image(current_user):
    payload = request.get_json(silent=True) or {}
    source = payload.get("source")
    if source is None:
        return error_response("source krävs", 400)

    try:
        data, content_type, filename = resolve_to_bytes(current_user, source)
    except ImageProxyError as e:
        return error_response(str(e), e.status_code)
    except Exception:
        logger.exception("Image proxy: unexpected error")
        return error_response("Internt fel vid hämtning av bild.", 500)

    return Response(
        data,
        mimetype=content_type,
        headers={
            "Content-Length": str(len(data)),
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": "inline; filename=\"{}\"; filename*=UTF-8''{}".format(
                filename.encode("ascii", "replace").decode("ascii"),
                urllib.parse.quote(filename),
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )
