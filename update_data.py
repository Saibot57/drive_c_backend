# update_data.py
from app import create_app
from services.db_config import db
from models.user import User
from models.calendar import CalendarEvent, DayNote
from services.db_config import DriveFile

app = create_app()

with app.app_context():
    # Find the admin user
    admin_user = User.query.filter_by(username="admin").first()

    if not admin_user:
        print("No admin user found. Please run the application first to create the default user.")
        exit(1)

    admin_id = admin_user.id
    print(f"Using admin user: {admin_user.username} (ID: {admin_id})")

    # Using raw SQL to update drive_files
    try:
        result = db.session.execute(
            "UPDATE drive_files SET user_id = :user_id WHERE user_id IS NULL OR user_id = ''",
            {"user_id": admin_id}
        )
        updated_count = result.rowcount
        db.session.commit()
        print(f"Updated {updated_count} drive files")
    except Exception as e:
        db.session.rollback()
        print(f"Error updating drive_files: {e}")

    # Update calendar events
    try:
        events_updated = CalendarEvent.query.filter(CalendarEvent.user_id.is_(None)).update({'user_id': admin_id})
        db.session.commit()
        print(f"Updated {events_updated} calendar events")
    except Exception as e:
        db.session.rollback()
        print(f"Error updating calendar events: {e}")

    # Update day notes
    try:
        notes_updated = DayNote.query.filter(DayNote.user_id.is_(None)).update({'user_id': admin_id})
        db.session.commit()
        print(f"Updated {notes_updated} day notes")
    except Exception as e:
        db.session.rollback()
        print(f"Error updating day notes: {e}")

    print("Migration completed successfully")