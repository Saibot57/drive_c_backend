from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import event
from sqlalchemy.engine import Engine
import logging

# Set up logging
logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)

db = SQLAlchemy()

# Add ping function to keep connection alive
@event.listens_for(Engine, "engine_connect")
def ping_connection(connection, branch):
    if branch:
        return

    try:
        connection.scalar("SELECT 1")
    except Exception:
        raw_conn = getattr(connection.connection, "connection", None)
        if raw_conn is not None and hasattr(raw_conn, "ping"):
            raw_conn.ping()

class DriveFile(db.Model):
    __tablename__ = 'drive_files'

    id = db.Column(db.String(100), primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    url = db.Column(db.String(500))
    tags = db.Column(db.String(500))
    notebooklm = db.Column(db.String(500))
    created_time = db.Column(db.DateTime, default=datetime.utcnow)
    is_folder = db.Column(db.Boolean, default=False)

    # Add explicit foreign key reference to users table
    user_id = db.Column(db.String(100), db.ForeignKey('users.id'), nullable=True)

class NoteContent(db.Model):
    __tablename__ = 'note_contents'

    id = db.Column(db.String(100), primary_key=True)
    file_id = db.Column(db.String(100), db.ForeignKey('drive_files.id', ondelete='CASCADE'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_time = db.Column(db.DateTime, default=datetime.utcnow)
    updated_time = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship with DriveFile with cascade delete
    file = db.relationship('DriveFile', backref=db.backref('note_content', lazy=True, cascade='all, delete-orphan'))