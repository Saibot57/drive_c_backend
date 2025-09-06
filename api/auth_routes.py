# api/auth_routes.py
from flask import Blueprint, jsonify, request
from services.db_config import db
from models.user import User
from functools import wraps
from datetime import datetime, timedelta, timezone
import logging
import json, base64, hmac, hashlib

logger = logging.getLogger(__name__)
auth = Blueprint('auth', __name__)

# ---- Minimal, säker fallback-JWT (HS256) ----
def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")

def _b64url_decode(s: str) -> bytes:
    pad = '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)

class JWT:
    @staticmethod
    def encode(payload: dict, key: str, algorithm: str = "HS256") -> str:
        if algorithm != "HS256":
            raise ValueError("Only HS256 is supported by this fallback JWT.")
        header = {"alg": "HS256", "typ": "JWT"}

        # Standard-claims (läggs till om saknas)
        now = datetime.now(timezone.utc)
        payload = dict(payload)  # kopia så vi ej muterar anroparens dict
        payload.setdefault("iat", int(now.timestamp()))
        payload.setdefault("exp", int((now + timedelta(days=7)).timestamp()))

        header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode())
        payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
        signing_input = f"{header_b64}.{payload_b64}".encode()
        sig = hmac.new(key.encode(), signing_input, hashlib.sha256).digest()
        signature_b64 = _b64url_encode(sig)
        return f"{header_b64}.{payload_b64}.{signature_b64}"

    @staticmethod
    def decode(token: str, key: str, algorithms=None) -> dict:
        if algorithms is None:
            algorithms = ["HS256"]
        parts = token.split(".")
        if len(parts) != 3:
            raise Exception("Invalid token format")
        header_b64, payload_b64, signature_b64 = parts

        header = json.loads(_b64url_decode(header_b64))
        alg = header.get("alg")
        if alg not in algorithms or alg != "HS256":
            raise Exception("Unsupported or disallowed algorithm")

        # Verifiera signatur (konstant tidsjämförelse)
        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected_sig = hmac.new(key.encode(), signing_input, hashlib.sha256).digest()
        expected_sig_b64 = _b64url_encode(expected_sig)
        if not hmac.compare_digest(signature_b64, expected_sig_b64):
            raise Exception("Invalid signature")

        payload = json.loads(_b64url_decode(payload_b64))

        # Expirations- och nbf-kontroller
        now_ts = int(datetime.now(timezone.utc).timestamp())
        nbf = payload.get("nbf")
        exp = payload.get("exp")
        if nbf is not None and now_ts < int(nbf):
            raise Exception("Token not yet valid")
        if exp is not None and now_ts >= int(exp):
            raise Exception("Token has expired")

        return payload

# Använd klassens statiska metoder via 'jwt'
jwt = JWT
from config.settings import SECRET_KEY

# ---- Auth-dekorator (OPTIONS passas vidare utan validering) ----
def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.split(" ", 1)[1] if auth_header.startswith("Bearer ") else None
        if not token:
            return jsonify({'status': 'error', 'message': 'Authentication token is missing'}), 401
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            user_id = data.get('user_id')
            if not user_id:
                return jsonify({'status': 'error', 'message': 'Invalid authentication token'}), 401
            user = User.query.filter_by(id=user_id).first()
            if not user:
                return jsonify({'status': 'error', 'message': 'Invalid authentication token'}), 401
        except Exception as e:
            logger.error(f"Token validation error: {str(e)}")
            return jsonify({'status': 'error', 'message': 'Invalid authentication token'}), 401
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
            return jsonify({'status': 'error', 'message': 'Username and password are required'}), 400

        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401

        user.last_login = datetime.utcnow()
        db.session.commit()

        token = jwt.encode(
            {
                'user_id': user.id,
                'username': user.username,
                # exp sätts i encode() om saknas
            },
            SECRET_KEY,
            algorithm="HS256"
        )
        return jsonify({'status': 'success', 'data': {'token': token, 'user': user.to_dict()}})
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Login failed'}), 500

@auth.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or "").strip()
        password = data.get('password')
        if not username or not password:
            return jsonify({'status': 'error', 'message': 'Username and password are required'}), 400

        if User.query.filter_by(username=username).first():
            return jsonify({'status': 'error', 'message': 'Username already taken'}), 400

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
            },
            SECRET_KEY,
            algorithm="HS256"
        )
        return jsonify({'status': 'success', 'data': {'token': token, 'user': new_user.to_dict()}}), 201
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        db.session.rollback()
        return jsonify({'status': 'error', 'message': 'Registration failed'}), 500

@auth.route('/me', methods=['GET'])
@token_required
def get_user_profile(current_user):
    try:
        return jsonify({'status': 'success', 'data': current_user.to_dict()})
    except Exception as e:
        logger.error(f"Profile fetch error: {str(e)}")
        return jsonify({'status': 'error', 'message': 'Failed to get profile'}), 500
