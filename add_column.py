# add_column.py
from app import create_app
from services.db_config import db

app = create_app()

with app.app_context():
    try:
        # Try to execute raw SQL to add the column
        result = db.session.execute("ALTER TABLE drive_files ADD COLUMN user_id VARCHAR(36)")
        db.session.commit()
        print("Successfully added user_id column to drive_files table")
    except Exception as e:
        db.session.rollback()
        print(f"Error adding column: {e}")