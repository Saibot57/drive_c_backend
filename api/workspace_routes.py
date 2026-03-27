from flask import Blueprint, request
from services.db_config import db
from models.workspace_models import Surface, WorkspaceElement, SurfaceElement
from api.auth_routes import token_required
from api.routes import success_response, error_response
from sqlalchemy.exc import OperationalError
from functools import wraps
from time import sleep
import logging
import json

logger = logging.getLogger(__name__)

workspace_api = Blueprint("workspace_api", __name__)


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
# SURFACES
# ============================================================

@workspace_api.route("/surfaces", methods=["GET"])
@token_required
@retry_on_connection_error
def get_surfaces(current_user):
    include_archived = request.args.get('include_archived', 'false').lower() == 'true'
    query = Surface.query.filter_by(user_id=current_user.id)
    if not include_archived:
        query = query.filter_by(is_archived=False)
    surfaces = query.order_by(Surface.sort_order).all()
    return success_response([s.to_dict() for s in surfaces])


@workspace_api.route("/surfaces", methods=["POST"])
@token_required
@retry_on_connection_error
def create_surface(current_user):
    data = request.get_json(silent=True) or {}
    name = data.get('name', 'Untitled').strip()
    if not name:
        return error_response("Name is required", 400)

    max_order = db.session.query(db.func.max(Surface.sort_order)).filter_by(
        user_id=current_user.id
    ).scalar() or 0

    surface = Surface(
        id=Surface.generate_id(),
        user_id=current_user.id,
        name=name,
        sort_order=max_order + 1,
    )
    db.session.add(surface)
    db.session.commit()
    return success_response(surface.to_dict(), 201)


@workspace_api.route("/surfaces/<surface_id>", methods=["PUT"])
@token_required
@retry_on_connection_error
def update_surface(current_user, surface_id):
    surface = Surface.query.filter_by(id=surface_id, user_id=current_user.id).first()
    if not surface:
        return error_response("Surface not found", 404)

    data = request.get_json(silent=True) or {}
    if 'name' in data:
        surface.name = data['name'].strip() or surface.name
    if 'sort_order' in data:
        surface.sort_order = int(data['sort_order'])
    if 'is_archived' in data:
        surface.is_archived = bool(data['is_archived'])

    db.session.commit()
    return success_response(surface.to_dict())


@workspace_api.route("/surfaces/<surface_id>", methods=["DELETE"])
@token_required
@retry_on_connection_error
def delete_surface(current_user, surface_id):
    surface = Surface.query.filter_by(id=surface_id, user_id=current_user.id).first()
    if not surface:
        return error_response("Surface not found", 404)

    # Remove all placements on this surface
    SurfaceElement.query.filter_by(surface_id=surface_id).delete()
    db.session.delete(surface)
    db.session.commit()
    return success_response(None)


# ============================================================
# ELEMENTS
# ============================================================

@workspace_api.route("/surfaces/<surface_id>/elements", methods=["GET"])
@token_required
@retry_on_connection_error
def get_surface_elements(current_user, surface_id):
    surface = Surface.query.filter_by(id=surface_id, user_id=current_user.id).first()
    if not surface:
        return error_response("Surface not found", 404)

    placements = SurfaceElement.query.filter_by(surface_id=surface_id).all()
    element_ids = [p.element_id for p in placements]
    elements = {e.id: e for e in WorkspaceElement.query.filter(
        WorkspaceElement.id.in_(element_ids)
    ).all()} if element_ids else {}

    result = []
    for p in placements:
        d = p.to_dict()
        el = elements.get(p.element_id)
        d['element'] = el.to_dict() if el else None
        result.append(d)

    return success_response(result)


@workspace_api.route("/elements", methods=["POST"])
@token_required
@retry_on_connection_error
def create_element(current_user):
    data = request.get_json(silent=True) or {}
    el_type = data.get('type', '').strip()
    if el_type not in WorkspaceElement.VALID_TYPES:
        return error_response(f"Invalid type. Must be one of: {', '.join(WorkspaceElement.VALID_TYPES)}", 400)

    element = WorkspaceElement(
        id=WorkspaceElement.generate_id(),
        user_id=current_user.id,
        type=el_type,
        title=data.get('title', 'Untitled').strip(),
    )
    element.set_content(data.get('content'))
    db.session.add(element)
    db.session.commit()
    return success_response(element.to_dict(), 201)


@workspace_api.route("/elements/<element_id>", methods=["PUT"])
@token_required
@retry_on_connection_error
def update_element(current_user, element_id):
    element = WorkspaceElement.query.filter_by(id=element_id, user_id=current_user.id).first()
    if not element:
        return error_response("Element not found", 404)

    data = request.get_json(silent=True) or {}
    if 'title' in data:
        element.title = data['title'].strip() or element.title
    if 'content' in data:
        element.set_content(data['content'])

    db.session.commit()
    return success_response(element.to_dict())


@workspace_api.route("/elements/<element_id>", methods=["DELETE"])
@token_required
@retry_on_connection_error
def delete_element(current_user, element_id):
    element = WorkspaceElement.query.filter_by(id=element_id, user_id=current_user.id).first()
    if not element:
        return error_response("Element not found", 404)

    SurfaceElement.query.filter_by(element_id=element_id).delete()
    db.session.delete(element)
    db.session.commit()
    return success_response(None)


# ============================================================
# PLACEMENTS
# ============================================================

@workspace_api.route("/surfaces/<surface_id>/place", methods=["POST"])
@token_required
@retry_on_connection_error
def place_element(current_user, surface_id):
    surface = Surface.query.filter_by(id=surface_id, user_id=current_user.id).first()
    if not surface:
        return error_response("Surface not found", 404)

    data = request.get_json(silent=True) or {}
    element_id = data.get('element_id')
    if not element_id:
        return error_response("element_id is required", 400)

    element = WorkspaceElement.query.filter_by(id=element_id, user_id=current_user.id).first()
    if not element:
        return error_response("Element not found", 404)

    # Calculate next z_index
    max_z = db.session.query(db.func.max(SurfaceElement.z_index)).filter_by(
        surface_id=surface_id
    ).scalar() or 0

    placement = SurfaceElement(
        id=SurfaceElement.generate_id(),
        surface_id=surface_id,
        element_id=element_id,
        position_x=data.get('position_x', 0),
        position_y=data.get('position_y', 0),
        width=data.get('width', 320),
        height=data.get('height', 200),
        is_locked=data.get('is_locked', False),
        is_on_canvas=True,
        z_index=max_z + 1,
    )
    db.session.add(placement)
    db.session.commit()

    result = placement.to_dict()
    result['element'] = element.to_dict()
    return success_response(result, 201)


@workspace_api.route("/placements/<placement_id>", methods=["PUT"])
@token_required
@retry_on_connection_error
def update_placement(current_user, placement_id):
    placement = SurfaceElement.query.filter_by(id=placement_id).first()
    if not placement:
        return error_response("Placement not found", 404)

    # Verify ownership via surface
    surface = Surface.query.filter_by(id=placement.surface_id, user_id=current_user.id).first()
    if not surface:
        return error_response("Placement not found", 404)

    data = request.get_json(silent=True) or {}
    for field in ('position_x', 'position_y', 'width', 'height'):
        if field in data:
            setattr(placement, field, float(data[field]))
    if 'is_locked' in data:
        placement.is_locked = bool(data['is_locked'])
    if 'is_on_canvas' in data:
        placement.is_on_canvas = bool(data['is_on_canvas'])
    if 'z_index' in data:
        placement.z_index = int(data['z_index'])

    db.session.commit()
    return success_response(placement.to_dict())


@workspace_api.route("/placements/<placement_id>", methods=["DELETE"])
@token_required
@retry_on_connection_error
def delete_placement(current_user, placement_id):
    placement = SurfaceElement.query.filter_by(id=placement_id).first()
    if not placement:
        return error_response("Placement not found", 404)

    surface = Surface.query.filter_by(id=placement.surface_id, user_id=current_user.id).first()
    if not surface:
        return error_response("Placement not found", 404)

    db.session.delete(placement)
    db.session.commit()
    return success_response(None)


# ============================================================
# MIRROR & COPY
# ============================================================

@workspace_api.route("/elements/<element_id>/mirror", methods=["POST"])
@token_required
@retry_on_connection_error
def mirror_element(current_user, element_id):
    element = WorkspaceElement.query.filter_by(id=element_id, user_id=current_user.id).first()
    if not element:
        return error_response("Element not found", 404)

    data = request.get_json(silent=True) or {}
    surface_id = data.get('surface_id')
    if not surface_id:
        return error_response("surface_id is required", 400)

    surface = Surface.query.filter_by(id=surface_id, user_id=current_user.id).first()
    if not surface:
        return error_response("Surface not found", 404)

    max_z = db.session.query(db.func.max(SurfaceElement.z_index)).filter_by(
        surface_id=surface_id
    ).scalar() or 0

    placement = SurfaceElement(
        id=SurfaceElement.generate_id(),
        surface_id=surface_id,
        element_id=element_id,
        position_x=data.get('position_x', 100),
        position_y=data.get('position_y', 100),
        width=data.get('width', 320),
        height=data.get('height', 200),
        is_locked=True,
        is_on_canvas=True,
        z_index=max_z + 1,
    )
    db.session.add(placement)
    db.session.commit()

    result = placement.to_dict()
    result['element'] = element.to_dict()
    return success_response(result, 201)


@workspace_api.route("/elements/<element_id>/copy", methods=["POST"])
@token_required
@retry_on_connection_error
def copy_element(current_user, element_id):
    element = WorkspaceElement.query.filter_by(id=element_id, user_id=current_user.id).first()
    if not element:
        return error_response("Element not found", 404)

    data = request.get_json(silent=True) or {}
    surface_id = data.get('surface_id')
    if not surface_id:
        return error_response("surface_id is required", 400)

    surface = Surface.query.filter_by(id=surface_id, user_id=current_user.id).first()
    if not surface:
        return error_response("Surface not found", 404)

    # Create independent copy
    new_element = WorkspaceElement(
        id=WorkspaceElement.generate_id(),
        user_id=current_user.id,
        type=element.type,
        title=f"{element.title} (kopia)",
        content=element.content,  # raw JSON string, independent copy
    )
    db.session.add(new_element)

    max_z = db.session.query(db.func.max(SurfaceElement.z_index)).filter_by(
        surface_id=surface_id
    ).scalar() or 0

    placement = SurfaceElement(
        id=SurfaceElement.generate_id(),
        surface_id=surface_id,
        element_id=new_element.id,
        position_x=data.get('position_x', 100),
        position_y=data.get('position_y', 100),
        width=data.get('width', 320),
        height=data.get('height', 200),
        is_locked=True,
        is_on_canvas=True,
        z_index=max_z + 1,
    )
    db.session.add(placement)
    db.session.commit()

    result = placement.to_dict()
    result['element'] = new_element.to_dict()
    return success_response(result, 201)


# ============================================================
# SEARCH
# ============================================================

@workspace_api.route("/search", methods=["GET"])
@token_required
@retry_on_connection_error
def search_elements(current_user):
    q = request.args.get('q', '').strip()
    if not q:
        return success_response([])

    deep = request.args.get('deep', 'false').lower() == 'true'
    surface_id = request.args.get('surface_id')
    el_type = request.args.get('type')

    query = WorkspaceElement.query.filter_by(user_id=current_user.id)

    if el_type and el_type in WorkspaceElement.VALID_TYPES:
        query = query.filter_by(type=el_type)

    if deep:
        query = query.filter(
            db.or_(
                WorkspaceElement.title.ilike(f'%{q}%'),
                WorkspaceElement.content.ilike(f'%{q}%'),
            )
        )
    else:
        query = query.filter(WorkspaceElement.title.ilike(f'%{q}%'))

    elements = query.limit(50).all()

    # If filtering by surface, narrow down
    if surface_id:
        placed_ids = {p.element_id for p in SurfaceElement.query.filter_by(surface_id=surface_id).all()}
        elements = [e for e in elements if e.id in placed_ids]

    # For each element, find which surfaces it's on
    results = []
    for el in elements:
        d = el.to_dict()
        placements = SurfaceElement.query.filter_by(element_id=el.id).all()
        surface_ids = list({p.surface_id for p in placements})
        surfaces = Surface.query.filter(Surface.id.in_(surface_ids)).all() if surface_ids else []
        d['surfaces'] = [{'id': s.id, 'name': s.name} for s in surfaces]
        results.append(d)

    return success_response(results)
