from flask import Blueprint, request
from services.db_config import db
from models.theme_models import UserTheme, ThemePreset
from api.auth_routes import token_required
from api.routes import success_response, error_response
from sqlalchemy.exc import OperationalError
from functools import wraps
from time import sleep
import json
import logging

logger = logging.getLogger(__name__)

theme_api = Blueprint("theme_api", __name__)


def retry_on_connection_error(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except OperationalError as e:
                logger.warning("DB OperationalError (attempt %s/3): %s", attempt + 1, e)
                db.session.rollback()
                if attempt < 2:
                    sleep(0.5)
                    continue
                raise
    return wrapper


# ============================================================
# USER THEME (active tokens)
# ============================================================

@theme_api.route("", methods=["GET"])
@token_required
@retry_on_connection_error
def get_theme(current_user):
    theme = UserTheme.query.filter_by(user_id=current_user.id).first()
    tokens = json.loads(theme.tokens) if theme and theme.tokens else {}
    return success_response(tokens)


@theme_api.route("", methods=["PUT"])
@token_required
@retry_on_connection_error
def save_theme(current_user):
    data = request.get_json(silent=True) or {}
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return error_response("tokens must be an object", 400)

    theme = UserTheme.query.filter_by(user_id=current_user.id).first()
    if theme:
        theme.tokens = json.dumps(tokens)
    else:
        theme = UserTheme(
            id=UserTheme.generate_id(),
            user_id=current_user.id,
            tokens=json.dumps(tokens),
        )
        db.session.add(theme)
    db.session.commit()
    return success_response(json.loads(theme.tokens))


@theme_api.route("", methods=["DELETE"])
@token_required
@retry_on_connection_error
def reset_theme(current_user):
    theme = UserTheme.query.filter_by(user_id=current_user.id).first()
    if theme:
        db.session.delete(theme)
        db.session.commit()
    return success_response({"reset": True})


# ============================================================
# THEME PRESETS
# ============================================================

@theme_api.route("/presets", methods=["GET"])
@token_required
@retry_on_connection_error
def get_presets(current_user):
    presets = ThemePreset.query.filter_by(user_id=current_user.id).order_by(ThemePreset.created_at.desc()).all()
    return success_response([p.to_dict() for p in presets])


@theme_api.route("/presets", methods=["POST"])
@token_required
@retry_on_connection_error
def create_preset(current_user):
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return error_response("name is required", 400)
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return error_response("tokens must be an object", 400)

    preset = ThemePreset(
        id=ThemePreset.generate_id(),
        user_id=current_user.id,
        name=name,
        tokens=json.dumps(tokens),
    )
    db.session.add(preset)
    db.session.commit()
    return success_response(preset.to_dict(), 201)


@theme_api.route("/presets/<preset_id>", methods=["DELETE"])
@token_required
@retry_on_connection_error
def delete_preset(current_user, preset_id):
    preset = ThemePreset.query.filter_by(id=preset_id, user_id=current_user.id).first()
    if not preset:
        return error_response("Preset not found", 404)
    db.session.delete(preset)
    db.session.commit()
    return success_response({"deleted_id": preset_id})
