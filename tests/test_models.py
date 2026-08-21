from database.models import db, User, UserRole, LoginHistory, AuditLog, Incident


def test_user_password_hashing(app):
    with app.app_context():
        u = User(username='testuser', email='test@custos.local', role=UserRole.OPERATOR)
        u.set_password('securepassword123')
        assert u.check_password('securepassword123') is True
        assert u.check_password('wrongpassword') is False
        assert u.password_hash != 'securepassword123'

def test_user_role_hierarchy(app):
    admin = User(role=UserRole.ADMIN)
    security_mgr = User(role=UserRole.SECURITY_MANAGER)
    operator = User(role=UserRole.OPERATOR)
    viewer = User(role=UserRole.VIEWER)

    # Admin has all rights
    assert admin.has_role(UserRole.VIEWER) is True
    assert admin.has_role(UserRole.OPERATOR) is True
    assert admin.has_role(UserRole.SECURITY_MANAGER) is True
    assert admin.has_role(UserRole.ADMIN) is True

    # Operator has operator and viewer rights
    assert operator.has_role(UserRole.VIEWER) is True
    assert operator.has_role(UserRole.OPERATOR) is True
    assert operator.has_role(UserRole.ADMIN) is False

    # Viewer has only viewer rights
    assert viewer.has_role(UserRole.VIEWER) is True
    assert viewer.has_role(UserRole.OPERATOR) is False

def test_login_history_model(app):
    with app.app_context():
        h = LoginHistory(ip_address='127.0.0.1', success=True, user_agent='PyTest')
        db.session.add(h)
        db.session.commit()

        saved = LoginHistory.query.filter_by(ip_address='127.0.0.1').first()
        assert saved is not None
        assert saved.success is True
        assert saved.user_agent == 'PyTest'

def test_audit_log_model(app):
    with app.app_context():
        log = AuditLog(user_id=1, action='Test Action', target='Test Target', details='Details')
        db.session.add(log)
        db.session.commit()

        saved = AuditLog.query.filter_by(action='Test Action').first()
        assert saved is not None
        assert saved.target == 'Test Target'

def test_incident_model(app):
    with app.app_context():
        inc = Incident(score=85.5, events='["HIGH ZONE BREACH"]', snapshot_path='alert_123.jpg')
        db.session.add(inc)
        db.session.commit()

        saved = Incident.query.filter_by(score=85.5).first()
        assert saved is not None
        assert saved.status == 'New'
        assert saved.snapshot_path == 'alert_123.jpg'
