from services.db_config import db
import uuid


class PlannerActivity(db.Model):
    __tablename__ = "planner_activity"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # user_id har här ändrats till en vanlig String(36) utan ForeignKey för att undvika
    # OperationalError 3780 vid inkompatibla tabellinställningar i MySQL.
    user_id = db.Column(db.String(36), nullable=False, index=True)
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


class PlannerCourse(db.Model):
    __tablename__ = "planner_course"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    teacher = db.Column(db.String(150), nullable=True)
    room = db.Column(db.String(150), nullable=True)
    duration = db.Column(db.Integer, nullable=False, default=60)
    color = db.Column(db.String(20), nullable=True)
    category = db.Column(db.String(50), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "teacher": self.teacher,
            "room": self.room,
            "duration": self.duration,
            "color": self.color,
            "category": self.category,
        }
