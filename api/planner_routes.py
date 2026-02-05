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

# --- Helpers & Decorators ---

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

def _coerce_int(name, value):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")

def _calculate_duration_minutes(start_time: str, end_time: str) -> int:
    sh, sm = map(int, start_time.split(':'))
    eh, em = map(int, end_time.split(':'))
    return (eh * 60 + em) - (sh * 60 + sm)

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
        "duration": activity.duration,
        "archiveName": activity.archive_name,
    }

def _serialize_course(course: PlannerCourse):
    return {
        "id": course.id,
        "title": course.title,
        "teacher": course.teacher,
        "room": course.room,
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
        activities = PlannerActivity.query.filter_by(
            user_id=current_user.id, archive_name=None
        ).all()
    else:
        activities = PlannerActivity.query.filter_by(
            user_id=current_user.id, archive_name=archive_name
        ).all()
    return success_response([_serialize_activity(activity) for activity in activities])

@planner_api.route("/archives", methods=["GET"])
@token_required
@retry_on_connection_error
def get_planner_archives(current_user):
    archive_rows = (
        db.session.query(PlannerActivity.archive_name)
        .filter(
            PlannerActivity.user_id == current_user.id,
            PlannerActivity.archive_name.isnot(None),
        )
        .distinct()
        .all()
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

    if archive_name is not None and not isinstance(archive_name, str):
        return error_response("archiveName must be a string", 400)

    if not isinstance(activities_payload, list):
        return error_response("Payload must be a list of activities", 400)

    try:
        new_activities = []
        for item in activities_payload:
            if not isinstance(item, dict):
                raise ValueError("Each activity must be an object")

            title = item.get("title")
            day = item.get("day")
            start_time = item.get("startTime")
            end_time = item.get("endTime")

            if not title or not isinstance(title, str):
                raise ValueError("title is required")
            if not day or not isinstance(day, str):
                raise ValueError("day is required")

            if not start_time or not isinstance(start_time, str) or not TIME_FORMAT_REGEX.match(start_time):
                raise ValueError(f"Invalid startTime format: {start_time}")
            if not end_time or not isinstance(end_time, str) or not TIME_FORMAT_REGEX.match(end_time):
                raise ValueError(f"Invalid endTime format: {end_time}")

            if start_time >= end_time:
                raise ValueError("startTime must be before endTime")

            duration = _calculate_duration_minutes(start_time, end_time)
            activity_id = str(uuid.uuid4())

            new_activities.append(
                PlannerActivity(
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
                    duration=duration,
                    archive_name=archive_name,
                )
            )

        if archive_name is None:
            PlannerActivity.query.filter_by(user_id=current_user.id, archive_name=None).delete(synchronize_session=False)
        else:
            PlannerActivity.query.filter_by(user_id=current_user.id, archive_name=archive_name).delete(synchronize_session=False)

        db.session.add_all(new_activities)
        db.session.commit()
        return success_response({"count": len(new_activities), "activities": [_serialize_activity(a) for a in new_activities]}, 201)
    except ValueError as exc:
        db.session.rollback()
        return error_response(str(exc), 400)
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        db.session.rollback()
        return error_response("Failed to sync planner activities", 500)

@planner_api.route("/activities", methods=["DELETE"])
@token_required
@retry_on_connection_error
def delete_planner_activities(current_user):
    archive_name = request.args.get("archive_name")
    if archive_name is None:
        PlannerActivity.query.filter_by(user_id=current_user.id, archive_name=None).delete(synchronize_session=False)
    else:
        PlannerActivity.query.filter_by(user_id=current_user.id, archive_name=archive_name).delete(synchronize_session=False)
    db.session.commit()
    return success_response({"message": "Planner activities deleted"})

# --- Course Routes ---

@planner_api.route("/courses", methods=["GET"])
@token_required
@retry_on_connection_error
def get_planner_courses(current_user):
    courses = PlannerCourse.query.filter_by(user_id=current_user.id).all()
    return success_response([_serialize_course(course) for course in courses])

@planner_api.route("/courses/sync", methods=["POST"])
@token_required
@retry_on_connection_error
def sync_planner_courses(current_user):
    payload = request.get_json(silent=True)
    courses_payload = payload
    if isinstance(payload, dict):
        courses_payload = payload.get("courses")

    if not isinstance(courses_payload, list):
        return error_response("Payload must contain a list of courses", 400)

    try:
        new_courses = []
        seen_ids = set()
        for item in courses_payload:
            title = item.get("title")
            if not title or not isinstance(title, str):
                raise ValueError("title is required")

            duration = _coerce_int("duration", item.get("duration", 60))
            course_id = item.get("id") if isinstance(item.get("id"), str) else str(uuid.uuid4())

            if course_id in seen_ids:
                raise ValueError("Duplicate course id")
            seen_ids.add(course_id)

            new_courses.append(
                PlannerCourse(
                    id=course_id,
                    user_id=current_user.id,
                    title=title.strip(),
                    teacher=item.get("teacher"),
                    room=item.get("room"),
                    duration=duration,
                    color=item.get("color"),
                    category=item.get("category"),
                )
            )

        PlannerCourse.query.filter_by(user_id=current_user.id).delete(synchronize_session=False)
        db.session.add_all(new_courses)
        db.session.commit()
        return success_response({"count": len(new_courses), "courses": [_serialize_course(c) for c in new_courses]}, 201)
    except Exception as e:
        db.session.rollback()
        logger.error(f"Course sync failed: {e}")
        return error_response("Failed to sync courses", 500)