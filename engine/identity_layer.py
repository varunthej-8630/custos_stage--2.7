# engine/identity_layer.py — CUSTOS People Intelligence Identity Layer
from typing import Dict, Any, Optional

class IdentityLayer:
    """
    Decouples Detection vs Tracking vs Identity Classification.
    
    Identity Status:
      - KNOWN: Enrolled profile matched with confidence >= threshold.
      - SUSPICIOUS: Profile marked suspicious matched with confidence >= threshold.
      - UNKNOWN: Human face detected, clustered or unknown.
      - UNIDENTIFIED / TRACKED_SUBJECT: Face not currently detected / occluded / too far.
      
    Security Risk Rating:
      - NORMAL (Score < 40)
      - SUSPICIOUS (40 <= Score < 60)
      - THREAT (60 <= Score < 80)
      - CRITICAL (Score >= 80)
    """
    @staticmethod
    def classify_risk_rating(score: float) -> str:
        if score >= 80.0: return 'CRITICAL'
        if score >= 60.0: return 'THREAT'
        if score >= 40.0: return 'SUSPICIOUS'
        return 'NORMAL'

    @staticmethod
    def classify_identity(track_id: int, person_memory: Optional[Any] = None) -> Dict[str, Any]:
        """Legacy and direct identity classifier helper."""
        if person_memory and hasattr(person_memory, 'identity'):
            data = dict(person_memory.identity)
            data['identity_status'] = data.get('status', 'TRACKED_SUBJECT')
            data['label'] = data.get('label') or f'Track-{track_id}'
            return data
        return {
            'status': 'TRACKED_SUBJECT',
            'identity_status': 'TRACKED_SUBJECT',
            'label': f'Track-{track_id}',
            'person_id': f'Person-{track_id}',
            'classification': 'UNIDENTIFIED',
            'confidence': 1.0
        }



    @staticmethod
    def format_security_context(
        camera_id: int,
        track_id: int,
        identity_data: Dict[str, Any],
        zone_name: Optional[str],
        risk_score: float,
        tamper: bool = False
    ) -> Dict[str, Any]:
        """
        Builds the unified canonical security context for DecisionEngine & IncidentLifecycle.
        """
        return {
            'camera_id': camera_id,
            'track_id': track_id,
            'person_id': identity_data.get('person_id'),
            'cluster_id': identity_data.get('cluster_id'),
            'identity': identity_data.get('label', f'Person-{track_id}'),
            'classification': identity_data.get('classification', 'UNIDENTIFIED'),
            'recognition_score': float(identity_data.get('recognition_score', 0.0)),
            'zone': zone_name or 'NORMAL',
            'risk_score': round(risk_score, 1),
            'tamper': bool(tamper)
        }

identity_layer = IdentityLayer()
