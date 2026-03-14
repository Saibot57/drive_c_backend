from datetime import datetime
from services.db_config import db
import uuid


class UserTheme(db.Model):
    __tablename__ = 'user_themes'

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36), nullable=False, unique=True, index=True)
    tokens = db.Column(db.Text)  # JSON string
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def generate_id():
        return str(uuid.uuid4())

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'user_id': self.user_id,
            'tokens': json.loads(self.tokens) if self.tokens else {},
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ThemePreset(db.Model):
    __tablename__ = 'theme_presets'

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    tokens = db.Column(db.Text)  # JSON string
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    @staticmethod
    def generate_id():
        return str(uuid.uuid4())

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'user_id': self.user_id,
            'name': self.name,
            'tokens': json.loads(self.tokens) if self.tokens else {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
