import json
import threading
from datetime import datetime
from database.models import db, Incident, Subject, Evidence, BehaviorLog, User, UserRole
from engine.logger import app_logger

def parse_events(data):
    if data is None:
        return []
    if isinstance(data, list):
        return [str(x) if not isinstance(x, (dict, list)) else x for x in data]
    if isinstance(data, dict):
        return [data]
    if isinstance(data, str):
        data_str = data.strip()
        if not data_str:
            return []
        try:
            decoded = json.loads(data_str)
            return parse_events(decoded)
        except Exception:
            return [data_str]
    return [str(data)]

class DatabaseManager:
    """
    Central Manager for thread-safe Flask-SQLAlchemy Database Operations.
    """
    def __init__(self):
        self.lock = threading.Lock()

    def init_db(self, app):
        with app.app_context():
            db.create_all()
            admin_user = User.query.filter_by(username='admin').first()
            if not admin_user:
                admin_user = User(username='admin', email='admin@custos.local', role=UserRole.ADMIN)
                admin_user.set_password('admin123')
                db.session.add(admin_user)
            else:
                admin_user.role = UserRole.ADMIN
                admin_user.is_active = True
                admin_user.set_password('admin123')
            db.session.commit()
            app_logger.info("Admin credentials guaranteed: username=admin | password=admin123")


    def save_incident(self, app, incident_data):
        """
        Thread-safe insertion of Incident, Subject, Evidence & BehaviorLogs.
        """
        if not app:
            return None

        with app.app_context():
            with self.lock:
                try:
                    events_list = incident_data.get('events', [])
                    events_str = json.dumps(events_list) if isinstance(events_list, list) else str(events_list)

                    inc = Incident(
                        camera_id=int(incident_data.get('camera_id', 0)),
                        zone_name=incident_data.get('zone_name', 'Observation Area'),
                        score=float(incident_data.get('score', 0.0)),
                        reliability_score=float(incident_data.get('reliability_score', 100.0)),
                        subject_id=incident_data.get('subject_id', 'Person-01'),
                        subject_dwell_time=float(incident_data.get('subject_dwell_time', 0.0)),
                        events=events_str,
                        ai_summary=incident_data.get('ai_summary', ''),
                        recommended_action=incident_data.get('recommended_action', ''),
                        timeline_json=json.dumps(incident_data.get('timeline', [])),
                        behavior_history_json=json.dumps(incident_data.get('behaviors', [])),
                        snapshot_path=incident_data.get('snapshot_path', ''),
                        clip_path=incident_data.get('clip_path', ''),
                        snapshot_status=incident_data.get('snapshot_status', 'AVAILABLE' if incident_data.get('snapshot_path') else 'NONE'),
                        video_status=incident_data.get('video_status', 'AVAILABLE' if incident_data.get('clip_path') else 'NONE'),
                        evidence_status=incident_data.get('evidence_status', 'CAPTURING' if incident_data.get('snapshot_path') else 'PENDING'),
                        status=incident_data.get('status', 'Active')
                    )
                    db.session.add(inc)
                    db.session.commit()

                    # Save evidence links
                    if inc.snapshot_path:
                        ev_snap = Evidence(
                            incident_id=inc.id,
                            type='snapshot',
                            path=inc.snapshot_path,
                            timestamp=inc.timestamp,
                            metadata_json=inc.timeline_json
                        )
                        db.session.add(ev_snap)
                    if inc.clip_path:
                        ev_clip = Evidence(
                            incident_id=inc.id,
                            type='clip',
                            path=inc.clip_path,
                            timestamp=inc.timestamp,
                            metadata_json=inc.timeline_json
                        )
                        db.session.add(ev_clip)

                    # Update subject record
                    subj_id = inc.subject_id
                    if subj_id and subj_id != 'Person-0':
                        subj = Subject.query.filter_by(subject_id=subj_id).first()
                        if not subj:
                            subj = Subject(
                                subject_id=subj_id,
                                first_seen=inc.timestamp,
                                last_seen=inc.timestamp,
                                total_dwell_seconds=inc.subject_dwell_time,
                                visited_zones_json=json.dumps([inc.zone_name])
                            )
                            db.session.add(subj)
                        else:
                            subj.last_seen = inc.timestamp
                            subj.total_dwell_seconds = max(subj.total_dwell_seconds, inc.subject_dwell_time)
                    db.session.commit()
                    app_logger.info(f"Incident {inc.id} saved to Database")
                    return inc.id
                except Exception as e:
                    db.session.rollback()
                    app_logger.error(f"[DB] Save Incident Error: {e}")
                    return None

    def update_incident_lifecycle(self, app, incident_id, snapshot_path=None, snapshot_status=None,
                                 video_status=None, evidence_status=None, dwell_time=None,
                                 score=None, timeline=None, status=None):
        """
        Updates ongoing active incident lifecycle fields (dwell time, score, live timeline, statuses).
        """
        if not app or not incident_id:
            return False

        with app.app_context():
            with self.lock:
                try:
                    inc = db.session.get(Incident, incident_id)
                    if not inc:
                        return False

                    if snapshot_path is not None:
                        inc.snapshot_path = snapshot_path
                    if snapshot_status is not None:
                        inc.snapshot_status = snapshot_status
                    if video_status is not None:
                        inc.video_status = video_status
                    if evidence_status is not None:
                        inc.evidence_status = evidence_status
                    if dwell_time is not None:
                        inc.subject_dwell_time = float(dwell_time)
                    if score is not None:
                        inc.score = max(inc.score or 0.0, float(score))
                    if timeline is not None:
                        inc.timeline_json = json.dumps(timeline) if isinstance(timeline, list) else str(timeline)
                    if status is not None:
                        inc.status = status

                    db.session.commit()
                    return True
                except Exception as e:
                    db.session.rollback()
                    app_logger.error(f"[DB] Update Incident Lifecycle Error: {e}")
                    return False

    def close_incident_lifecycle(self, app, incident_id, clip_path=None, video_status='AVAILABLE',
                                evidence_status='COMPLETE', dwell_time=None, timeline=None):
        """
        Finalizes an incident upon subject exit / tamper recovery with verified MP4 video clip.
        """
        if not app or not incident_id:
            return False

        with app.app_context():
            with self.lock:
                try:
                    inc = db.session.get(Incident, incident_id)
                    if not inc:
                        return False

                    if clip_path:
                        inc.clip_path = clip_path
                        # Link clip to Evidence table if not already added
                        ev_clip = Evidence.query.filter_by(incident_id=inc.id, type='clip').first()
                        if not ev_clip:
                            ev_clip = Evidence(
                                incident_id=inc.id,
                                type='clip',
                                path=clip_path,
                                timestamp=datetime.utcnow(),
                                metadata_json=inc.timeline_json
                            )
                            db.session.add(ev_clip)
                        else:
                            ev_clip.path = clip_path

                    inc.video_status = video_status
                    inc.evidence_status = evidence_status
                    inc.status = 'Closed'
                    inc.closed_at = datetime.utcnow()
                    if dwell_time is not None:
                        inc.subject_dwell_time = float(dwell_time)
                    if timeline is not None:
                        inc.timeline_json = json.dumps(timeline) if isinstance(timeline, list) else str(timeline)

                    db.session.commit()
                    app_logger.info(f"Incident {inc.id} finalized and closed in Database")
                    return True
                except Exception as e:
                    db.session.rollback()
                    app_logger.error(f"[DB] Close Incident Lifecycle Error: {e}")
                    return False

    def _apply_date_filter(self, query, date_range=None, start_date=None, end_date=None):
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        if date_range == 'today':
            start_of_day = datetime(now.year, now.month, now.day)
            query = query.filter(Incident.timestamp >= start_of_day)
        elif date_range in ('7d', '7days', 'week'):
            query = query.filter(Incident.timestamp >= now - timedelta(days=7))
        elif date_range in ('30d', '30days', 'month'):
            query = query.filter(Incident.timestamp >= now - timedelta(days=30))
        elif start_date or end_date:
            if start_date:
                try:
                    dt_s = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                    query = query.filter(Incident.timestamp >= dt_s)
                except Exception:
                    pass
            if end_date:
                try:
                    dt_e = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                    query = query.filter(Incident.timestamp <= dt_e)
                except Exception:
                    pass
        return query

    def query_alerts(self, app, filters=None):
        filters = filters or {}
        with app.app_context():
            query = Incident.query

            # Severity filter
            severity = filters.get('severity')
            if severity:
                sev_u = severity.upper()
                if sev_u == 'CRITICAL':
                    query = query.filter(Incident.score >= 80.0)
                elif sev_u == 'HIGH':
                    query = query.filter(Incident.score >= 60.0, Incident.score < 80.0)
                elif sev_u == 'MEDIUM':
                    query = query.filter(Incident.score >= 40.0, Incident.score < 60.0)
                elif sev_u == 'LOW':
                    query = query.filter(Incident.score < 40.0)

            # Status filter
            status = filters.get('status')
            if status and status.lower() != 'all':
                if status.lower() in ('resolved', 'true'):
                    query = query.filter(Incident.status == 'Resolved')
                elif status.lower() in ('new', 'active', 'unresolved', 'false'):
                    query = query.filter(Incident.status != 'Resolved')

            # Incident type filter
            inc_type = filters.get('type') or filters.get('incident_type')
            if inc_type and inc_type.lower() != 'all':
                type_u = inc_type.upper()
                if 'TAMPER' in type_u:
                    query = query.filter(Incident.events.ilike('%TAMPER%'))
                elif 'BREACH' in type_u or 'ZONE' in type_u:
                    query = query.filter(db.or_(Incident.events.ilike('%HIGH%'), Incident.events.ilike('%BREACH%')))
                elif 'OBS' in type_u or 'WATCH' in type_u:
                    query = query.filter(db.or_(Incident.events.ilike('%OBS%'), Incident.events.ilike('%WATCH%')))
                else:
                    query = query.filter(Incident.events.ilike(f'%{inc_type}%'))

            # Camera ID filter
            camera_id = filters.get('camera_id')
            if camera_id is not None and camera_id != '' and camera_id != 'all':
                try:
                    query = query.filter(Incident.camera_id == int(camera_id))
                except ValueError:
                    pass

            # Zone filter
            zone = filters.get('zone')
            if zone and zone.lower() != 'all':
                query = query.filter(Incident.zone_name.ilike(f'%{zone}%'))

            # Subject ID
            subj = filters.get('subject_id')
            if subj:
                query = query.filter(Incident.subject_id.ilike(f'%{subj}%'))

            # Date range filter
            query = self._apply_date_filter(query, filters.get('date_range'), filters.get('start_date'), filters.get('end_date'))

            # Full-text query (q)
            q = filters.get('q')
            if q:
                pattern = f'%{q}%'
                conds = [
                    Incident.events.ilike(pattern),
                    Incident.ai_summary.ilike(pattern),
                    Incident.recommended_action.ilike(pattern),
                    Incident.subject_id.ilike(pattern),
                    Incident.zone_name.ilike(pattern),
                    Incident.notes.ilike(pattern)
                ]
                try:
                    c_val = int(q)
                    conds.append(Incident.camera_id == c_val)
                except ValueError:
                    pass
                query = query.filter(db.or_(*conds))

            # Total count before pagination
            total_count = query.count()

            # Pagination
            page = max(1, int(filters.get('page', 1)))
            limit = max(1, min(100, int(filters.get('limit', 20))))
            offset = (page - 1) * limit

            incidents = query.order_by(Incident.timestamp.desc()).offset(offset).limit(limit).all()
            items = [inc.to_alert_dict() for inc in incidents]

            return {
                'items': items,
                'total': total_count,
                'page': page,
                'limit': limit,
                'pages': max(1, (total_count + limit - 1) // limit)
            }

    def get_alert_by_id(self, app, alert_id):
        with app.app_context():
            inc = db.session.get(Incident, alert_id)
            if not inc:
                return None
            return inc.to_alert_dict()

    def resolve_alert(self, app, alert_id, user_id=None, notes=''):
        with app.app_context():
            inc = db.session.get(Incident, alert_id)
            if not inc:
                return None
            inc.status = 'Resolved'
            inc.resolved_at = datetime.utcnow()
            if user_id:
                inc.resolved_by_id = user_id
            if notes:
                inc.notes = notes
            db.session.commit()
            return inc.to_alert_dict()

    def get_alerts_stats(self, app):
        from datetime import datetime
        with app.app_context():
            now = datetime.utcnow()
            start_of_day = datetime(now.year, now.month, now.day)

            total_alerts = Incident.query.count()
            active_alerts = Incident.query.filter(Incident.status != 'Resolved').count()
            today_alerts = Incident.query.filter(Incident.timestamp >= start_of_day).count()
            critical_alerts = Incident.query.filter(Incident.score >= 80.0, Incident.status != 'Resolved').count()
            resolved_alerts = Incident.query.filter(Incident.status == 'Resolved').count()

            return {
                'total_alerts': total_alerts,
                'active_alerts': active_alerts,
                'today_alerts': today_alerts,
                'critical_alerts': critical_alerts,
                'resolved_alerts': resolved_alerts,
                'camera_status': 'Online'
            }

    def query_evidence(self, app, filters=None):
        filters = filters or {}
        with app.app_context():
            # Query incidents that serve as the canonical source of evidence
            query = Incident.query

            # Type filter
            ev_type = filters.get('type')
            if ev_type and ev_type.lower() != 'all':
                t_low = ev_type.lower()
                if t_low == 'snapshot':
                    query = query.filter(Incident.snapshot_path != None, Incident.snapshot_path != '')
                elif t_low in ('clip', 'video'):
                    query = query.filter(Incident.clip_path != None, Incident.clip_path != '')
                elif t_low == 'tamper':
                    query = query.filter(Incident.events.ilike('%TAMPER%'))
                elif t_low in ('zone breach', 'breach'):
                    query = query.filter(db.or_(Incident.events.ilike('%HIGH%'), Incident.events.ilike('%BREACH%')))

            # Severity filter
            severity = filters.get('severity')
            if severity and severity.upper() != 'ALL':
                sev_u = severity.upper()
                if sev_u == 'CRITICAL':
                    query = query.filter(Incident.score >= 80.0)
                elif sev_u == 'HIGH':
                    query = query.filter(Incident.score >= 60.0, Incident.score < 80.0)
                elif sev_u == 'MEDIUM':
                    query = query.filter(Incident.score >= 40.0, Incident.score < 60.0)
                elif sev_u == 'LOW':
                    query = query.filter(Incident.score < 40.0)

            # Camera ID
            cam_id = filters.get('camera_id')
            if cam_id is not None and cam_id != '' and cam_id != 'all':
                try:
                    query = query.filter(Incident.camera_id == int(cam_id))
                except ValueError:
                    pass

            # Zone
            zone = filters.get('zone')
            if zone and zone.lower() != 'all':
                query = query.filter(Incident.zone_name.ilike(f'%{zone}%'))

            # Date Range
            query = self._apply_date_filter(query, filters.get('date_range'), filters.get('start_date'), filters.get('end_date'))

            # Search query
            q = filters.get('q')
            if q:
                pattern = f'%{q}%'
                conds = [
                    Incident.events.ilike(pattern),
                    Incident.ai_summary.ilike(pattern),
                    Incident.recommended_action.ilike(pattern),
                    Incident.subject_id.ilike(pattern),
                    Incident.zone_name.ilike(pattern)
                ]
                try:
                    c_val = int(q)
                    conds.append(Incident.camera_id == c_val)
                except ValueError:
                    pass
                query = query.filter(db.or_(*conds))

            total_count = query.count()

            page = max(1, int(filters.get('page', 1)))
            limit = max(1, min(100, int(filters.get('limit', 20))))
            offset = (page - 1) * limit

            incidents = query.order_by(Incident.timestamp.desc()).offset(offset).limit(limit).all()
            items = [inc.to_evidence_dict() for inc in incidents]

            return {
                'items': items,
                'total': total_count,
                'page': page,
                'limit': limit,
                'pages': max(1, (total_count + limit - 1) // limit)
            }

    def get_evidence_by_id(self, app, evidence_id):
        with app.app_context():
            inc = db.session.get(Incident, evidence_id)
            if not inc:
                return None
            return inc.to_evidence_dict()

    def get_evidence_stats(self, app):
        with app.app_context():
            total_records = Incident.query.count()
            snapshots_count = Incident.query.filter(Incident.snapshot_path != None, Incident.snapshot_path != '').count()
            clips_count = Incident.query.filter(Incident.clip_path != None, Incident.clip_path != '').count()
            tamper_count = Incident.query.filter(Incident.events.ilike('%TAMPER%')).count()

            return {
                'total_evidence': total_records,
                'total_records': total_records,
                'snapshots_count': snapshots_count,
                'total_snapshots': snapshots_count,
                'clips_count': clips_count,
                'total_clips': clips_count,
                'tamper_count': tamper_count
            }

db_manager = DatabaseManager()
