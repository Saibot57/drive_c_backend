from datetime import datetime
from services.db_config import db
import uuid
import json


class Surface(db.Model):
    __tablename__ = 'surfaces'

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False, default='Untitled')
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def generate_id():
        return str(uuid.uuid4())

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'sort_order': self.sort_order,
            'is_archived': self.is_archived,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class WorkspaceElement(db.Model):
    __tablename__ = 'workspace_elements'

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36), nullable=False, index=True)
    type = db.Column(db.String(20), nullable=False)  # text | table | mindmap | list
    title = db.Column(db.String(255), nullable=False, default='Untitled')
    content = db.Column(db.Text)  # JSON-serialized
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    VALID_TYPES = {'text', 'table', 'mindmap', 'list', 'kanban', 'sticky', 'pdf', 'image', 'link'}

    @staticmethod
    def generate_id():
        return str(uuid.uuid4())

    def get_content(self):
        if self.content:
            try:
                return json.loads(self.content)
            except (json.JSONDecodeError, TypeError):
                return self.content
        return None

    def set_content(self, data):
        if data is not None:
            self.content = json.dumps(data, ensure_ascii=False)
        else:
            self.content = None

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'type': self.type,
            'title': self.title,
            'content': self.get_content(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class SurfaceElement(db.Model):
    __tablename__ = 'surface_elements'

    id = db.Column(db.String(36), primary_key=True)
    surface_id = db.Column(db.String(36), nullable=False, index=True)
    element_id = db.Column(db.String(36), nullable=False, index=True)
    position_x = db.Column(db.Float, nullable=False, default=0.0)
    position_y = db.Column(db.Float, nullable=False, default=0.0)
    width = db.Column(db.Float, nullable=False, default=320.0)
    height = db.Column(db.Float, nullable=False, default=200.0)
    is_locked = db.Column(db.Boolean, nullable=False, default=True)
    is_on_canvas = db.Column(db.Boolean, nullable=False, default=True)
    z_index = db.Column(db.Integer, nullable=False, default=0)

    @staticmethod
    def generate_id():
        return str(uuid.uuid4())

    def to_dict(self):
        return {
            'id': self.id,
            'surface_id': self.surface_id,
            'element_id': self.element_id,
            'position_x': self.position_x,
            'position_y': self.position_y,
            'width': self.width,
            'height': self.height,
            'is_locked': self.is_locked,
            'is_on_canvas': self.is_on_canvas,
            'z_index': self.z_index,
        }
