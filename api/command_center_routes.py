from flask import Blueprint, request
from services.db_config import db
from models.command_center_models import CCNote, CCTodo, NoteTemplate
from api.auth_routes import token_required
from api.routes import success_response, error_response
from sqlalchemy.exc import OperationalError
from functools import wraps
from time import sleep
import logging

logger = logging.getLogger(__name__)

command_center_api = Blueprint("command_center_api", __name__)

VALID_TODO_TYPES = {'week', 'date'}
VALID_TODO_STATUSES = {'open', 'done'}


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
# TEMPLATES
# ============================================================

@command_center_api.route("/templates", methods=["GET"])
@token_required
@retry_on_connection_error
def get_templates(current_user):
    templates = NoteTemplate.query.filter_by(user_id=current_user.id).all()
    return success_response([t.to_dict() for t in templates])


@command_center_api.route("/templates", methods=["POST"])
@token_required
@retry_on_connection_error
def create_template(current_user):
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return error_response("name is required", 400)
    template = NoteTemplate(
        id=NoteTemplate.generate_id(),
        user_id=current_user.id,
        name=name,
        skeleton=data.get("skeleton"),
    )
    db.session.add(template)
    db.session.commit()
    return success_response(template.to_dict(), 201)


@command_center_api.route("/templates/<template_id>", methods=["PUT"])
@token_required
@retry_on_connection_error
def update_template(current_user, template_id):
    template = NoteTemplate.query.filter_by(id=template_id, user_id=current_user.id).first()
    if not template:
        return error_response("Template not found", 404)
    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            return error_response("name cannot be empty", 400)
        template.name = name
    if "skeleton" in data:
        template.skeleton = data["skeleton"]
    db.session.commit()
    return success_response(template.to_dict())


@command_center_api.route("/templates/<template_id>", methods=["DELETE"])
@token_required
@retry_on_connection_error
def delete_template(current_user, template_id):
    template = NoteTemplate.query.filter_by(id=template_id, user_id=current_user.id).first()
    if not template:
        return error_response("Template not found", 404)
    db.session.delete(template)
    db.session.commit()
    return success_response({"deleted_id": template_id})


# ============================================================
# NOTES
# ============================================================

@command_center_api.route("/notes", methods=["GET"])
@token_required
@retry_on_connection_error
def get_notes(current_user):
    notes = CCNote.query.filter_by(user_id=current_user.id).order_by(CCNote.updated_at.desc()).all()
    return success_response([n.to_dict() for n in notes])


@command_center_api.route("/notes/<note_id>", methods=["GET"])
@token_required
@retry_on_connection_error
def get_note(current_user, note_id):
    note = CCNote.query.filter_by(id=note_id, user_id=current_user.id).first()
    if not note:
        return error_response("Note not found", 404)
    return success_response(note.to_dict())


@command_center_api.route("/notes", methods=["POST"])
@token_required
@retry_on_connection_error
def create_note(current_user):
    data = request.get_json(silent=True) or {}
    tags_input = data.get("tags")
    if isinstance(tags_input, list):
        tags_str = ",".join(t.strip() for t in tags_input if t.strip()) or None
    else:
        tags_str = (tags_input or "").strip() or None
    note = CCNote(
        id=CCNote.generate_id(),
        user_id=current_user.id,
        title=(data.get("title") or "").strip(),
        content=data.get("content"),
        tags=tags_str,
        template_id=data.get("template_id"),
    )
    db.session.add(note)
    db.session.commit()
    return success_response(note.to_dict(), 201)


@command_center_api.route("/notes/<note_id>", methods=["PUT"])
@token_required
@retry_on_connection_error
def update_note(current_user, note_id):
    note = CCNote.query.filter_by(id=note_id, user_id=current_user.id).first()
    if not note:
        return error_response("Note not found", 404)
    data = request.get_json(silent=True) or {}
    if "title" in data:
        note.title = (data["title"] or "").strip()
    if "content" in data:
        note.content = data["content"]
    if "tags" in data:
        tags_input = data["tags"]
        if isinstance(tags_input, list):
            note.tags = ",".join(t.strip() for t in tags_input if t.strip()) or None
        else:
            note.tags = (tags_input or "").strip() or None
    if "template_id" in data:
        note.template_id = data["template_id"]
    db.session.commit()
    return success_response(note.to_dict())


@command_center_api.route("/notes/<note_id>", methods=["DELETE"])
@token_required
@retry_on_connection_error
def delete_note(current_user, note_id):
    note = CCNote.query.filter_by(id=note_id, user_id=current_user.id).first()
    if not note:
        return error_response("Note not found", 404)
    db.session.delete(note)
    db.session.commit()
    return success_response({"deleted_id": note_id})


# ============================================================
# TODOS
# ============================================================

@command_center_api.route("/todos", methods=["GET"])
@token_required
@retry_on_connection_error
def get_todos(current_user):
    query = CCTodo.query.filter_by(user_id=current_user.id)
    todo_type = request.args.get("type")
    if todo_type == "week":
        query = query.filter_by(type="week")
        week = request.args.get("week")
        if week:
            query = query.filter_by(week_number=int(week))
    elif todo_type == "date":
        query = query.filter_by(type="date")
        d = request.args.get("date")
        if d:
            query = query.filter_by(target_date=d)
    todos = query.order_by(CCTodo.created_at.desc()).all()
    return success_response([t.to_dict() for t in todos])


@command_center_api.route("/todos", methods=["POST"])
@token_required
@retry_on_connection_error
def create_todo(current_user):
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return error_response("content is required", 400)
    todo_type = (data.get("type") or "date").strip()
    if todo_type not in VALID_TODO_TYPES:
        return error_response(f"type must be one of {sorted(VALID_TODO_TYPES)}", 400)
    status = (data.get("status") or "open").strip()
    if status not in VALID_TODO_STATUSES:
        return error_response(f"status must be one of {sorted(VALID_TODO_STATUSES)}", 400)
    todo = CCTodo(
        id=CCTodo.generate_id(),
        user_id=current_user.id,
        content=content,
        type=todo_type,
        target_date=data.get("target_date"),
        week_number=data.get("week_number"),
        status=status,
    )
    db.session.add(todo)
    db.session.commit()
    return success_response(todo.to_dict(), 201)


@command_center_api.route("/todos/<todo_id>", methods=["PUT"])
@token_required
@retry_on_connection_error
def update_todo(current_user, todo_id):
    todo = CCTodo.query.filter_by(id=todo_id, user_id=current_user.id).first()
    if not todo:
        return error_response("Todo not found", 404)
    data = request.get_json(silent=True) or {}
    if "content" in data:
        content = (data["content"] or "").strip()
        if not content:
            return error_response("content cannot be empty", 400)
        todo.content = content
    if "type" in data:
        if data["type"] not in VALID_TODO_TYPES:
            return error_response(f"type must be one of {sorted(VALID_TODO_TYPES)}", 400)
        todo.type = data["type"]
    if "status" in data:
        if data["status"] not in VALID_TODO_STATUSES:
            return error_response(f"status must be one of {sorted(VALID_TODO_STATUSES)}", 400)
        todo.status = data["status"]
    if "target_date" in data:
        todo.target_date = data["target_date"]
    if "week_number" in data:
        todo.week_number = data["week_number"]
    db.session.commit()
    return success_response(todo.to_dict())


@command_center_api.route("/todos/<todo_id>", methods=["DELETE"])
@token_required
@retry_on_connection_error
def delete_todo(current_user, todo_id):
    todo = CCTodo.query.filter_by(id=todo_id, user_id=current_user.id).first()
    if not todo:
        return error_response("Todo not found", 404)
    db.session.delete(todo)
    db.session.commit()
    return success_response({"deleted_id": todo_id})
