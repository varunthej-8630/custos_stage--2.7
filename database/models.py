import os
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class UserRole:
    ADMIN = 'Admin'
    SECURITY_MANAGER = 'Security Manager'
    OPERATOR = 'Operator'
    VIEWER = 'Viewer'

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, index=True)
    email = db.Column(db.String(120), unique=True, index=True)
    password_hash = db.Column(db.String(128))
    google_id = db.Column(db.String(120), unique=True, nullable=True)
    
    role = db.Column(db.String(32), default=UserRole.VIEWER)
    is_active = db.Column(db.Boolean, default=True)
    is_email_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def has_role(self, role):
        roles_hierarchy = {
            UserRole.ADMIN: 4,
            UserRole.SECURITY_MANAGER: 3,
            UserRole.OPERATOR: 2,
            UserRole.VIEWER: 1
        }
        return roles_hierarchy.get(self.role, 0) >= roles_hierarchy.get(role, 0)

class LoginHistory(db.Model):
    __tablename__ = 'login_history'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    ip_address = db.Column(db.String(45))
    login_time = db.Column(db.DateTime, default=datetime.utcnow)
    success = db.Column(db.Boolean, default=False)
    user_agent = db.Column(db.String(255))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(128))
    target = db.Column(db.String(128))
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class Incident(db.Model):
    __tablename__ = 'incidents'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    camera_id = db.Column(db.Integer, default=0, index=True)
    zone_name = db.Column(db.String(64), default='Observation Area', index=True)
    score = db.Column(db.Float, index=True)
    reliability_score = db.Column(db.Float, default=100.0, index=True)
    
    subject_id = db.Column(db.String(64), index=True)
    subject_dwell_time = db.Column(db.Float, default=0.0)
    
    events = db.Column(db.Text) # JSON serialized list
    ai_summary = db.Column(db.Text)
    recommended_action = db.Column(db.Text)
    timeline_json = db.Column(db.Text)
    behavior_history_json = db.Column(db.Text)
    
    status = db.Column(db.String(32), default='New', index=True) # New, Active, Closed, Resolved
    snapshot_path = db.Column(db.String(255))
    clip_path = db.Column(db.String(255))
    snapshot_status = db.Column(db.String(32), default='NONE') # AVAILABLE, FAILED, NONE
    video_status = db.Column(db.String(32), default='NONE') # AVAILABLE, RECORDING, PROCESSING, FAILED, NONE
    evidence_status = db.Column(db.String(32), default='PENDING') # PENDING, CAPTURING, COMPLETE, PARTIAL, FAILED
    closed_at = db.Column(db.DateTime, nullable=True)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    resolved_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)

    evidence_items = db.relationship('Evidence', backref='incident', lazy=True, cascade='all, delete-orphan')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def threat_score(self):
        return self.score or 0.0

    @threat_score.setter
    def threat_score(self, val):
        self.score = float(val)

    @property
    def severity(self):
        s = self.score or 0.0
        if s >= 80.0:
            return 'CRITICAL'
        elif s >= 60.0:
            return 'HIGH'
        elif s >= 40.0:
            return 'MEDIUM'
        return 'LOW'

    @property
    def incident_type(self):
        if self.events:
            try:
                import json
                evs = json.loads(self.events) if isinstance(self.events, str) else self.events
                if isinstance(evs, list) and len(evs) > 0:
                    first = str(evs[0])
                    if 'TAMPER' in first.upper(): return 'CAMERA TAMPER'
                    if 'HIGH' in first.upper(): return 'RESTRICTED ZONE BREACH'
                    if 'OBS' in first.upper() or 'OBSERVATION' in first.upper(): return 'OBSERVATION ZONE EVENT'
                    return first
            except Exception:
                pass
        return 'SECURITY DETECTION'

    def get_parsed_events(self):
        if not self.events:
            return []
        try:
            import json
            if isinstance(self.events, str):
                return json.loads(self.events)
            elif isinstance(self.events, list):
                return self.events
        except Exception:
            return [str(self.events)]
        return []

    def get_explainable_reasons(self):
        reasons = []
        evts = self.get_parsed_events()
        for e in evts:
            e_up = str(e).upper()
            if 'ENTERED HIGH' in e_up or 'BREACH' in e_up:
                reasons.append('Person entered restricted security zone')
            elif 'PACING' in e_up:
                reasons.append('Pacing back and forth detected')
            elif 'CROUCH' in e_up:
                reasons.append('Crouching / low posture detected')
            elif 'FROZE' in e_up or 'FREEZE' in e_up:
                reasons.append('Sudden freeze / cessation of movement detected')
            elif 'LINGER' in e_up:
                reasons.append(f'Extended dwell time: {self.subject_dwell_time or 0:.1f}s')
            elif 'TAMPER' in e_up:
                reasons.append('Camera lens obstruction / optical tamper confirmed')
            elif 'OBSERVATION' in e_up or 'ENTERED WATCH' in e_up:
                reasons.append('Subject entered observation perimeter')

        if not reasons and evts:
            reasons = [str(x) for x in evts]
        elif not reasons:
            reasons = ['Risk threshold exceeded in monitored area']
        return list(dict.fromkeys(reasons))

    def to_alert_dict(self):
        import json
        evs = self.get_parsed_events()
        reasons = self.get_explainable_reasons()
        
        # Primary title and description
        is_tamper = any('TAMPER' in str(e).upper() for e in evs)
        is_high = any('HIGH' in str(e).upper() for e in evs)
        
        if is_tamper:
            title = 'Camera Tamper Detected'
            short_desc = 'Camera lens obstruction or optical tamper verified.'
        elif is_high:
            title = 'Restricted Zone Breach'
            short_desc = f'Person detected inside {self.zone_name or "Restricted Area"}.'
        else:
            title = 'Perimeter Observation Alert'
            short_desc = f'Activity detected in {self.zone_name or "Observation Zone"}.'

        has_snap = bool(self.snapshot_path and self.snapshot_status != 'FAILED')
        has_clip = bool(self.clip_path and self.video_status != 'FAILED')

        return {
            'id': self.id,
            'incident_id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'time_display': self.timestamp.strftime('%d %b %Y, %I:%M %p') if self.timestamp else 'Just now',
            'time_short': self.timestamp.strftime('%I:%M %p') if self.timestamp else '',
            'camera_id': self.camera_id,
            'camera_name': 'Built-in Camera' if self.camera_id == 0 else f'Camera {self.camera_id + 1}',
            'zone_name': self.zone_name or 'Observation Area',
            'score': round(self.score or 0.0, 1),
            'severity': self.severity,
            'status': self.status or 'Active',
            'title': title,
            'short_desc': short_desc,
            'incident_type': self.incident_type,
            'subject_id': self.subject_id or 'Person-01',
            'dwell_time': round(self.subject_dwell_time or 0.0, 1),
            'events': evs,
            'explainable_reasons': reasons,
            'ai_summary': self.ai_summary or f'{title} with risk score {round(self.score or 0)}.',
            'recommended_action': self.recommended_action or 'Verify live camera feed and inspect monitored perimeter.',
            'has_snapshot': has_snap,
            'has_clip': has_clip,
            'has_evidence': has_snap or has_clip,
            'snapshot_status': self.snapshot_status or ('AVAILABLE' if has_snap else 'NONE'),
            'video_status': self.video_status or ('AVAILABLE' if has_clip else 'NONE'),
            'evidence_status': self.evidence_status or 'PENDING',
            'snapshot_url': f'/api/evidence/{self.id}/media/snapshot' if has_snap else None,
            'clip_url': f'/api/evidence/{self.id}/media/clip' if has_clip else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            'notes': self.notes or ''
        }

    def to_evidence_dict(self):
        import json
        timeline = []
        if self.timeline_json:
            try:
                timeline = json.loads(self.timeline_json)
            except Exception:
                pass
        
        if not timeline:
            ts_str = self.timestamp.strftime('%H:%M:%S') if self.timestamp else ''
            timeline = [
                {'time': ts_str, 'event': f'Detection initiated for {self.subject_id or "Subject"}', 'severity': 'LOW'},
                {'time': ts_str, 'event': f'Zone entry confirmed: {self.zone_name or "Area"}', 'severity': 'MEDIUM'},
                {'time': ts_str, 'event': f'Security threshold reached: Score {round(self.score or 0)}', 'severity': self.severity}
            ]

        has_snap = bool(self.snapshot_path and self.snapshot_status != 'FAILED')
        has_clip = bool(self.clip_path and self.video_status != 'FAILED')

        return {
            'id': self.id,
            'incident_id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'time_display': self.timestamp.strftime('%d %b %Y, %I:%M:%S %p') if self.timestamp else '',
            'camera_id': self.camera_id,
            'camera_name': 'Built-in Camera' if self.camera_id == 0 else f'Camera {self.camera_id + 1}',
            'zone_name': self.zone_name or 'Observation Area',
            'score': round(self.score or 0.0, 1),
            'severity': self.severity,
            'status': self.status or 'Active',
            'incident_type': self.incident_type,
            'subject_id': self.subject_id or 'Person-01',
            'dwell_time': round(self.subject_dwell_time or 0.0, 1),
            'has_snapshot': has_snap,
            'has_clip': has_clip,
            'snapshot_status': self.snapshot_status or ('AVAILABLE' if has_snap else 'NONE'),
            'video_status': self.video_status or ('AVAILABLE' if has_clip else 'NONE'),
            'evidence_status': self.evidence_status or ('COMPLETE' if (has_snap and has_clip) else 'PARTIAL' if (has_snap or has_clip) else 'FAILED'),
            'snapshot_url': f'/api/evidence/{self.id}/media/snapshot' if has_snap else None,
            'clip_url': f'/api/evidence/{self.id}/media/clip' if has_clip else None,
            'timeline': timeline,
            'ai_summary': self.ai_summary or '',
            'recommended_action': self.recommended_action or '',
            'explainable_reasons': self.get_explainable_reasons()
        }

class Subject(db.Model):
    __tablename__ = 'subjects'
    
    subject_id = db.Column(db.String(64), primary_key=True)
    first_seen = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    total_dwell_seconds = db.Column(db.Float, default=0.0)
    visited_zones_json = db.Column(db.Text)
    risk_history_json = db.Column(db.Text)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class Evidence(db.Model):
    __tablename__ = 'evidence'
    
    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('incidents.id'), index=True)
    type = db.Column(db.String(32)) # snapshot, clip, timeline
    path = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    metadata_json = db.Column(db.Text)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @property
    def snapshot_path(self):
        return self.path if self.type == 'snapshot' else ''

    @property
    def clip_path(self):
        return self.path if self.type == 'clip' else ''

    @property
    def timeline(self):
        if self.metadata_json:
            try:
                import json
                return json.loads(self.metadata_json)
            except Exception:
                pass
        return []

    @property
    def created_at(self):
        return self.timestamp

    def to_dict(self):
        return {
            'id': self.id,
            'incident_id': self.incident_id,
            'type': self.type,
            'path': self.path,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'timeline': self.timeline
        }

class BehaviorLog(db.Model):
    __tablename__ = 'behavior_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey('incidents.id'), index=True)
    subject_id = db.Column(db.String(64), index=True)
    behavior_name = db.Column(db.String(64))
    confidence = db.Column(db.Float, default=1.0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
