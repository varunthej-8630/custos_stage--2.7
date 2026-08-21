class IdentityLayer:
    """
    Decouples Detection vs Tracking vs Identity Classification.
    
    Identity Status (Stage 2):
      - TRACKED_SUBJECT (Temporary Track ID assigned via ByteTrack)
      - UNTRACKED_SUBJECT (Transient un-associated detection)
      (Full KNOWN / UNKNOWN / UNCERTAIN classification deferred to Stage 3 ReID engine)
      
    Security Risk Rating:
      - NORMAL (Score < 40)
      - SUSPICIOUS (40 <= Score < 60)
      - THREAT (60 <= Score < 80)
      - CRITICAL (Score >= 80)
    """
    @staticmethod
    def classify_risk_rating(score):
        if score >= 80.0: return 'CRITICAL'
        if score >= 60.0: return 'THREAT'
        if score >= 40.0: return 'SUSPICIOUS'
        return 'NORMAL'

    @staticmethod
    def classify_identity(track_id=None):
        if track_id is not None:
            return {
                'identity_status': 'TRACKED_SUBJECT',
                'label': f"Track-{track_id}",
                'confidence': 1.0
            }
        return {
            'identity_status': 'UNTRACKED_SUBJECT',
            'label': 'Transient Detection',
            'confidence': 0.0
        }

identity_layer = IdentityLayer()
