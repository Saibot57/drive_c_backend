from flask import Blueprint, request
from services.db_config import db
from models.planner_models import PlannerActivity, PlannerCourse
from api.auth_routes import token_required
from api.routes import success_response, error_response
from api.schedule_routes import retry_on_connection_error
from sqlalchemy.exc import IntegrityError
import uuid
import logging

planner_api = Blueprint("planner_api", __name__)
logger = logging.getLogger(__name__)


def _coerce_int(name, value):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")


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


@planner_api.route("/activities", methods=["GET"])
@token_required
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
            duration = _coerce_int("duration", item.get("duration"))

            if not title or not isinstance(title, str):
                raise ValueError("title is required")
            if not day or not isinstance(day, str):
                raise ValueError("day is required")
            if not start_time or not isinstance(start_time, str):
                raise ValueError("startTime is required")
            if not end_time or not isinstance(end_time, str):
                raise ValueError("endTime is required")

            activity_id = item.get("id") if isinstance(item.get("id"), str) else str(uuid.uuid4())

            new_activities.append(
                PlannerActivity(
                    id=activity_id,
                    user_id=current_user.id,
                    title=title.strip(),
                    teacher=item.get("teacher"),
                    room=item.get("room"),
                    notes=item.get("notes"),
                    day=day.strip(),
                    start_time=start_time,
                    end_time=end_time,
                    color=item.get("color"),
                    duration=duration,
                    archive_name=archive_name,
                )
            )

        with db.session.begin():
            if archive_name is None:
                PlannerActivity.query.filter_by(
                    user_id=current_user.id, archive_name=None
                ).delete()
            else:
                PlannerActivity.query.filter_by(
                    user_id=current_user.id, archive_name=archive_name
                ).delete()
            db.session.add_all(new_activities)

        return success_response({"count": len(new_activities)}, 201)
    except ValueError as exc:
        db.session.rollback()
        return error_response(str(exc), 400)
    except Exception:
        db.session.rollback()
        return error_response("Failed to sync planner activities", 500)


@planner_api.route("/activities", methods=["DELETE"])
@token_required
def delete_planner_activities(current_user):
    archive_name = request.args.get("archive_name")
    if archive_name is None:
        PlannerActivity.query.filter_by(user_id=current_user.id, archive_name=None).delete()
    else:
        PlannerActivity.query.filter_by(
            user_id=current_user.id, archive_name=archive_name
        ).delete()
    db.session.commit()
    return success_response({"message": "Planner activities deleted"})


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

    logger.info("Syncing planner courses for user %s", current_user.id)
    try:
        new_courses = []
        seen_ids = set()
        for item in courses_payload:
            if not isinstance(item, dict):
                raise ValueError("Each course must be an object")

            title = item.get("title")
            if not title or not isinstance(title, str):
                raise ValueError("title is required")

            duration = _coerce_int("duration", item.get("duration", 60))
            if duration <= 0:
                raise ValueError("duration must be a positive integer")

            incoming_id = item.get("id")
            if isinstance(incoming_id, str) and incoming_id.strip():
                incoming_id = incoming_id.strip()
                existing = PlannerCourse.query.filter_by(id=incoming_id).first()
                if existing and existing.user_id != current_user.id:
                    raise ValueError("Invalid course id")
                course_id = incoming_id
            else:
                course_id = str(uuid.uuid4())

            if course_id in seen_ids:
                raise ValueError("Duplicate course id in request")
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

        PlannerCourse.query.filter_by(user_id=current_user.id).delete(
            synchronize_session=False
        )
        db.session.add_all(new_courses)
        db.session.commit()
        logger.info(
            "Synced %s planner courses for user %s", len(new_courses), current_user.id
        )
        return success_response(
            {
                "count": len(new_courses),
                "courses": [_serialize_course(course) for course in new_courses],
            },
            201,
        )
    except ValueError as exc:
        db.session.rollback()
        logger.error("Validation error syncing courses for user %s: %s", current_user.id, exc)
        return error_response(str(exc), 400)
    except IntegrityError:
        db.session.rollback()
        logger.error("Integrity error syncing courses for user %s", current_user.id)
        return error_response("Database integrity error. Please try again.", 400)
    except Exception:
        db.session.rollback()
        logger.error("Failed to sync planner courses for user %s", current_user.id)
        return error_response("Failed to sync planner courses", 500)
