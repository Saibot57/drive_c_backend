# Spara som init_db.py och kör: python init_db.py
from app import create_app
from services.db_config import db
# Det är viktigt att importera modellen så att SQLAlchemy känner till den
from models.planner_models import PlannerActivity

app = create_app()

with app.app_context():
    print("Skapar tabeller som saknas...")
    db.create_all()
    print("Klart! Tabellen planner_activity borde nu finnas.")