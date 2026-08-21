# web/models.py — Forwarding module to database.models
from database.models import db, UserRole, User, LoginHistory, AuditLog, Incident, Subject, Evidence, BehaviorLog

__all__ = [
    'db',
    'UserRole',
    'User',
    'LoginHistory',
    'AuditLog',
    'Incident',
    'Subject',
    'Evidence',
    'BehaviorLog'
]
