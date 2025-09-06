# models/schedule_models.py
from services.db_config import db
import uuid
from datetime import datetime

# Association table för många-till-många-relationen mellan aktiviteter och deltagare
activity_participants = db.Table('activity_participants',
    db.Column('activity_id', db.String(36), db.ForeignKey('activity.id'), primary_key=True),
    db.Column('family_member_id', db.String(36), db.ForeignKey('family_member.id'), primary_key=True)
)

class FamilyMember(db.Model):
    __tablename__ = 'family_member'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(7), nullable=False)
    icon = db.Column(db.String(10), nullable=False)

    activities = db.relationship('Activity', secondary=activity_participants, back_populates='participants')

class Activity(db.Model):
    __tablename__ = 'activity'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    series_id = db.Column(db.String(36), nullable=True, index=True)
    name = db.Column(db.String(150), nullable=False)
    icon = db.Column(db.String(10), nullable=False)
    day = db.Column(db.String(20), nullable=False)
    week = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    location = db.Column(db.String(150), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    color = db.Column(db.String(7), nullable=True)

    participants = db.relationship('FamilyMember', secondary=activity_participants, back_populates='activities')

class Settings(db.Model):
    __tablename__ = 'schedule_settings'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False, unique=True)
    show_weekends = db.Column(db.Boolean, default=False)
    day_start = db.Column(db.Integer, default=7)
    day_end = db.Column(db.Integer, default=18)