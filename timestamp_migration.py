# migrations/timestamp_migration.py
from datetime import datetime
from zoneinfo import ZoneInfo
from app import app
from services.db_config import db
from models.calendar import CalendarEvent

def run_migration():
    """
    Migrate calendar events to ensure all stored times are in UTC.
    """
    print("Starting calendar events migration to UTC...")

    # Explicitly use Stockholm timezone
    stockholm_tz = ZoneInfo("Europe/Stockholm")

    with app.app_context():
        # Step 1: Get all existing events
        events = CalendarEvent.query.all()
        print(f"Found {len(events)} events to migrate")

        # Step 2: Convert naive datetimes to UTC
        for event in events:
            if event.start_time and not event.start_time.tzinfo:
                # Assign Stockholm timezone to naive datetime
                local_start = event.start_time.replace(tzinfo=stockholm_tz)
                # Convert to UTC
                event.start_time = local_start.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

            if event.end_time and not event.end_time.tzinfo:
                # Assign Stockholm timezone to naive datetime
                local_end = event.end_time.replace(tzinfo=stockholm_tz)
                # Convert to UTC
                event.end_time = local_end.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

        # Step 3: Commit changes to database
        db.session.commit()
        print("Migration completed successfully")

if __name__ == "__main__":
    run_migration()