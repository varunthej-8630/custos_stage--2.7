# CUSTOS — Change Log

## Optimisation Pass (March 2026)

### Architecture
- **`utils.py` (NEW)** — Single source of truth for `iou()`, `box_centre()`, `box_foot()`. Previously the same function was copy-pasted identically in `web_server.py`, `tracker.py`, and `zone_selector.py`. Now one definition, imported everywhere.
- **`main.py`** — Clarified as the standalone debug entry point. `web_server.py` is the production entry point.

### Detection & Scoring (`risk_engine.py`)
- Signal weights tuned to the 4 reliably detected behaviours: **running (28), crouching (35), erratic movement (22), pacing (20)**
- These 4 signals now trigger alerts solo in OBSERVATION zones — previously all single-signal events were dampened to 25%, blocking real alerts
- Lingering and freeze still require corroboration (less reliable)
- Score smoothing window reduced 3→2 frames for faster response
- Decay rate increased to 7× when no one is in any zone — score drops fast after person leaves

### Dashboard (`dashboard/index.html`)
- **Zone coordinate mapping** — was using `feedEl.naturalWidth` which returns `0` on MJPEG streams. Now uses real camera frame dimensions (`cam_w`, `cam_h`) sent from server via socket on startup
- **Socket reconnection** — added `reconnection: true` with exponential backoff. Previously a dropped connection required a page refresh
- **`prevZone` ghost fix** — drag-preview was accumulating ghost outlines. Fixed by calling `redraw()` before drawing the preview each frame
- **Auto-resolve UI** — `alert_resolved` socket event now turns banner green, stamps timeline entries with ✓ RESOLVED, and auto-dismisses after 4s
- **Connection status indicator** — sidebar pip turns amber when reconnecting, green when live

### Web Server (`web_server.py`)
- **Bounding boxes removed** from MJPEG stream — zones only on the video feed
- **Socket emit always fires** every 6 frames regardless of monitoring state — previously the browser got no updates until zones were configured
- **Camera dimensions exposed** — `cam_w`/`cam_h` captured after warmup and sent to browser via both `/state` route and socket
- **Auto-resolve** — server emits `alert_resolved` when threat drops and person leaves zone
- **Credentials moved to env vars** — `CUSTOS_USER`, `CUSTOS_PASS`, `CUSTOS_SECRET` via `.env` file
- **`/ping` route** added for health checks
- **Socket ping config** — `ping_timeout=20`, `ping_interval=10` to prevent silent disconnections
- **`_iou` removed** — now imported from `utils.py`
- **`save_pretamper_clip` deduplicated** — single definition, shared

### Zone Monitor (`zone_monitor.py`)
- Removed `config_tamper_std_thresh()` workaround function that imported config inside itself
- Config now imported normally at module top
- `TAMPER_CONFIRM_SEC` and diff threshold pulled from config constants (were hardcoded)

### Credentials & Security
- **`.env.example`** — template with all required vars documented
- **`.gitignore`** — prevents `.env`, model weights (`*.pt`), and output dirs from being committed

### Tracker (`tracker.py`)
- Dead `is_inside_any_zone_iou()` and `_iou()` methods removed
- `iou` and `box_foot` imported from `utils.py`

### Zone Selector (`zone_selector.py`)
- Local `_iou` method removed, imported from `utils.py`