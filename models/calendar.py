# models/calendar.py
from datetime import datetime
from services.db_config import db
import uuid

class CalendarEvent(db.Model):
    __tablename__ = 'calendar_events'

    id = db.Column(db.String(100), primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    # Keep columns as naive datetimes - we'll consistently treat them as UTC
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    notes = db.Column(db.Text)
    color = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Foreign key with explicit reference to users table
    user_id = db.Column(db.String(100), db.ForeignKey('users.id'), nullable=True)

    @staticmethod
    def generate_id():
        return str(uuid.uuid4())

class DayNote(db.Model):
    __tablename__ = 'day_notes'

    id = db.Column(db.String(100), primary_key=True)
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Updated foreign key with explicit reference to users table
    user_id = db.Column(db.String(100), db.ForeignKey('users.id'), nullable=True)

    @staticmethod
    def generate_id():
        return str(uuid.uuid4())