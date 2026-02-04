from services.db_config import db
import uuid


class PlannerActivity(db.Model):
    __tablename__ = "planner_activity"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    teacher = db.Column(db.String(150), nullable=True)
    room = db.Column(db.String(150), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    day = db.Column(db.String(20), nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    color = db.Column(db.String(7), nullable=True)
    duration = db.Column(db.Integer, nullable=False)
    archive_name = db.Column(db.String(150), nullable=True)
