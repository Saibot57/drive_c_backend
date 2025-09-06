# app.py
from flask import Flask, jsonify, make_response, request
from flask_cors import CORS
from services.db_config import db
from api.routes import api
from api.calendar_routes import calendar_api
from api.notes_routes import notes
from api.auth_routes import auth
from api.schedule_routes import schedule_bp
from config.settings import (
    DATABASE_URL,
    DATABASE_POOL_OPTIONS,
    CORS_ORIGINS,
    SECRET_KEY
)
import logging
import os

# Konfigurera loggning
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app():
    app = Flask(__name__)

    # --- SPECIFIK OCH STRAM CORS FÖR /api/* ---
    # - Exakta origins (måste matcha browserns Origin)
    # - Tillåt vanliga metoder inkl. PATCH/OPTIONS
    # - JWT i Authorization-header -> inga cookies -> supports_credentials=False
    # - intercept_exceptions=False så CORS-fel inte maskeras som 500
    CORS(
        app,
        resources={r"/api/*": {
            "origins": CORS_ORIGINS,
            "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            "allow_headers": ["Authorization", "Content-Type", "X-Requested-With"],
            "supports_credentials": False,
        }},
        intercept_exceptions=False,
    )

    # --- Global preflight: svara TIDIGT med tom 204 för alla /api/* ---
    @app.before_request
    def global_preflight():
        if request.method == "OPTIONS" and request.path.startswith("/api/"):
            return ("", 204)

    # (Valfritt men robust): spegla begärda headers på preflight
    @app.after_request
    def mirror_requested_cors_headers(resp):
        origin = request.headers.get("Origin")
        acrh = request.headers.get("Access-Control-Request-Headers")
        if origin in CORS_ORIGINS and acrh:
            # Säkerställ att alla begärda headers tillåts i svaret
            resp.headers["Access-Control-Allow-Headers"] = acrh
            vary = resp.headers.get("Vary", "")
            needed = ["Origin", "Access-Control-Request-Headers"]
            for h in needed:
                if h not in vary:
                    vary = (vary + ", " + h).strip(", ").strip()
            if vary:
                resp.headers["Vary"] = vary
        return resp

    # --- Databas ---
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = DATABASE_POOL_OPTIONS
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = SECRET_KEY
    db.init_app(app)

    # --- Blueprints ---
    app.register_blueprint(api, url_prefix='/api')
    app.register_blueprint(calendar_api, url_prefix='/api')  # kvar tills vidare
    app.register_blueprint(notes, url_prefix='/api/notes')
    app.register_blueprint(auth, url_prefix='/api/auth')
    app.register_blueprint(schedule_bp, url_prefix='/api/schedule')

    # --- Felhanterare ---
    @app.errorhandler(404)
    def not_found_error(error):
        return make_response(jsonify({"status": "error", "message": "Resource not found"}), 404)

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"Internal server error: {str(error)}")
        db.session.rollback()
        return make_response(jsonify({"status": "error", "message": "Internal server error"}), 500)

    # --- Health check ---
    @app.route('/health')
    def health_check():
        try:
            db.session.execute('SELECT 1')
            return jsonify({"status": "healthy", "database": "connected"})
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return jsonify({"status": "unhealthy", "database": str(e)}), 500

    return app

app = create_app()

# Initiera databas och skapa tabeller
with app.app_context():
    try:
        from services.db_config import DriveFile, NoteContent
        from models.calendar import CalendarEvent, DayNote
        from models.user import User
        from models.schedule_models import Activity, FamilyMember, Settings
        db.create_all()
        logger.info("Database tables, including new schedule tables, created successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {str(e)}")

# Serverkonfiguration för lokal utveckling
if __name__ == '__main__':
    if not os.getenv('PYTHONANYWHERE_DOMAIN'):
        port = int(os.getenv('FLASK_PORT', 5001))
        debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
        logger.info(f"Starting development server on port {port}")
        app.run(debug=debug, port=port, host='0.0.0.0')
