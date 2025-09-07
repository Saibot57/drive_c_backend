# api/calendar_routes.py
from flask import Blueprint, jsonify, request
from services.db_config import db
from models.calendar import CalendarEvent, DayNote
from api.auth_routes import token_required
from datetime import datetime, timezone, date
import logging

logger = logging.getLogger(__name__)
calendar_api = Blueprint('calendar_api', __name__)


def success_response(data=None, status_code=200):
    return jsonify({"success": True, "data": data if data is not None else {}, "error": None}), status_code


def error_response(message, status_code=400, data=None):
    return jsonify({"success": False, "data": data, "error": message}), status_code

# --- Hjälpare för tidskonvertering (lagras som "naive UTC" i DB) ---
def ms_to_naive_utc(ms):
    """ms (epoch) -> naive UTC datetime"""
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).replace(tzinfo=None)

def naive_utc_to_ms(dt):
    """naive UTC datetime -> ms (epoch)"""
    # Behandla dt som UTC
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)

# --------------------- Event endpoints ---------------------

@calendar_api.route('/events', methods=['GET'])
@token_required
def get_events(current_user):
    """Get events with optional date range filtering (query: start, end in ms)"""
    try:
        start_ts = request.args.get('start')
        end_ts = request.args.get('end')

        query = CalendarEvent.query.filter_by(user_id=current_user.id)

        start_dt = end_dt = None
        if start_ts:
            try:
                start_dt = ms_to_naive_utc(start_ts)
                query = query.filter(CalendarEvent.start_time >= start_dt)
            except Exception:
                return error_response("Invalid start timestamp format", 400)

        if end_ts:
            try:
                end_dt = ms_to_naive_utc(end_ts)
                query = query.filter(CalendarEvent.end_time <= end_dt)
            except Exception:
                return error_response("Invalid end timestamp format", 400)

        if start_dt and end_dt and end_dt < start_dt:
            return error_response("end must be >= start", 400)

        events = query.order_by(CalendarEvent.start_time.asc()).all()

        events_data = [{
            'id': e.id,
            'title': e.title,
            'start': naive_utc_to_ms(e.start_time),
            'end': naive_utc_to_ms(e.end_time),
            'notes': e.notes,
            'color': e.color
        } for e in events]

        return success_response(events_data)

    except Exception as e:
        logger.error(f"Error in get_events: {str(e)}")
        return error_response("Failed to fetch events", 500)


@calendar_api.route('/events', methods=['POST'])
@token_required
def create_event(current_user):
    """Create a new event (expects title, start, end in ms)"""
    try:
        data = request.get_json(silent=True) or {}
        required = ['title', 'start', 'end']
        missing = [f for f in required if f not in data]
        if missing:
            return error_response(f"Missing required field(s): {', '.join(missing)}", 400)

        try:
            start_time = ms_to_naive_utc(data['start'])
            end_time = ms_to_naive_utc(data['end'])
        except Exception:
            return error_response("Invalid timestamp format. Use milliseconds since epoch.", 400)

        if end_time < start_time:
            return error_response("end must be >= start", 400)

        new_event = CalendarEvent(
            id=CalendarEvent.generate_id(),
            title=data['title'],
            start_time=start_time,
            end_time=end_time,
            notes=data.get('notes'),
            color=data.get('color'),
            user_id=current_user.id
        )
        db.session.add(new_event)
        db.session.commit()

        return success_response({
            'id': new_event.id,
            'title': new_event.title,
            'start': naive_utc_to_ms(new_event.start_time),
            'end': naive_utc_to_ms(new_event.end_time),
            'notes': new_event.notes,
            'color': new_event.color
        }, 201)

    except Exception as e:
        logger.error(f"Error in create_event: {str(e)}")
        db.session.rollback()
        return error_response("Failed to create event", 500)


@calendar_api.route('/events/<event_id>', methods=['PUT'])
@token_required
def update_event(current_user, event_id):
    """Update an existing event (accepts title, start, end in ms, notes, color)"""
    try:
        data = request.get_json(silent=True) or {}
        event = CalendarEvent.query.filter_by(id=event_id, user_id=current_user.id).first()
        if not event:
            return error_response("Event not found", 404)

        # Temporära värden för validering av start/end
        new_start = event.start_time
        new_end = event.end_time

        if 'title' in data:
            event.title = data['title']

        if 'start' in data:
            try:
                new_start = ms_to_naive_utc(data['start'])
            except Exception:
                return error_response("Invalid start timestamp format", 400)

        if 'end' in data:
            try:
                new_end = ms_to_naive_utc(data['end'])
            except Exception:
                return error_response("Invalid end timestamp format", 400)

        if new_end < new_start:
            return error_response("end must be >= start", 400)

        event.start_time = new_start
        event.end_time = new_end

        if 'notes' in data:
            event.notes = data['notes']
        if 'color' in data:
            event.color = data['color']

        db.session.commit()

        return success_response({
            'id': event.id,
            'title': event.title,
            'start': naive_utc_to_ms(event.start_time),
            'end': naive_utc_to_ms(event.end_time),
            'notes': event.notes,
            'color': event.color
        })

    except Exception as e:
        logger.error(f"Error in update_event: {str(e)}")
        db.session.rollback()
        return error_response("Failed to update event", 500)


@calendar_api.route('/events/<event_id>', methods=['DELETE'])
@token_required
def delete_event(current_user, event_id):
    """Delete an event"""
    try:
        event = CalendarEvent.query.filter_by(id=event_id, user_id=current_user.id).first()
        if not event:
            return error_response("Event not found", 404)

        db.session.delete(event)
        db.session.commit()
        return success_response({"message": "Event deleted successfully"})
        # (Alternativt: return ("", 204))

    except Exception as e:
        logger.error(f"Error in delete_event: {str(e)}")
        db.session.rollback()
        return error_response("Failed to delete event", 500)

# --------------------- Day Notes endpoints ---------------------

@calendar_api.route('/notes/<date_str>', methods=['GET'])
@token_required
def get_day_note(current_user, date_str):
    """Get notes for a specific day (date_str = YYYY-MM-DD)"""
    try:
        try:
            day_date = date.fromisoformat(date_str)
        except ValueError:
            return error_response("Invalid date format. Use YYYY-MM-DD.", 400)

        note = DayNote.query.filter_by(date=day_date, user_id=current_user.id).first()
        if not note:
            return success_response({"date": date_str, "notes": ""})

        return success_response({
            "id": note.id,
            "date": note.date.isoformat(),
            "notes": note.notes
        })

    except Exception as e:
        logger.error(f"Error in get_day_note: {str(e)}")
        return error_response("Failed to fetch day note", 500)


@calendar_api.route('/notes/<date_str>', methods=['POST', 'PUT'])
@token_required
def save_day_note(current_user, date_str):
    """Create or update notes for a specific day (date_str = YYYY-MM-DD)"""
    try:
        try:
            day_date = date.fromisoformat(date_str)
        except ValueError:
            return error_response("Invalid date format. Use YYYY-MM-DD.", 400)

        data = request.get_json(silent=True) or {}
        if 'notes' not in data:
            return error_response("Missing required field: notes", 400)

        note = DayNote.query.filter_by(date=day_date, user_id=current_user.id).first()
        if note:
            note.notes = data['notes']
            note.updated_at = datetime.utcnow()
        else:
            note = DayNote(
                id=DayNote.generate_id(),
                date=day_date,
                notes=data['notes'],
                user_id=current_user.id
            )
            db.session.add(note)

        db.session.commit()

        return success_response({
            "id": note.id,
            "date": note.date.isoformat(),
            "notes": note.notes
        })

    except Exception as e:
        logger.error(f"Error in save_day_note: {str(e)}")
        db.session.rollback()
        return error_response("Failed to save day note", 500)
