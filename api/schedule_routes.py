from flask import Blueprint, jsonify, request
from services.db_config import db
from models.schedule_models import Activity, FamilyMember, Settings
from api.auth_routes import token_required

from sqlalchemy.exc import OperationalError
from time import sleep
from datetime import datetime
from functools import wraps
import uuid
import logging
import json

logger = logging.getLogger(__name__)
schedule_bp = Blueprint("schedule_bp", __name__)

# --- Standardiserade Svar ---
def success_response(data=None, status_code=200):
    return jsonify({"success": True, "data": data if data is not None else {}, "error": None}), status_code


def error_response(message, status_code=400, data=None):
    return jsonify({"success": False, "data": data, "error": message}), status_code


# ---------------- Retry-hjälpare ----------------
def retry_on_connection_error(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except OperationalError as e:
                logger.warning("DB OperationalError (försök %s/3): %s", attempt + 1, e)
                db.session.rollback()
                if attempt < 2:
                    sleep(0.5)
                    continue
                raise

    return wrapper


# ---------------- Hjälpfunktioner ----------------
SV_WEEKDAYS = {
    1: "Måndag",
    2: "Tisdag",
    3: "Onsdag",
    4: "Torsdag",
    5: "Fredag",
    6: "Lördag",
    7: "Söndag",
}
SV_TO_NUM = {v.lower(): k for k, v in SV_WEEKDAYS.items()}


def _parse_time_hhmm(value: str):
    if not isinstance(value, str) or len(value) not in (4, 5):
        raise ValueError("Time must be 'HH:MM'")
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("Time must be 'HH:MM'")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Time must be 'HH:MM' in 24h range")
    return datetime(2000, 1, 1, hour, minute)


def _time_to_str(dt: datetime) -> str:
    return f"{dt.hour:02d}:{dt.minute:02d}"


def _require_int(name: str, val):
    if val is None:
        raise ValueError(f"{name} is required and must be an integer")
    try:
        return int(val)
    except (ValueError, TypeError):
        raise ValueError(f"{name} must be an integer")


def _norm_day(d) -> str:
    if isinstance(d, int):
        if 1 <= d <= 7:
            return SV_WEEKDAYS[d]
        raise ValueError("day int must be 1..7 (ISO, Måndag=1)")
    if isinstance(d, str):
        s = d.strip().lower()
        if s.isdigit():
            i = int(s)
            if 1 <= i <= 7:
                return SV_WEEKDAYS[i]
        if s in SV_TO_NUM:
            return SV_WEEKDAYS[SV_TO_NUM[s]]
    raise ValueError("day must be a Swedish weekday name or 1..7")


def _validate_activity_payload(raw: dict):
    if not isinstance(raw, dict):
        raise ValueError("Each activity must be an object")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name is required")

    start_t = _parse_time_hhmm(raw.get("startTime"))
    end_t = _parse_time_hhmm(raw.get("endTime"))
    if start_t >= end_t:
        raise ValueError("startTime must be earlier than endTime")

    participants = raw.get("participants", [])
    if not isinstance(participants, list):
        raise ValueError("participants must be an array")

    series_id = raw.get("seriesId") or str(uuid.uuid4())

    base_payload = {
        "name": name.strip(),
        "icon": raw.get("icon"),
        "startTime": _time_to_str(start_t),
        "endTime": _time_to_str(end_t),
        "participants": [str(p) for p in participants],
        "location": raw.get("location"),
        "notes": raw.get("notes"),
        "color": raw.get("color"),
        "seriesId": series_id,
    }

    days_raw = raw.get("days", []) if "days" in raw else [raw.get("day")]
    if not days_raw or days_raw[0] is None:
        raise ValueError("Provide either 'date'/'dates' or 'days'/'day'")
    base_payload["days"] = [_norm_day(d) for d in days_raw]

    base_payload["week"] = _require_int("week", raw.get("week"))
    base_payload["year"] = _require_int("year", raw.get("year"))

    return base_payload


def _expand_instances(v: dict) -> list[dict]:
    base = {
        k: v[k]
        for k in [
            "name",
            "icon",
            "startTime",
            "endTime",
            "participants",
            "location",
            "notes",
            "color",
            "seriesId",
        ]
        if k in v
    }
    out = []
    for d in v["days"]:
        out.append({**base, "day": d, "week": v["week"], "year": v["year"]})
    return out


# ---------------- Routes: Settings ----------------
@schedule_bp.route("/settings", methods=["GET"])
@token_required
@retry_on_connection_error
def get_schedule_settings(current_user):
    s = Settings.query.filter_by(user_id=current_user.id).first()
    if not s:
        s = Settings(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            show_weekends=False,
            day_start=7,
            day_end=18,
        )
        db.session.add(s)
        db.session.commit()
    return success_response(
        {
            "showWeekends": bool(s.show_weekends),
            "dayStart": int(s.day_start),
            "dayEnd": int(s.day_end),
        }
    )


@schedule_bp.route("/settings", methods=["PUT"])
@token_required
@retry_on_connection_error
def update_schedule_settings(current_user):
    data = request.get_json(silent=True) or {}
    s = Settings.query.filter_by(user_id=current_user.id).first()
    if not s:
        s = Settings(id=str(uuid.uuid4()), user_id=current_user.id)
        db.session.add(s)

    if "showWeekends" in data:
        s.show_weekends = bool(data["showWeekends"])
    if "dayStart" in data:
        s.day_start = int(data["dayStart"])
    if "dayEnd" in data:
        s.day_end = int(data["dayEnd"])

    db.session.commit()
    return success_response(
        {
            "showWeekends": bool(s.show_weekends),
            "dayStart": int(s.day_start),
            "dayEnd": int(s.day_end),
        }
    )


# ---------------- Routes: Family members ----------------
@schedule_bp.route("/family-members", methods=["GET"])
@token_required
@retry_on_connection_error
def get_family_members(current_user):
    ms = FamilyMember.query.filter_by(user_id=current_user.id).all()
    if not ms:
        default_members = [
            {"name": "Rut", "color": "#FF6B6B", "icon": "👧"},
            {"name": "Pim", "color": "#4E9FFF", "icon": "👦"},
            {"name": "Siv", "color": "#6BCF7F", "icon": "👧"},
            {"name": "Mamma", "color": "#A020F0", "icon": "👩"},
            {"name": "Pappa", "color": "#FF9F45", "icon": "👨"},
        ]
        for member_data in default_members:
            member = FamilyMember(
                id=str(uuid.uuid4()), user_id=current_user.id, **member_data
            )
            db.session.add(member)
            ms.append(member)
        db.session.commit()

    return success_response(
        [{"id": m.id, "name": m.name, "color": m.color, "icon": m.icon} for m in ms]
    )


# ---------------- Routes: Activities (CRUD) ----------------
@schedule_bp.route("/activities", methods=["GET"])
@token_required
@retry_on_connection_error
def get_activities(current_user):
    try:
        year = _require_int("year", request.args.get("year"))
        week = _require_int("week", request.args.get("week"))
    except ValueError as e:
        return error_response(str(e), 400)

    activities = Activity.query.filter_by(
        user_id=current_user.id, year=year, week=week
    ).all()

    result = [
        {
            "id": a.id,
            "seriesId": a.series_id,
            "name": a.name,
            "icon": a.icon,
            "day": a.day,
            "week": a.week,
            "year": a.year,
            "startTime": a.start_time,
            "endTime": a.end_time,
            "location": a.location,
            "notes": a.notes,
            "color": a.color,
            "participants": [p.id for p in a.participants],
        }
        for a in activities
    ]
    return success_response(result)


@schedule_bp.route("/activities", methods=["POST"])
@token_required
@retry_on_connection_error
def create_activity(current_user):
    payload = request.get_json(silent=True) or {}
    if not payload:
        return error_response("Invalid request: No JSON received", 400)

    try:
        v = _validate_activity_payload(payload)
        instances = _expand_instances(v)
    except ValueError as ve:
        return error_response(str(ve), 400)

    members = FamilyMember.query.filter_by(user_id=current_user.id).all()
    by_id = {m.id: m for m in members}  # kept for parity, even if not used below

    created_activities = []
    for inst in instances:
        # Map from camelCase (JS) to snake_case (Python/DB)
        inst_for_db = {
            "series_id": inst["seriesId"],
            "name": inst["name"],
            "icon": inst.get("icon"),
            "day": inst["day"],
            "week": inst["week"],
            "year": inst["year"],
            "start_time": inst["startTime"],
            "end_time": inst["endTime"],
            "location": inst.get("location"),
            "notes": inst.get("notes"),
            "color": inst.get("color"),
        }
        a = Activity(id=str(uuid.uuid4()), user_id=current_user.id, **inst_for_db)

        # Add participants
        participant_ids = inst.get("participants", [])
        resolved_participants = FamilyMember.query.filter(
            FamilyMember.id.in_(participant_ids)
        ).all()
        a.participants.extend(resolved_participants)

        db.session.add(a)
        created_activities.append(a)

    db.session.commit()
    return success_response(
        {"id": created_activities[0].id, "created": len(created_activities)}, 201
    )


@schedule_bp.route("/activities/<activity_id>", methods=["PUT"])
@token_required
@retry_on_connection_error
def update_activity(current_user, activity_id):
    a = Activity.query.filter_by(id=activity_id, user_id=current_user.id).first()
    if not a:
        return error_response("Activity not found", 404)

    data = request.get_json(silent=True) or {}
    try:
        if "name" in data:
            a.name = str(data["name"]).strip() or a.name
        if "icon" in data:
            a.icon = data["icon"]
        if "day" in data:
            a.day = _norm_day(data["day"])
        if "week" in data:
            a.week = _require_int("week", data["week"])
        if "year" in data:
            a.year = _require_int("year", data["year"])
        if "startTime" in data:
            a.start_time = _time_to_str(_parse_time_hhmm(data["startTime"]))
        if "endTime" in data:
            a.end_time = _time_to_str(_parse_time_hhmm(data["endTime"]))
        if "location" in data:
            a.location = data["location"]
        if "notes" in data:
            a.notes = data["notes"]
        if "color" in data:
            a.color = data["color"]
        if "participants" in data:
            members = FamilyMember.query.filter_by(user_id=current_user.id).all()
            by_id = {m.id: m for m in members}
            a.participants.clear()
            for pid in data["participants"] or []:
                if pid in by_id:
                    a.participants.append(by_id[pid])
    except (ValueError, TypeError) as e:
        return error_response(str(e))

    db.session.commit()
    return success_response()


@schedule_bp.route("/activities/<activity_id>", methods=["DELETE"])
@token_required
@retry_on_connection_error
def delete_activity(current_user, activity_id):
    a = Activity.query.filter_by(id=activity_id, user_id=current_user.id).first()
    if not a:
        return error_response("Activity not found", 404)
    db.session.delete(a)
    db.session.commit()
    return success_response()


@schedule_bp.route("/activities/series/<series_id>", methods=["DELETE"])
@token_required
@retry_on_connection_error
def delete_activity_series(current_user, series_id):
    acts = Activity.query.filter_by(series_id=series_id, user_id=current_user.id).all()
    if not acts:
        return error_response("No activities for series", 404)
    num_deleted = len(acts)
    for a in acts:
        db.session.delete(a)
    db.session.commit()
    return success_response({"deleted": num_deleted})


@schedule_bp.route("/add-activities", methods=["POST"])
@token_required
@retry_on_connection_error
def add_activities_from_json(current_user):
    try:
        payload = request.get_json(silent=True)
        if payload is None:
            return error_response("Invalid JSON", 400)

        activities = payload if isinstance(payload, list) else payload.get("activities")
        if not isinstance(activities, list) or not activities:
            return error_response("Provide a non-empty array of activities", 400)

        all_instances = []
        for raw in activities:
            v = _validate_activity_payload(raw)
            all_instances.extend(_expand_instances(v))

        members = FamilyMember.query.filter_by(user_id=current_user.id).all()
        by_id = {m.id: m for m in members}  # kept for parity

        for inst in all_instances:
            # Map from camelCase (JS) to snake_case (Python/DB)
            inst_for_db = {
                "series_id": inst["seriesId"],
                "name": inst["name"],
                "icon": inst.get("icon"),
                "day": inst["day"],
                "week": inst["week"],
                "year": inst["year"],
                "start_time": inst["startTime"],
                "end_time": inst["endTime"],
                "location": inst.get("location"),
                "notes": inst.get("notes"),
                "color": inst.get("color"),
            }
            a = Activity(id=str(uuid.uuid4()), user_id=current_user.id, **inst_for_db)

            participant_ids = inst.get("participants", [])
            resolved_participants = FamilyMember.query.filter(
                FamilyMember.id.in_(participant_ids)
            ).all()
            a.participants.extend(resolved_participants)

            db.session.add(a)

        db.session.commit()
        return success_response({"message": f"Activities added: {len(all_instances)}"}, 201)

    except ValueError as ve:
        return error_response(str(ve), 400)
    except Exception as e:
        logger.error("add_activities_from_json error: %s", str(e))
        db.session.rollback()
        return error_response("Failed to add activities", 500)
