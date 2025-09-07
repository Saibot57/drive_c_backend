# api/notes_routes.py
from flask import Blueprint, jsonify, request
from sqlalchemy import and_, or_
from services.db_config import db, DriveFile, NoteContent
from api.auth_routes import token_required
import logging
from datetime import datetime
import os
import uuid

logger = logging.getLogger(__name__)
notes = Blueprint('notes', __name__)


def success_response(data=None, status_code=200):
    return jsonify({"success": True, "data": data if data is not None else {}, "error": None}), status_code


def error_response(message, status_code=400, data=None):
    return jsonify({"success": False, "data": data, "error": message}), status_code

# --- Hjälpare ---
def _norm_path(p: str) -> str:
    """Normalisera sökväg: ledande '/', ingen trailing '/' (utom för root)."""
    if p is None or p == "":
        return "/"
    p = p.strip()
    if not p.startswith("/"):
        p = "/" + p
    p = p.rstrip("/")
    return "/" if p == "" else p

def _now_utc():
    return datetime.utcnow()

def _normalize_tags(tags):
    """Tillåt både lista och sträng; lagra som kommaseparerad sträng."""
    if tags is None:
        return ""
    if isinstance(tags, list):
        return ",".join([str(t).strip() for t in tags if str(t).strip()])
    return str(tags).strip()

# --------------------- List files ---------------------

@notes.route('/files', methods=['GET'])
@token_required
def list_files(current_user):
    """List files in a given directory (query: path, default='/')."""
    try:
        path = _norm_path(request.args.get('path', '/'))
        logger.info(f"Listing files at path: {path}")

        try:
            if path == '/':
                # Root: antingen exakt '/', eller direkt under root ("/name", men inte "/a/b")
                files = DriveFile.query.filter(
                    and_(
                        DriveFile.user_id == current_user.id,
                        or_(
                            DriveFile.file_path == '/',
                            and_(DriveFile.file_path.like('/%'), ~DriveFile.file_path.like('/%/%'))
                        )
                    )
                ).order_by(DriveFile.is_folder.desc(), DriveFile.name.asc()).all()
            else:
                # Annan katalog: antingen exakt katalogen själv eller poster direkt i den
                files = DriveFile.query.filter(
                    and_(
                        DriveFile.user_id == current_user.id,
                        or_(
                            DriveFile.file_path == path,
                            and_(DriveFile.file_path.like(f"{path}/%"), ~DriveFile.file_path.like(f"{path}/%/%"))
                        )
                    )
                ).order_by(DriveFile.is_folder.desc(), DriveFile.name.asc()).all()

            # Filtrera bort katalogen själv från resultatet
            filtered = [f for f in files if not (f.is_folder and f.file_path == path)]

            response_data = [{
                'id': f.id,
                'name': f.name,
                'file_path': f.file_path,
                'is_folder': f.is_folder,
                'tags': f.tags.split(',') if f.tags else [],
                'url': f.url,
                'created_time': f.created_time.isoformat() if f.created_time else None
            } for f in filtered]

            return success_response(response_data)

        except Exception as db_error:
            logger.error(f"Database error in list_files: {str(db_error)}")
            db.session.rollback()
            return error_response("Database error", 500)

    except Exception as e:
        logger.error(f"Error in list_files: {str(e)}")
        return error_response("Failed to list files", 500)

# --------------------- Create directory ---------------------

@notes.route('/directory', methods=['POST'])
@token_required
def create_directory(current_user):
    """Create a new directory."""
    try:
        data = request.get_json(silent=True) or {}
        if 'path' not in data:
            return error_response("Path is required", 400)

        path = _norm_path(data['path'])
        dir_name = os.path.basename(path)
        parent_path = os.path.dirname(path) or "/"

        logger.info(f"Creating directory: {dir_name} at {parent_path}")

        # Finns katalog redan?
        existing_dir = DriveFile.query.filter_by(
            file_path=path, is_folder=True, user_id=current_user.id
        ).first()
        if existing_dir:
            return error_response(f"Directory already exists: {path}", 400)

        # För icke-root: kräver existerande parent
        if parent_path != "/":
            parent_dir = DriveFile.query.filter_by(
                file_path=parent_path, is_folder=True, user_id=current_user.id
            ).first()
            if not parent_dir:
                return error_response(f"Parent directory does not exist: {parent_path}", 400)

        new_dir = DriveFile(
            id=str(uuid.uuid4()),
            name=dir_name,
            file_path=path,
            is_folder=True,
            created_time=_now_utc(),
            user_id=current_user.id
        )
        db.session.add(new_dir)
        db.session.commit()

        return success_response({
            "id": new_dir.id,
            "name": new_dir.name,
            "file_path": new_dir.file_path,
            "is_folder": True,
            "created_time": new_dir.created_time.isoformat()
        })
    except Exception as e:
        logger.error(f"Error in create_directory: {str(e)}")
        db.session.rollback()
        return error_response("Failed to create directory", 500)

# --------------------- Save note ---------------------

@notes.route('/file', methods=['POST'])
@token_required
def save_note(current_user):
    """Create or update a note file."""
    try:
        data = request.get_json(silent=True) or {}
        if 'path' not in data or 'content' not in data:
            return error_response("Path and content are required", 400)

        path = _norm_path(data['path'])
        content = data['content']
        tags = _normalize_tags(data.get('tags', ''))
        description = (data.get('description') or "").strip()

        file_name = os.path.basename(path)
        parent_path = os.path.dirname(path) or "/"

        logger.info(f"Saving note: {file_name} at {parent_path}")

        # Parent måste finnas om ej root
        if parent_path != "/":
            parent_dir = DriveFile.query.filter_by(
                file_path=parent_path, is_folder=True, user_id=current_user.id
            ).first()
            if not parent_dir:
                return error_response(f"Parent directory does not exist: {parent_path}", 400)

        existing_file = DriveFile.query.filter_by(
            file_path=path, is_folder=False, user_id=current_user.id
        ).first()

        if existing_file:
            existing_file.name = file_name
            existing_file.tags = tags
            existing_file.notebooklm = description  # använder fältet notebooklm som beskrivning

            note_content = NoteContent.query.filter_by(file_id=existing_file.id).first()
            if note_content:
                note_content.content = content
                note_content.updated_time = _now_utc()
            else:
                note_content = NoteContent(
                    id=str(uuid.uuid4()),
                    file_id=existing_file.id,
                    content=content,
                    updated_time=_now_utc()
                )
                db.session.add(note_content)

            db.session.commit()
            file_id = existing_file.id
            message = "Note updated successfully"
        else:
            new_file = DriveFile(
                id=str(uuid.uuid4()),
                name=file_name,
                file_path=path,
                is_folder=False,
                tags=tags,
                notebooklm=description,
                created_time=_now_utc(),
                user_id=current_user.id
            )
            db.session.add(new_file)
            db.session.flush()  # hämta id

            note_content = NoteContent(
                id=str(uuid.uuid4()),
                file_id=new_file.id,
                content=content,
                updated_time=_now_utc()
            )
            db.session.add(note_content)
            db.session.commit()

            file_id = new_file.id
            message = "Note created successfully"

        return success_response({"id": file_id, "name": file_name, "file_path": path, "message": message})
    except Exception as e:
        logger.error(f"Error in save_note: {str(e)}")
        db.session.rollback()
        return error_response("Failed to save note", 500)

# --------------------- Get note ---------------------

@notes.route('/file', methods=['GET'])
@token_required
def get_note(current_user):
    """Get the content of a note file (query: path)."""
    try:
        path = request.args.get('path')
        if not path:
            return error_response("Path is required", 400)
        path = _norm_path(path)

        logger.info(f"Getting note content from: {path}")

        note_file = DriveFile.query.filter_by(
            file_path=path, is_folder=False, user_id=current_user.id
        ).first()
        if not note_file:
            return error_response(f"Note not found: {path}", 404)

        note_content = NoteContent.query.filter_by(file_id=note_file.id).first()
        if not note_content:
            # Skapa tomt innehåll vid behov
            note_content = NoteContent(
                id=str(uuid.uuid4()),
                file_id=note_file.id,
                content="",
                updated_time=_now_utc()
            )
            db.session.add(note_content)
            db.session.commit()

        tags = note_file.tags.split(',') if note_file.tags else []
        description = note_file.notebooklm or ""

        return success_response({
            "id": note_file.id,
            "content": note_content.content,
            "tags": tags,
            "description": description
        })
    except Exception as e:
        logger.error(f"Error in get_note: {str(e)}")
        return error_response("Failed to get note", 500)

# --------------------- Delete file/dir ---------------------

@notes.route('/file', methods=['DELETE'])
@token_required
def delete_file(current_user):
    """Delete a file or directory (query: path)."""
    try:
        path = request.args.get('path')
        if not path:
            return error_response("Path is required", 400)
        path = _norm_path(path)

        logger.info(f"Deleting file or directory: {path}")

        file_item = DriveFile.query.filter_by(file_path=path, user_id=current_user.id).first()
        if not file_item:
            return error_response(f"Item not found: {path}", 404)

        # Om katalog: radera alla barn först
        if file_item.is_folder:
            children = DriveFile.query.filter(
                and_(DriveFile.file_path.like(f"{path}/%"), DriveFile.user_id == current_user.id)
            ).all()
            for child in children:
                nc = NoteContent.query.filter_by(file_id=child.id).first()
                if nc:
                    db.session.delete(nc)
                db.session.delete(child)

        # Radera ev. NoteContent för det primära objektet
        nc = NoteContent.query.filter_by(file_id=file_item.id).first()
        if nc:
            db.session.delete(nc)

        db.session.delete(file_item)
        db.session.commit()

        return success_response({"message": f"Successfully deleted: {path}"})
    except Exception as e:
        logger.error(f"Error in delete_file: {str(e)}")
        db.session.rollback()
        return error_response("Failed to delete file", 500)

# --------------------- Move file/dir ---------------------

@notes.route('/move', methods=['POST'])
@token_required
def move_file(current_user):
    """Move a file or directory to a new location.
    Body: { "source": "/old/path/file.md", "destination": "/new/path/file.md" }
    """
    try:
        data = request.get_json(silent=True) or {}
        if 'source' not in data or 'destination' not in data:
            return error_response("Source and destination paths are required", 400)

        source_path = _norm_path(data['source'])
        destination_path = _norm_path(data['destination'])

        if source_path == "/" or destination_path == "/":
            return error_response("Cannot move root", 400)

        # Förhindra att man flyttar mappen in i sig själv
        if source_path != destination_path and destination_path.startswith(source_path + "/"):
            return error_response("Cannot move a directory into itself", 400)

        logger.info(f"Moving from {source_path} to {destination_path}")

        source_file = DriveFile.query.filter_by(
            file_path=source_path, user_id=current_user.id
        ).first()
        if not source_file:
            return error_response(f"Source path not found: {source_path}", 404)

        # Validera att destinationens parent finns (om inte root)
        parent_path = os.path.dirname(destination_path) or "/"
        if parent_path != "/":
            parent_dir = DriveFile.query.filter_by(
                file_path=parent_path, is_folder=True, user_id=current_user.id
            ).first()
            if not parent_dir:
                return error_response(f"Destination directory does not exist: {parent_path}", 400)

        # Destination får inte redan finnas
        if DriveFile.query.filter_by(file_path=destination_path, user_id=current_user.id).first():
            return error_response(f"Destination already exists: {destination_path}", 400)

        if source_file.is_folder:
            # Flytta alla barn
            children = DriveFile.query.filter(
                and_(DriveFile.file_path.like(f"{source_path}/%"), DriveFile.user_id == current_user.id)
            ).all()
            logger.info(f"Found {len(children)} children to move")
            for child in children:
                child.file_path = child.file_path.replace(source_path, destination_path, 1)

        # Flytta själva noden
        source_file.file_path = destination_path
        db.session.commit()

        return success_response({"message": f"Successfully moved {source_path} to {destination_path}", "new_path": destination_path})
    except Exception as e:
        logger.error(f"Error in move_file: {str(e)}")
        db.session.rollback()
        return error_response("Failed to move file", 500)
