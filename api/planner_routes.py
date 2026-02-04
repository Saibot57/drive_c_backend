from flask import Blueprint, request
from services.db_config import db
from models.planner_models import PlannerActivity
from api.auth_routes import token_required
from api.routes import success_response, error_response
import uuid

planner_bp = Blueprint("planner_bp", __name__)


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
        "day": activity.day,
        "startTime": activity.start_time,
        "endTime": activity.end_time,
        "color": activity.color,
        "duration": activity.duration,
    }


@planner_bp.route("/activities", methods=["GET"])
@token_required
def get_planner_activities(current_user):
    activities = PlannerActivity.query.filter_by(user_id=current_user.id).all()
    return success_response([_serialize_activity(activity) for activity in activities])


@planner_bp.route("/activities", methods=["POST"])
@token_required
def save_planner_activities(current_user):
    payload = request.get_json(silent=True)
    if payload is None:
        return error_response("Invalid JSON payload", 400)

    activities_payload = payload.get("activities") if isinstance(payload, dict) else payload
    if not isinstance(activities_payload, list):
        return error_response("Payload must be a list of activities", 400)

    try:
        PlannerActivity.query.filter_by(user_id=current_user.id).delete()

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
                    day=day.strip(),
                    start_time=start_time,
                    end_time=end_time,
                    color=item.get("color"),
                    duration=duration,
                )
            )

        db.session.add_all(new_activities)
        db.session.commit()
        return success_response({"count": len(new_activities)}, 201)
    except ValueError as exc:
        db.session.rollback()
        return error_response(str(exc), 400)
    except Exception:
        db.session.rollback()
        return error_response("Failed to save planner activities", 500)


@planner_bp.route("/activities", methods=["DELETE"])
@token_required
def delete_planner_activities(current_user):
    PlannerActivity.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return success_response({"message": "Planner activities deleted"})
