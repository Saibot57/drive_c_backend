# migration.py
from app import create_app
from services.db_config import db
from models.user import User
from models.calendar import CalendarEvent, DayNote
from services.db_config import DriveFile, NoteContent

app = create_app()

with app.app_context():
    # Add the missing column if it doesn't exist
    try:
        db.engine.execute("ALTER TABLE drive_files ADD COLUMN user_id VARCHAR(36)")
        print("Added user_id column to drive_files table")
    except Exception as e:
        print(f"Error adding column (it might already exist): {e}")

    # Find the admin user (or first user if multiple exist)
    admin_user = User.query.filter_by(username="admin").first()

    if not admin_user:
        print("No admin user found. Please run the application first to create the default user.")
        exit(1)

    admin_id = admin_user.id
    print(f"Using admin user: {admin_user.username} (ID: {admin_id})")

    # Update calendar events
    events_updated = CalendarEvent.query.filter(CalendarEvent.user_id.is_(None)).update({'user_id': admin_id})
    print(f"Updated {events_updated} calendar events")

    # Update day notes
    notes_updated = DayNote.query.filter(DayNote.user_id.is_(None)).update({'user_id': admin_id})
    print(f"Updated {notes_updated} day notes")

    # Update drive files
    files_updated = DriveFile.query.filter(DriveFile.user_id.is_(None)).update({'user_id': admin_id})
    print(f"Updated {files_updated} drive files")

    # Commit the changes
    db.session.commit()
    print("Migration completed successfully")