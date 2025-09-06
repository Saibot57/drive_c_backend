from flask import Blueprint, jsonify, request
from services.db_config import db
from models.schedule_models import Activity, FamilyMember, Settings
from api.auth_routes import token_required

from sqlalchemy.exc import OperationalError
from sqlalchemy import and_, or_
from time import sleep
from datetime import datetime
import uuid
import logging

logger = logging.getLogger(__name__)
schedule_bp = Blueprint('schedule_bp', __name__)

# ---------------- Retry-hjälpare ----------------
def retry_on_connection_error(func):
    """Retry DB-operationer som kan kasta OperationalError (t.ex. tappad MySQL-anslutning)."""
    def wrapper(*args, **kwargs):
        for attempt in range(3):
            try:
                return func(*args, **kwargs)
            except OperationalError as e:
                logger.warning(f"DB OperationalError (försök {attempt+1}/3): {e}")
                db.session.rollback()
                if attempt < 2:
                    sleep(0.5)
                    continue
                raise
    wrapper.__name__ = func.__name__
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
    hour = int(parts[0]); minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Time must be 'HH:MM' in 24h range")
    return datetime(2000, 1, 1, hour, minute)

def _time_to_str(dt: datetime) -> str:
    return f"{dt.hour:02d}:{dt.minute:02d}"

def _require_int(name: str, val):
    if not isinstance(val, int):
        raise ValueError(f"{name} must be an integer")
    return val

def _norm_day(d) -> str:
    """Accepterar t.ex. 'Måndag', 'måndag', 1..7. Returnerar svensk veckodag som str."""
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

def _iso_to_sv_weekday(dt: datetime) -> str:
    return SV_WEEKDAYS[dt.isocalendar()[2]]

def _dates_to_dwy(dates: list[str]):
    triples = []
    for s in dates:
        try:
            dt = datetime.strptime(s.strip(), "%Y-%m-%d")
        except Exception:
            raise ValueError(f"Invalid ISO date: {s} (expected YYYY-MM-DD)")
        iso = dt.isocalendar()
        triples.append({
            "day": _iso_to_sv_weekday(dt),
            "week": iso[1],
            "year": iso[0],
        })
    return triples

def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)

def _ranges_overlap(s1: str, e1: str, s2: str, e2: str) -> bool:
    a1, b1, a2, b2 = _minutes(s1), _minutes(e1), _minutes(s2), _minutes(e2)
    return max(a1, a2) < min(b1, b2)

def _validate_activity_payload(raw: dict):
    """
    Validerar och normaliserar en (1) aktivitet.
    - Hanterar participants som id eller namn (löses senare).
    - Accepterar antingen 'date'/'dates' eller legacy 'day(s)' + week + year.
    """
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
    participants = [str(p) for p in participants]

    series_id = raw.get("seriesId") or str(uuid.uuid4())
    icon = raw.get("icon")
    location = raw.get("location")
    notes = raw.get("notes")
    color = raw.get("color")

    # Ny väg: date/dates
    if "date" in raw or "dates" in raw:
        if "date" in raw:
            if not isinstance(raw["date"], str) or not raw["date"].strip():
                raise ValueError("date must be a non-empty ISO date string (YYYY-MM-DD)")
            dates = [raw["date"].strip()]
        else:
            dates = raw["dates"]
            if not isinstance(dates, list) or not dates:
                raise ValueError("dates must be a non-empty array of ISO date strings (YYYY-MM-DD)")
        dateTriples = _dates_to_dwy(dates)

        return {
            "name": name.strip(),
            "icon": icon,
            "startTime": _time_to_str(start_t),
            "endTime": _time_to_str(end_t),
            "participants": participants,
            "location": location,
            "notes": notes,
            "color": color,
            "seriesId": series_id,
            "dateTriples": dateTriples,
        }

    # Legacy: day(s), week, year
    if "days" in raw:
        if not isinstance(raw["days"], list) or not raw["days"]:
            raise ValueError("days must be a non-empty array")
        days = [_norm_day(d) for d in raw["days"]]
    elif "day" in raw:
        days = [_norm_day(raw["day"])]
    else:
        raise ValueError("Provide either 'date'/'dates' or 'days'/'day'")

    week = _require_int("week", raw.get("week"))
    year = _require_int("year", raw.get("year"))

    return {
        "name": name.strip(),
        "icon": icon,
        "days": days,
        "week": week,
        "year": year,
        "startTime": _time_to_str(start_t),
        "endTime": _time_to_str(end_t),
        "participants": participants,
        "location": location,
        "notes": notes,
        "color": color,
        "seriesId": series_id,
    }

def _expand_instances(v: dict) -> list[dict]:
    """
    Bygger instanser (en per dag/datum) av en normaliserad aktivitet.
    Returnerar listor av dicts som är klara att skapa som Activity.
    """
    base = {
        "name": v["name"],
        "icon": v.get("icon"),
        "startTime": v["startTime"],
        "endTime": v["endTime"],
        "participants": v.get("participants", []),
        "location": v.get("location"),
        "notes": v.get("notes"),
        "color": v.get("color"),
        "seriesId": v["seriesId"],
    }
    out = []

    if "dateTriples" in v:
        for t in v["dateTriples"]:
            out.append({**base, "day": t["day"], "week": t["week"], "year": t["year"]})
        return out

    # Legacy
    for d in v["days"]:
        out.append({**base, "day": d, "week": v["week"], "year": v["year"]})
    return out

def _check_for_conflicts(user_id: str, instances: list[dict]):
    """
    Enkel konfliktdetektion: om någon deltagare redan är bokad samma (year, week, day)
    och tiden överlappar.
    Returnerar lista med konflikter, annars [].
    """
    if not instances:
        return []

    # Gruppers efter (y, w, d) för att minimera queries
    keys = set((i["year"], i["week"], i["day"]) for i in instances)
    conflicts = []

    for (year, week, day) in keys:
        # Hämta befintliga aktiviteter för veckan/dagen
        existing = Activity.query.filter_by(user_id=user_id, year=year, week=week, day=day).all()
        # Indexera befintliga deltagare per aktivitet-id
        existing_with_parts = []
        for a in existing:
            try:
                part_ids = [m.id for m in a.participants]
            except Exception:
                part_ids = []
            existing_with_parts.append({
                "id": a.id,
                "name": a.name,
                "start": a.start_time,
                "end": a.end_time,
                "participants": set(part_ids),
            })

        # Nya instanser för samma (y,w,d)
        new_for_key = [i for i in instances if i["year"] == year and i["week"] == week and i["day"] == day]
        for inst in new_for_key:
            inst_parts = set(inst.get("participants", []))
            for ex in existing_with_parts:
                if not inst_parts or not ex["participants"]:
                    continue
                if inst_parts & ex["participants"]:
                    if _ranges_overlap(inst["startTime"], inst["endTime"], ex["start"], ex["end"]):
                        conflicts.append({
                            "day": day, "week": week, "year": year,
                            "new": {
                                "name": inst["name"],
                                "startTime": inst["startTime"],
                                "endTime": inst["endTime"],
                                "participants": list(inst_parts),
                            },
                            "existing": {
                                "id": ex["id"],
                                "name": ex["name"],
                                "startTime": ex["start"],
                                "endTime": ex["end"],
                                "participants": list(ex["participants"]),
                            }
                        })
    return conflicts

# ---------------- Routes: Settings ----------------
@schedule_bp.route('/settings', methods=['GET'])
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
            day_end=18
        )
        db.session.add(s)
        db.session.commit()
    return jsonify({
        "status": "success",
        "data": {
            "showWeekends": bool(s.show_weekends),
            "dayStart": int(s.day_start),
            "dayEnd": int(s.day_end),
        }
    })

@schedule_bp.route('/settings', methods=['PUT'])
@token_required
@retry_on_connection_error
def update_schedule_settings(current_user):
    data = request.get_json(silent=True) or {}
    s = Settings.query.filter_by(user_id=current_user.id).first()
    if not s:
        s = Settings(id=str(uuid.uuid4()), user_id=current_user.id)
        db.session.add(s)

    # Tillåt endast de fält som finns i modellen
    if "showWeekends" in data:
        s.show_weekends = bool(data["showWeekends"])
    if "dayStart" in data:
        s.day_start = int(data["dayStart"])
    if "dayEnd" in data:
        s.day_end = int(data["dayEnd"])

    db.session.commit()
    return jsonify({
        "status": "success",
        "data": {
            "showWeekends": bool(s.show_weekends),
            "dayStart": int(s.day_start),
            "dayEnd": int(s.day_end),
        }
    })

# ---------------- Routes: Family members ----------------
@schedule_bp.route('/family-members', methods=['GET'])
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
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                name=member_data["name"],
                color=member_data["color"],
                icon=member_data["icon"]
            )
            db.session.add(member)
            ms.append(member)

        db.session.commit()

    return jsonify({
        "status": "success",
        "data": [{
            "id": m.id,
            "name": m.name,
            "color": m.color,
            "icon": m.icon
        } for m in ms]
    })

# ---------------- Routes: Activities (CRUD) ----------------
@schedule_bp.route('/activities', methods=['GET'])
@token_required
@retry_on_connection_error
def list_activities(current_user):
    # Valfri filtrering
    week = request.args.get("week", type=int)
    year = request.args.get("year", type=int)

    q = Activity.query.filter_by(user_id=current_user.id)
    if week is not None:
        q = q.filter_by(week=week)
    if year is not None:
        q = q.filter_by(year=year)
    acts = q.all()

    def dto(a: Activity):
        return {
            "id": a.id,
            "seriesId": a.series_id,
            "userId": a.user_id,
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
            "participants": [m.id for m in a.participants],  # id:n utåt
        }

    return jsonify({"status": "success", "data": [dto(a) for a in acts]})

@schedule_bp.route('/activities', methods=['POST'])
@token_required
@retry_on_connection_error
def create_activity(current_user):
    payload = request.get_json(silent=True) or {}
    try:
        v = _validate_activity_payload(payload)
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 400

    instances = _expand_instances(v)

    # Lös deltagare (id eller namn) mot DB
    all_refs = set()
    for inst in instances:
        all_refs.update(inst.get("participants", []))

    members = FamilyMember.query.filter_by(user_id=current_user.id).all()
    by_id = {m.id: m for m in members}
    by_name = {m.name.lower(): m for m in members}

    resolved = {}
    unknown = []
    for ref in all_refs:
        rlow = str(ref).lower()
        if ref in by_id:
            resolved[ref] = by_id[ref].id
        elif rlow in by_name:
            resolved[ref] = by_name[rlow].id
        else:
            unknown.append(ref)

    if unknown:
        return jsonify({"status": "error", "message": "Unknown participants", "unknown": unknown}), 400

    for inst in instances:
        inst["participants"] = [resolved[p] for p in inst.get("participants", []) if p in resolved]

    # Konflikter?
    conflicts = _check_for_conflicts(current_user.id, instances)
    if conflicts:
        return jsonify({"status": "error", "message": "Conflicts detected", "conflicts": conflicts}), 409

    # Skapa alla
    created_activities = []
    for inst in instances:
        a = Activity(
            id=str(uuid.uuid4()),
            series_id=inst["seriesId"],
            user_id=current_user.id,
            name=inst["name"],
            icon=inst.get("icon"),
            day=inst["day"],
            week=inst["week"],
            year=inst["year"],
            start_time=inst["startTime"],
            end_time=inst["endTime"],
            location=inst.get("location"),
            notes=inst.get("notes"),
            color=inst.get("color"),
        )
        for pid in inst.get("participants", []):
            if pid in by_id:
                a.participants.append(by_id[pid])
        db.session.add(a)
        created_activities.append(a)

    db.session.commit()
    return jsonify({
        "status": "success",
        "data": {
            "id": created_activities[0].id if len(created_activities) == 1 else None,
            "created": len(created_activities)
        }
    }), 201

@schedule_bp.route('/activities/<activity_id>', methods=['PUT'])
@token_required
@retry_on_connection_error
def update_activity(current_user, activity_id):
    a = Activity.query.filter_by(id=activity_id, user_id=current_user.id).first()
    if not a:
        return jsonify({"status": "error", "message": "Activity not found"}), 404

    data = request.get_json(silent=True) or {}

    # Tillåt att uppdatera tid, dag, namn, mm.
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

    # Uppdatera participants (lista av id eller namn)
    if "participants" in data:
        members = FamilyMember.query.filter_by(user_id=current_user.id).all()
        by_id = {m.id: m for m in members}
        by_name = {m.name.lower(): m for m in members}
        new_ids = []
        for ref in data["participants"] or []:
            rlow = str(ref).lower()
            if ref in by_id:
                new_ids.append(by_id[ref].id)
            elif rlow in by_name:
                new_ids.append(by_name[rlow].id)
            else:
                return jsonify({"status": "error", "message": f"Unknown participant: {ref}"}), 400
        a.participants.clear()
        for pid in new_ids:
            a.participants.append(by_id[pid])

    db.session.commit()
    return jsonify({"status": "success"})

@schedule_bp.route('/activities/<activity_id>', methods=['DELETE'])
@token_required
@retry_on_connection_error
def delete_activity(current_user, activity_id):
    a = Activity.query.filter_by(id=activity_id, user_id=current_user.id).first()
    if not a:
        return jsonify({"status": "error", "message": "Activity not found"}), 404
    db.session.delete(a)
    db.session.commit()
    return jsonify({"status": "success"})

@schedule_bp.route('/activities/series/<series_id>', methods=['DELETE'])
@token_required
@retry_on_connection_error
def delete_activity_series(current_user, series_id):
    acts = Activity.query.filter_by(series_id=series_id, user_id=current_user.id).all()
    if not acts:
        return jsonify({"status": "error", "message": "No activities for series"}), 404
    for a in acts:
        db.session.delete(a)
    db.session.commit()
    return jsonify({"status": "success", "deleted": len(acts)})

# ---------------- Import: add-activities (array ELLER {activities: [...]}) ----------------
@schedule_bp.route('/add-activities', methods=['POST'])
@token_required
@retry_on_connection_error
def add_activities_from_json(current_user):
    try:
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400

        # Acceptera både rå array och { activities: [...] }
        activities = payload if isinstance(payload, list) else payload.get("activities")
        if not isinstance(activities, list) or not activities:
            return jsonify({"status": "error", "message": "Provide a non-empty array of activities (or { activities: [...] })"}), 400

        validated = []
        all_instances = []
        for raw in activities:
            try:
                v = _validate_activity_payload(raw)
            except ValueError as ve:
                return jsonify({"status": "error", "message": str(ve)}), 400
            validated.append(v)
            all_instances.extend(_expand_instances(v))

        # Samla alla deltagarreferenser
        all_refs = set()
        for v in validated:
            all_refs.update(v.get("participants", []))

        members = FamilyMember.query.filter_by(user_id=current_user.id).all()
        by_id = {m.id: m for m in members}
        by_name = {m.name.lower(): m for m in members}

        resolved = {}
        unknown = []
        for ref in all_refs:
            rlow = str(ref).lower()
            if ref in by_id:
                resolved[ref] = by_id[ref].id
            elif rlow in by_name:
                resolved[ref] = by_name[rlow].id
            else:
                unknown.append(ref)

        if unknown:
            return jsonify({"status": "error", "message": "Unknown participants", "unknown": unknown}), 400

        for inst in all_instances:
            inst["participants"] = [resolved[p] for p in inst.get("participants", []) if p in resolved]

        conflicts = _check_for_conflicts(current_user.id, all_instances)
        if conflicts:
            return jsonify({"status": "error", "message": "Conflicts detected", "conflicts": conflicts}), 409

        # Skapa alla
        for inst in all_instances:
            a = Activity(
                id=str(uuid.uuid4()),
                series_id=inst["seriesId"],
                user_id=current_user.id,
                name=inst["name"],
                icon=inst.get("icon"),
                day=inst["day"],
                week=inst["week"],
                year=inst["year"],
                start_time=inst["startTime"],
                end_time=inst["endTime"],
                location=inst.get("location"),
                notes=inst.get("notes"),
                color=inst.get("color"),
            )
            for pid in inst.get("participants", []):
                if pid in by_id:
                    a.participants.append(by_id[pid])
            db.session.add(a)

        db.session.commit()
        return jsonify({"status": "success", "message": f"Activities added: {len(all_instances)}"}), 201

    except Exception as e:
        logger.error(f"add_activities_from_json error: {str(e)}")
        db.session.rollback()
        return jsonify({"status": "error", "message": "Failed to add activities"}), 500