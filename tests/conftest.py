import sys
import os
import pytest
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from web.server import app as flask_app
from database.models import db, User, UserRole, Incident


@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp()
    flask_app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SECRET_KEY': 'test_secret_key',
        'WTF_CSRF_ENABLED': False
    })

    with flask_app.app_context():
        db.drop_all()
        db.create_all()

        admin = User(username='admin', email='admin@test.com', role=UserRole.ADMIN)
        admin.set_password('adminpass')
        
        operator = User(username='operator', email='operator@test.com', role=UserRole.OPERATOR)
        operator.set_password('operatorpass')
        
        viewer = User(username='viewer', email='viewer@test.com', role=UserRole.VIEWER)
        viewer.set_password('viewerpass')

        db.session.add_all([admin, operator, viewer])
        db.session.commit()

        yield flask_app

    os.close(db_fd)
    if os.path.exists(db_path):
        try:
            os.unlink(db_path)
        except PermissionError:
            pass

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def admin_client(app):
    c = app.test_client()
    c.post('/login', data={'username': 'admin', 'password': 'adminpass'}, follow_redirects=True)
    return c

@pytest.fixture
def operator_client(app):
    c = app.test_client()
    c.post('/login', data={'username': 'operator', 'password': 'operatorpass'}, follow_redirects=True)
    return c

@pytest.fixture
def viewer_client(app):
    c = app.test_client()
    c.post('/login', data={'username': 'viewer', 'password': 'viewerpass'}, follow_redirects=True)
    return c
