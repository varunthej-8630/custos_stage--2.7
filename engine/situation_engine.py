class SituationEngine:
    """
    Synthesizes discrete event logs and subject behaviors into natural language situational briefings.
    State-Triggered: Text is regenerated ONLY when threat state or active event counts change,
    saving CPU cycles and preventing 30 Hz socket text spam.
    """
    def __init__(self):
        self.last_state_key = None
        self.last_briefing = {
            'summary': 'All zones secure. Normal activity monitored.',
            'risk_level': 'Normal',
            'recommended_action': 'Continue automated monitoring.'
        }

    def evaluate(self, system_score, event_log, active_persons_count):
        # Generate state key to check for state changes
        sorted_events = sorted(list(event_log))
        risk_category = 'Normal' if system_score < 40 else ('Suspicious' if system_score < 60 else ('Threat' if system_score < 80 else 'Critical'))
        current_state_key = (risk_category, tuple(sorted_events), active_persons_count)

        if current_state_key == self.last_state_key:
            return self.last_briefing

        self.last_state_key = current_state_key

        if system_score < 40 and not sorted_events:
            self.last_briefing = {
                'summary': f"Area clear. {active_persons_count} subject(s) monitored with normal activity.",
                'risk_level': 'Normal',
                'recommended_action': 'Continue automated monitoring.'
            }
            return self.last_briefing

        # Build natural language summary
        has_high_breach = any('HIGH' in e or 'restricted' in e for e in sorted_events)
        has_tamper = any('TAMPER' in e for e in sorted_events)

        if has_tamper:
            summary = "ALERT: Camera feed is obstructed or covered! Immediate security response required."
            action = "Dispatch guard immediately to inspect camera hardware."
        elif has_high_breach:
            summary = f"HIGH RISK BREACH: Subject entered restricted protection zone. Threat score {int(system_score)}/100."
            action = "Dispatch security officer to intercept subject in restricted area."
        else:
            event_desc = ", ".join(sorted_events[:2]) if sorted_events else "Suspicious movement"
            summary = f"SUSPICIOUS ACTIVITY: {event_desc} detected. Threat score {int(system_score)}/100."
            action = "Monitor live video feed and verify authorization."

        self.last_briefing = {
            'summary': summary,
            'risk_level': risk_category,
            'recommended_action': action
        }
        return self.last_briefing

situation_engine = SituationEngine()
