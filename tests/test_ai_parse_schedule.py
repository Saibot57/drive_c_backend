import os
import sys
import jwt
import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.db_config import db
from api.schedule_routes import schedule_bp
from services.ai_postprocess import normalize_and_align
from services.llm_client import LLMError, _extract_first_json_blob
from models.user import User
from models.schedule_models import FamilyMember
from config.settings import SECRET_KEY


@pytest.fixture
def ai_client():
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'poolclass': StaticPool,
        'connect_args': {'check_same_thread': False},
    }
    app.config['SECRET_KEY'] = SECRET_KEY

    db.init_app(app)
    app.register_blueprint(schedule_bp, url_prefix='/api/schedule')

    with app.app_context():
        db.create_all()
        user = User(id=User.generate_id(), username='tester')
        user.set_password('pw')
        db.session.add(user)
        db.session.flush()

        fm1 = FamilyMember(name='Rut', color='#111111', icon='😀', user_id=user.id)
        fm2 = FamilyMember(name='Bo', color='#222222', icon='😀', user_id=user.id)
        db.session.add_all([fm1, fm2])
        db.session.commit()

        token = jwt.encode({'user_id': user.id}, SECRET_KEY, algorithm='HS256')
        member_ids = {fm.name: fm.id for fm in FamilyMember.query.all()}

    client = app.test_client()
    client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token}'

    yield client, app, member_ids

    with app.app_context():
        db.drop_all()


def test_normalize_maps_participants_and_dates():
    fm = [{'id': '1', 'name': 'Rut'}, {'id': '2', 'name': 'Bo'}]
    items = [{
        'name': 'Fotboll',
        'startTime': '16:00',
        'endTime': '17:30',
        'participants': ['Rut', '2', 'Okänd'],
        'date': '2025-10-03',
    }]

    result = normalize_and_align(items, fm)
    assert len(result) == 1
    entry = result[0]
    assert entry['participants'] == ['1', '2']
    assert entry['days'] == ['Fredag']
    assert entry['week'] == 40
    assert entry['year'] == 2025


def test_normalize_requires_fields():
    fm = [{'id': '1', 'name': 'Rut'}]
    items = [{
        'name': '',
        'startTime': '10:00',
        'endTime': '11:00',
        'participants': ['Rut'],
        'days': ['Måndag'],
        'week': 1,
        'year': 2025,
    }]

    assert normalize_and_align(items, fm) == []


def test_normalize_strict_unknown_participant(monkeypatch):
    monkeypatch.setenv('AI_PARSE_STRICT_UNKNOWN_PARTICIPANTS', '1')
    fm = [{'id': '1', 'name': 'Rut'}]
    items = [{
        'name': 'Träning',
        'startTime': '10:00',
        'endTime': '11:00',
        'participants': ['Unknown'],
        'days': ['Måndag'],
        'week': 1,
        'year': 2025,
    }]

    with pytest.raises(ValueError):
        normalize_and_align(items, fm)


def test_ai_parse_schedule_success(ai_client, monkeypatch):
    client, app, member_ids = ai_client
    rut_id = member_ids['Rut']
    bo_id = member_ids['Bo']

    sample_response = [{
        'name': 'Fotboll',
        'participants': ['Rut', bo_id],
        'startTime': '16:00',
        'endTime': '17:30',
        'date': '2025-10-03',
    }]

    monkeypatch.setattr('api.schedule_routes.parse_schedule_with_llm', lambda prompt: sample_response)

    response = client.post('/api/schedule/ai-parse-schedule', json={'text': 'Rut spelar fotboll'})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    activity = payload['data']['activities'][0]
    assert activity['participants'] == [rut_id, bo_id]
    assert activity['days'] == ['Fredag']
    assert activity['week'] == 40
    assert activity['year'] == 2025


def test_ai_parse_schedule_unknown_participant_dropped(ai_client, monkeypatch):
    client, app, member_ids = ai_client

    sample_response = [{
        'name': 'Solo',
        'participants': ['Unknown'],
        'startTime': '09:00',
        'endTime': '10:00',
        'days': ['Måndag'],
        'week': 12,
        'year': 2025,
    }]

    monkeypatch.setattr('api.schedule_routes.parse_schedule_with_llm', lambda prompt: sample_response)

    response = client.post('/api/schedule/ai-parse-schedule', json={'text': 'Solo aktivitet'})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['data']['activities'][0]['participants'] == []


def test_ai_parse_schedule_unknown_participant_strict(ai_client, monkeypatch):
    client, app, member_ids = ai_client
    monkeypatch.setenv('AI_PARSE_STRICT_UNKNOWN_PARTICIPANTS', '1')

    sample_response = [{
        'name': 'Solo',
        'participants': ['Unknown'],
        'startTime': '09:00',
        'endTime': '10:00',
        'days': ['Måndag'],
        'week': 12,
        'year': 2025,
    }]

    monkeypatch.setattr('api.schedule_routes.parse_schedule_with_llm', lambda prompt: sample_response)

    response = client.post('/api/schedule/ai-parse-schedule', json={'text': 'Solo aktivitet'})
    assert response.status_code == 422
    payload = response.get_json()
    assert 'Unknown participants' in payload['error']


def test_ai_parse_schedule_requires_text(ai_client):
    client, app, member_ids = ai_client
    response = client.post('/api/schedule/ai-parse-schedule', json={'text': ''})
    assert response.status_code == 400


def test_ai_parse_schedule_llm_failure(ai_client, monkeypatch):
    client, app, member_ids = ai_client

    def _raise(*args, **kwargs):
        raise LLMError('boom')

    monkeypatch.setattr('api.schedule_routes.parse_schedule_with_llm', _raise)

    response = client.post('/api/schedule/ai-parse-schedule', json={'text': 'Hej'})
    assert response.status_code == 502


def test_extract_first_json_blob_handles_nested_structures():
    text = 'Svar:\n[{"name": "A", "participants": ["1", "2"], "meta": {"notes": "Hej"}}] extra'
    blob = _extract_first_json_blob(text)
    assert blob == '[{"name": "A", "participants": ["1", "2"], "meta": {"notes": "Hej"}}]'


def test_extract_first_json_blob_prefers_outer_array_over_object():
    text = '{"info": "metadata"}\n[{"name": "A"}]'
    blob = _extract_first_json_blob(text)
    assert blob == '[{"name": "A"}]'


def test_extract_first_json_blob_ignores_braces_inside_strings():
    text = '[{"name": "A", "note": "Use {curly} and [square]"}]'
    blob = _extract_first_json_blob(text)
    assert blob == text
