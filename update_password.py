# change_password.py
from app import create_app
from services.db_config import db
from models.user import User
from werkzeug.security import generate_password_hash

app = create_app()

with app.app_context():
    # Get the admin user
    admin_user = User.query.filter_by(username="admin").first()

    if not admin_user:
        print("Admin user not found!")
        exit(1)

    # Get the new password
    new_password = input("Enter new password: ")

    # Update the password
    admin_user.password_hash = generate_password_hash(new_password)

    # Save changes
    db.session.commit()

    print("Password updated successfully!")