import os
import sys
import uuid
import jwt
import pytest
from flask import Flask
from sqlalchemy.pool import StaticPool

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.db_config import db
from api.schedule_routes import schedule_bp
from models.user import User
from models.schedule_models import FamilyMember, Activity
import models.calendar  # noqa: F401
from config.settings import SECRET_KEY


@pytest.fixture
def client():
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
        db.session.commit()
        token = jwt.encode({'user_id': user.id}, SECRET_KEY, algorithm='HS256')
    test_client = app.test_client()
    test_client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    yield test_client, user


def test_create_update_delete_member(client):
    c, user = client
    res = c.post('/api/schedule/family-members', json={'name': 'Alice', 'color': '#123456', 'icon': '😀'})
    assert res.status_code == 201
    fid = res.get_json()['data']['id']

    res = c.put(f'/api/schedule/family-members/{fid}', json={'color': '#654321'})
    assert res.status_code == 200
    assert res.get_json()['data']['color'] == '#654321'

    res = c.delete(f'/api/schedule/family-members/{fid}')
    assert res.status_code == 204
    assert res.data == b''


def test_duplicate_name_case_insensitive(client):
    c, user = client
    res = c.post('/api/schedule/family-members', json={'name': 'Bob', 'color': '#111111', 'icon': '😀'})
    assert res.status_code == 201
    res = c.post('/api/schedule/family-members', json={'name': 'bob', 'color': '#222222', 'icon': '😀'})
    assert res.status_code == 400


def test_invalid_color_and_emoji(client):
    c, user = client
    res = c.post('/api/schedule/family-members', json={'name': 'Color', 'color': '123456', 'icon': '😀'})
    assert res.status_code == 400
    res = c.post('/api/schedule/family-members', json={'name': 'Emoji', 'color': '#123456', 'icon': 'not'})
    assert res.status_code == 400


def test_delete_member_with_activities(client):
    c, user = client
    res = c.post('/api/schedule/family-members', json={'name': 'Del', 'color': '#123456', 'icon': '😀'})
    fid = res.get_json()['data']['id']
    with c.application.app_context():
        fm = FamilyMember.query.get(fid)
        act = Activity(
            id=str(uuid.uuid4()),
            user_id=user.id,
            name='A',
            icon='🏃',
            day='Måndag',
            week=1,
            year=2024,
            start_time='10:00',
            end_time='11:00',
        )
        act.participants.append(fm)
        db.session.add(act)
        db.session.commit()
    res = c.delete(f'/api/schedule/family-members/{fid}')
    assert res.status_code == 409


def test_reorder_invalid_ids(client):
    c, user = client
    r1 = c.post('/api/schedule/family-members', json={'name': 'A', 'color': '#111111', 'icon': '😀'})
    id1 = r1.get_json()['data']['id']
    r2 = c.post('/api/schedule/family-members', json={'name': 'B', 'color': '#222222', 'icon': '😀'})
    id2 = r2.get_json()['data']['id']
    res = c.post('/api/schedule/family-members/reorder', json={'order': [id1]})
    assert res.status_code == 400
    res = c.post('/api/schedule/family-members/reorder', json={'order': [id1, 'bad']})
    assert res.status_code == 400


def test_get_members_sorted(client):
    c, user = client
    r1 = c.post('/api/schedule/family-members', json={'name': 'Charlie', 'color': '#111111', 'icon': '😀'})
    id1 = r1.get_json()['data']['id']
    r2 = c.post('/api/schedule/family-members', json={'name': 'Bravo', 'color': '#222222', 'icon': '😀'})
    id2 = r2.get_json()['data']['id']
    r3 = c.post('/api/schedule/family-members', json={'name': 'Alpha', 'color': '#333333', 'icon': '😀'})
    id3 = r3.get_json()['data']['id']
    c.put(f'/api/schedule/family-members/{id1}', json={'displayOrder': None})
    c.put(f'/api/schedule/family-members/{id2}', json={'displayOrder': None})
    res = c.get('/api/schedule/family-members')
    names = [m['name'] for m in res.get_json()['data']]
    assert names == ['Alpha', 'Bravo', 'Charlie']
