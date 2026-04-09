"""
PDF proxy blueprint — isolated endpoint that streams PDF bytes back to the
workspace PDF viewer. Exists in its own file so that changes here cannot
affect existing workspace CRUD routes.

Route: POST /api/workspace/pdf-proxy
Body:  { "source": { "kind": "gdrive"|"onedrive"|"url", ... } }
Auth:  JWT (token_required)
"""

import logging

from flask import Blueprint, Response, request

from api.auth_routes import token_required
from api.routes import error_response
from services.pdf_proxy import PdfProxyError, resolve_to_bytes

logger = logging.getLogger(__name__)

# Separate blueprint — registered with the same /api/workspace prefix as
# workspace_api but kept in its own module for strict isolation.
pdf_proxy_api = Blueprint("pdf_proxy_api", __name__)


@pdf_proxy_api.route("/pdf-proxy", methods=["POST"])
@token_required
def proxy_pdf(current_user):
    payload = request.get_json(silent=True) or {}
    source = payload.get("source")
    if source is None:
        return error_response("source is required", 400)

    try:
        data, filename = resolve_to_bytes(current_user, source)
    except PdfProxyError as e:
        return error_response(str(e), e.status_code)
    except Exception:
        logger.exception("PDF proxy: unexpected error")
        return error_response("Internal error while fetching PDF", 500)

    # Stream the bytes back as a raw PDF. We do NOT wrap in the success
    # envelope because the client reads this as an ArrayBuffer for pdf.js.
    return Response(
        data,
        mimetype="application/pdf",
        headers={
            "Content-Length": str(len(data)),
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
