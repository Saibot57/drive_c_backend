from datetime import datetime
from services.db_config import db
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
from sqlalchemy.orm import relationship

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.String(100), primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    # Relations (add these when needed)

    calendar_events = relationship('CalendarEvent', backref='user', lazy=True,
                                  primaryjoin="User.id==CalendarEvent.user_id")
    day_notes = relationship('DayNote', backref='user', lazy=True,
                            primaryjoin="User.id==DayNote.user_id")
    drive_files = relationship('DriveFile', backref='user', lazy=True,
                              primaryjoin="User.id==DriveFile.user_id")

    @staticmethod
    def generate_id():
        return str(uuid.uuid4())

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }