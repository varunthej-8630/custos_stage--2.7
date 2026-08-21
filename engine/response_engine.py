import json
import time
import os
from web.models import db, Incident

class ResponseEngine:
    def __init__(self, alert_manager):
        self.alerts = alert_manager
        self.app = None # Needs Flask app context for DB

    def set_app(self, app):
        self.app = app

    def process(self, frame, score, event_log, alert_active, tamper, pre_tamper_clip=None):
        if tamper:
            self.alerts.send_tamper_alert(pre_tamper_clip_path=pre_tamper_clip)
            return

        if alert_active:
            # check_and_send expects (frame, score, pseudo_risk_engine)
            # We'll just bypass and use it directly or pass a dummy
            class DummyRisk:
                def should_alert(self): return True
                def __init__(self, el): self.event_log = el
            
            # The actual AlertManager creates the snapshot and sends it.
            # We also want to record an Incident in the DB.
            now = time.time()
            if now - self.alerts.last_alert >= 10: # config.ALERT_COOLDOWN usually
                self.alerts.last_alert = now
                snap_path = self.alerts._save_snapshot(frame, score)
                
                # Try to use app context to save to DB
                if self.app:
                    with self.app.app_context():
                        events_arr = list(event_log) if event_log else ["Security Alert Triggered"]
                        inc = Incident(
                            camera_id=0,
                            zone_name='Protection Zone',
                            score=score,
                            reliability_score=85.0,
                            subject_id='Person-1',
                            subject_dwell_time=15.0,
                            events=json.dumps(events_arr),
                            ai_summary=' · '.join(events_arr),
                            recommended_action='Dispatch security team to inspect zone.',
                            timeline_json=json.dumps([{'step': i+1, 'time': time.strftime("%I:%M:%S %p"), 'action': e} for i, e in enumerate(events_arr)]),
                            snapshot_path=os.path.basename(snap_path) if snap_path else None,
                            clip_path=os.path.basename(pre_tamper_clip) if pre_tamper_clip else None
                        )
                        db.session.add(inc)
                        db.session.commit()

                
                msg = self.alerts._build_message(score, event_log)
                self.alerts._play_alarm()
                self.alerts._desktop_popup(score, event_log)
                if self.alerts.bot:
                    self.alerts._send_queue.put(('photo', msg, snap_path))
                else:
                    from engine.logger import alert_logger
                    alert_logger.info(f'{msg}')
