from datetime import datetime
from services.db_config import db
import uuid


class NoteTemplate(db.Model):
    __tablename__ = 'note_templates'

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    skeleton = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    @staticmethod
    def generate_id():
        return str(uuid.uuid4())

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'skeleton': self.skeleton,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class CCNote(db.Model):
    __tablename__ = 'cc_notes'

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False, default='')
    content = db.Column(db.Text)
    tags = db.Column(db.String(500))  # comma-separated
    template_id = db.Column(db.String(36))  # soft reference, no FK
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def generate_id():
        return str(uuid.uuid4())

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'title': self.title,
            'content': self.content,
            'tags': [t.strip() for t in self.tags.split(',') if t.strip()] if self.tags else [],
            'template_id': self.template_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class CCTodo(db.Model):
    __tablename__ = 'cc_todos'

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36), nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(10), nullable=False, default='date')  # 'week' | 'date'
    target_date = db.Column(db.Date)
    week_number = db.Column(db.Integer)
    status = db.Column(db.String(20), nullable=False, default='open')  # 'open' | 'done'
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def generate_id():
        return str(uuid.uuid4())

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'content': self.content,
            'type': self.type,
            'target_date': self.target_date.isoformat() if self.target_date else None,
            'week_number': self.week_number,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
