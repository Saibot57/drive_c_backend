# api/auth_routes.py
from flask import Blueprint, jsonify, request
from services.db_config import db
from models.user import User
from functools import wraps
from datetime import datetime, timedelta
import logging
import jwt

from config.settings import SECRET_KEY

logger = logging.getLogger(__name__)
auth = Blueprint('auth', __name__)


def success_response(data=None, status_code=200):
    return jsonify({"success": True, "data": data if data is not None else {}, "error": None}), status_code


def error_response(message, status_code=400, data=None):
    return jsonify({"success": False, "data": data, "error": message}), status_code

# ---- Auth-dekorator (OPTIONS passas vidare utan validering) ----
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.split(" ", 1)[1] if auth_header.startswith("Bearer ") else None
        if not token:
            return error_response('Authentication token is missing', 401)
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            user_id = data.get('user_id')
            if not user_id:
                return error_response('Invalid authentication token', 401)
            user = User.query.filter_by(id=user_id).first()
            if not user:
                return error_response('Invalid authentication token', 401)
        except Exception as e:
            logger.error(f"Token validation error: {str(e)}")
            return error_response('Invalid authentication token', 401)
        return f(user, *args, **kwargs)
    return decorated

# ---- Endpoints ----
@auth.route('/login', methods=['POST'])
def login():
    try:
        auth_data = request.get_json(silent=True) or {}
        username = (auth_data.get('username') or "").strip()
        password = auth_data.get('password')
        if not username or not password:
            return error_response('Username and password are required', 400)

        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            return error_response('Invalid credentials', 401)

        user.last_login = datetime.utcnow()
        db.session.commit()

        token = jwt.encode(
            {
                'user_id': user.id,
                'username': user.username,
                'exp': datetime.utcnow() + timedelta(days=7)
            },
            SECRET_KEY,
            algorithm="HS256"
        )
        return success_response({'token': token, 'user': user.to_dict()})
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return error_response('Login failed', 500)

@auth.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or "").strip()
        password = data.get('password')
        if not username or not password:
            return error_response('Username and password are required', 400)

        if User.query.filter_by(username=username).first():
            return error_response('Username already taken', 400)

        new_user = User(
            id=User.generate_id(),
            username=username,
            email=(data.get('email') or "").strip()
        )
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        token = jwt.encode(
            {
                'user_id': new_user.id,
                'username': new_user.username,
                'exp': datetime.utcnow() + timedelta(days=7)
            },
            SECRET_KEY,
            algorithm="HS256"
        )
        return success_response({'token': token, 'user': new_user.to_dict()}, 201)
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        db.session.rollback()
        return error_response('Registration failed', 500)

@auth.route('/me', methods=['GET'])
@token_required
def get_user_profile(current_user):
    try:
        return success_response(current_user.to_dict())
    except Exception as e:
        logger.error(f"Profile fetch error: {str(e)}")
        return error_response('Failed to get profile', 500)
