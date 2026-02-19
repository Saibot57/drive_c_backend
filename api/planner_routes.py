from flask import Blueprint, request
from services.db_config import db
from models.planner_models import PlannerActivity, PlannerCourse
from api.auth_routes import token_required
from api.routes import success_response, error_response
from sqlalchemy.exc import OperationalError, IntegrityError
from functools import wraps
from time import sleep
import uuid
import re
import logging

# Configure logger
logger = logging.getLogger(__name__)

planner_api = Blueprint("planner_api", __name__)

# Regex for HH:MM format (00:00 to 23:59)
TIME_FORMAT_REGEX = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')

# Allow-list for inbound activity fields
ALLOWED_ACTIVITY_INBOUND_FIELDS = {
    "id",
    "title",
    "teacher",
    "room",
    "notes",
    "day",
    "startTime",
    "endTime",
    "color",
    "category",
    "duration",
}

# --- Helpers ---

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

def _calculate_duration_minutes(start_time: str, end_time: str) -> int:
    sh, sm = map(int, start_time.split(':'))
    eh, em = map(int, end_time.split(':'))
    return (eh * 60 + em) - (sh * 60 + sm)

def _coerce_positive_int(name: str, value, default: int):
    if value is None:
        value = default
    try:
        iv = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")
    if iv <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return iv

def _serialize_activity(activity: PlannerActivity):
    return {
        "id": activity.id,
        "userId": activity.user_id,
        "title": activity.title,
        "teacher": activity.teacher,
        "room": activity.room,
        "notes": activity.notes,
        "day": activity.day,
        "startTime": activity.start_time,
        "endTime": activity.end_time,
        "color": activity.color,
        "category": activity.category,
        "duration": activity.duration,
        "archiveName": activity.archive_name,
    }

def _serialize_course(course: PlannerCourse):
    return {
        "id": course.id,
        "title": course.title,
        "teacher": course.teacher or "",
        "room": course.room or "",
        "duration": course.duration,
        "color": course.color,
        "category": course.category,
    }

# --- Activity Routes ---

@planner_api.route("/activities", methods=["GET"])
@token_required
@retry_on_connection_error
def get_planner_activities(current_user):
    archive_name = request.args.get("archive_name")
    if archive_name is None:
        activities = PlannerActivity.query.filter_by(user_id=current_user.id, archive_name=None).all()
    else:
        activities = PlannerActivity.query.filter_by(user_id=current_user.id, archive_name=archive_name).all()
    return success_response([_serialize_activity(activity) for activity in activities])

@planner_api.route("/archives", methods=["GET"])
@token_required
@retry_on_connection_error
def get_planner_archives(current_user):
    archive_rows = (
        db.session.query(PlannerActivity.archive_name)
        .filter(PlannerActivity.user_id == current_user.id, PlannerActivity.archive_name.isnot(None))
        .distinct().all()
    )
    archives = [row.archive_name for row in archive_rows]
    return success_response(archives)

@planner_api.route("/activities", methods=["POST"])
@planner_api.route("/activities/sync", methods=["POST"])
@token_required
@retry_on_connection_error
def sync_planner_activities(current_user):
    payload = request.get_json(silent=True)
    archive_name = None
    activities_payload = payload
    if isinstance(payload, dict):
        archive_name = payload.get("archiveName")
        activities_payload = payload.get("activities")

    if not isinstance(activities_payload, list):
        return error_response("Payload must be a list of activities", 400)

    try:
        new_activities = []
        for item in activities_payload:
            # Respect client IDs if they exist to prevent ID churn and preserve Undo stack
            # This is the fix discussed with the agent.
            activity_id = item.get("id") or str(uuid.uuid4())

            item = {k: v for k, v in item.items() if k in ALLOWED_ACTIVITY_INBOUND_FIELDS}
            title, day = item.get("title"), item.get("day")
            start_time, end_time = item.get("startTime"), item.get("endTime")

            if not title or not day or not start_time or not end_time:
                raise ValueError("Required fields missing")
            if not TIME_FORMAT_REGEX.match(start_time) or not TIME_FORMAT_REGEX.match(end_time):
                raise ValueError("Invalid time format")

            duration = _calculate_duration_minutes(start_time, end_time)
            new_activities.append(PlannerActivity(
                id=activity_id,
                user_id=current_user.id,
                title=title.strip(),
                teacher=item.get("teacher") or "",
                room=item.get("room") or "",
                notes=item.get("notes") or "",
                day=day.strip(),
                start_time=start_time,
                end_time=end_time,
                color=item.get("color"),
                category=item.get("category"),
                duration=duration,
                archive_name=archive_name
            ))

        filter_args = {"user_id": current_user.id, "archive_name": archive_name}
        PlannerActivity.query.filter_by(**filter_args).delete(synchronize_session=False)
        db.session.add_all(new_activities)
        db.session.commit()
        return success_response({"count": len(new_activities), "activities": [_serialize_activity(a) for a in new_activities]}, 201)
    except Exception as e:
        db.session.rollback()
        return error_response(str(e), 400)

@planner_api.route("/activities", methods=["DELETE"])
@token_required
@retry_on_connection_error
def delete_planner_activities(current_user):
    archive_name = request.args.get("archive_name")
    PlannerActivity.query.filter_by(user_id=current_user.id, archive_name=archive_name).delete(synchronize_session=False)
    db.session.commit()
    return success_response({"message": "Deleted"})

# --- Course Routes ---

@planner_api.route("/courses", methods=["GET"])
@token_required
@retry_on_connection_error
def get_planner_courses(current_user):
    courses = PlannerCourse.query.filter_by(user_id=current_user.id).all()
    return success_response([_serialize_course(c) for c in courses])

@planner_api.route("/courses/sync", methods=["POST"])
@token_required
@retry_on_connection_error
def sync_planner_courses(current_user):
    payload = request.get_json(silent=True)
    courses_payload = payload.get("courses") if isinstance(payload, dict) else payload
    if not isinstance(courses_payload, list):
        return error_response("Invalid payload", 400)

    try:
        new_courses = []
        for item in courses_payload:
            title = item.get("title")
            if not title: raise ValueError("Title required")

            # Courses already respected client-supplied IDs
            course_id = item.get("id") or str(uuid.uuid4())
            new_courses.append(PlannerCourse(
                id=course_id, user_id=current_user.id, title=title.strip(),
                teacher=item.get("teacher"), room=item.get("room"),
                duration=_coerce_positive_int("duration", item.get("duration"), 60),
                color=item.get("color"), category=item.get("category")
            ))

        PlannerCourse.query.filter_by(user_id=current_user.id).delete(synchronize_session=False)
        db.session.add_all(new_courses)
        db.session.commit()
        return success_response({"count": len(new_courses)}, 201)
    except Exception as e:
        db.session.rollback()
        return error_response(str(e), 400)