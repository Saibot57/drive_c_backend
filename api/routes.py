# api/routes.py
from flask import Blueprint, jsonify, request
from sqlalchemy import text, or_, and_
from services.db_config import db, DriveFile
from services.drive_connect import authenticate_drive_api, build_folder_tree, save_to_database_with_session
from config.settings import FOLDER_ID
from api.auth_routes import token_required
import logging
from datetime import datetime

logger = logging.getLogger(__name__)
api = Blueprint('api', __name__)


def success_response(data=None, status_code=200):
    return jsonify({"success": True, "data": data if data is not None else {}, "error": None}), status_code


def error_response(message, status_code=400, data=None):
    return jsonify({"success": False, "data": data, "error": message}), status_code

def check_database_connection():
    """Check database connection"""
    try:
        db.session.execute(text("SELECT 1"))
        return "connected"
    except Exception as e:
        logger.error(f"Database connection error: {str(e)}")
        return str(e)

@api.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    db_status = check_database_connection()
    if db_status == "connected":
        return success_response({"status": "healthy", "database": db_status})
    return error_response("unhealthy", 500, {"database": db_status})

@api.route('/files', methods=['GET'])
@token_required
def get_files(current_user):
    """Get all files (is_folder=False) with optional search, grouped by top-level folder."""
    try:
        query = DriveFile.query.filter_by(is_folder=False, user_id=current_user.id)

        # Optional search
        q = (request.args.get('search') or "").strip()
        if q:
            like = f"%{q}%"
            query = query.filter(or_(
                DriveFile.name.ilike(like),
                DriveFile.tags.ilike(like),
                DriveFile.file_path.ilike(like)
            ))

        files = query.all()
        logger.info(f"Found {len(files)} files matching query")

        # Build grouped structure: { top_folder: { name, path, subsections, files } }
        top_level_sections = {}

        for f in files:
            # Normalisera och splitta sökväg. Ex: "/A/B/file.md" -> ["A", "B", "file.md"]
            parts = (f.file_path or "/").lstrip("/").split("/")
            parts = [p for p in parts if p]  # ta bort tomma

            if not parts or len(parts) == 1:
                top_folder = "Uncategorized"
                top_path = "/"
                subsection = None
            else:
                top_folder = parts[0]
                top_path = f"/{top_folder}"
                subsection = parts[1] if len(parts) >= 3 else None  # endast en nivå av subsections

            if top_folder not in top_level_sections:
                top_level_sections[top_folder] = {
                    "name": top_folder,
                    "path": top_path,
                    "subsections": {},
                    "files": []
                }

            file_payload = {
                'id': f.id,
                'name': f.name,
                'url': f.url,
                'tags': f.tags.split(',') if f.tags else [],
                'notebooklm': f.notebooklm,
                'file_path': f.file_path,
                'created_time': f.created_time.isoformat() if f.created_time else None
            }

            if subsection:
                if subsection not in top_level_sections[top_folder]["subsections"]:
                    top_level_sections[top_folder]["subsections"][subsection] = {
                        "name": subsection,
                        "path": f"{top_path}/{subsection}",
                        "files": []
                    }
                top_level_sections[top_folder]["subsections"][subsection]["files"].append(file_payload)
            else:
                top_level_sections[top_folder]["files"].append(file_payload)

        return success_response(list(top_level_sections.values()))

    except Exception as e:
        logger.error(f"Error in get_files: {str(e)}")
        db.session.remove()
        return error_response("Failed to fetch files", 500)

@api.route('/update', methods=['POST'])
@token_required
def update_files(current_user):
    """Update files from Google Drive using a dedicated session."""
    logger.info("Starting update from Google Drive")
    try:
        # 1) Hämta data från Drive utanför DB-transaktion
        logger.info("Fetching data from Google Drive")
        service = authenticate_drive_api()
        folder_tree = build_folder_tree(service, FOLDER_ID)

        session = db.session
        try:
            logger.info("Finding notes to preserve")
            notes_to_preserve = session.query(DriveFile).filter(
                and_(
                    or_(DriveFile.url.is_(None), DriveFile.url == ''),
                    DriveFile.is_folder.is_(False),
                    DriveFile.user_id == current_user.id
                )
            ).all()
            preserved_notes = {n.file_path: n for n in notes_to_preserve}
            logger.info(f"Found {len(preserved_notes)} notes to preserve")

            logger.info("Clearing existing Google Drive records")
            session.query(DriveFile).filter(
                and_(DriveFile.url.isnot(None), DriveFile.user_id == current_user.id)
            ).delete(synchronize_session=False)

            logger.info("Saving new data to database")
            save_to_database_with_session(folder_tree, current_user.id, session)

            session.commit()
            logger.info("Successfully updated files from Google Drive")
            return success_response({
                "message": "Files updated successfully",
                "timestamp": datetime.utcnow().isoformat()
            })

        except Exception as e:
            session.rollback()
            logger.error(f"Database operation failed: {str(e)}")
            raise

    except Exception as e:
        logger.error(f"Failed to update files: {str(e)}")
        return error_response("Failed to update files", 500)

@api.route('/sections', methods=['GET'])
@token_required
def get_sections(current_user):
    """Get all unique sections/folders (is_folder=True)."""
    try:
        files = DriveFile.query.filter_by(is_folder=True, user_id=current_user.id) \
                               .order_by(DriveFile.file_path.asc()).all()
        sections = [{
            'id': f.id,
            'name': f.name,
            'path': f.file_path
        } for f in files]

        logger.info(f"Found {len(sections)} sections")
        return success_response(sections)
    except Exception as e:
        logger.error(f"Error in get_sections: {str(e)}")
        return error_response("Failed to fetch sections", 500)
