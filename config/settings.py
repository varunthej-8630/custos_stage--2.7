# config.py — All Smart Guard settings
# ─────────────────────────────────────────────────────────
# IMPORTANT: Create a .env file in the same folder with:
#   TELEGRAM_TOKEN=your_token_here
#   TELEGRAM_CHAT_ID=your_chat_id_here
# Never put real credentials directly in this file.
# ─────────────────────────────────────────────────────────

import os
from dotenv import load_dotenv

load_dotenv()

# ── APP VERSION & UPDATER ────────────────────────────────
APP_VERSION  = "1.0.0"
# URL to check for updates (e.g., a raw JSON file on GitHub)
UPDATE_URL   = os.getenv('CUSTOS_UPDATE_URL', 'https://raw.githubusercontent.com/VarunThej/custos-stage1/main/version.json')

# 0 = laptop webcam. For Jetson/RTSP change to your stream URL.
# Provide a list of sources for multiple cameras: [0, 1] or ['rtsp://...', 0]
CAMERA_SOURCES = [0]
# CAMERA_SOURCES = ['rtsp://admin:pass@192.168.1.105:554/stream1', 0]
CAMERA_WARMUP_FRAMES = 3      # Reduced from 20 to 3 for near-instant camera startup

# ── TELEGRAM ─────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv('TELEGRAM_TOKEN',   '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')


# ── AI MODEL ─────────────────────────────────────────────
MODEL_PATH   = 'data/weights/yolov8n.pt'
CONFIDENCE   = 0.40
INPUT_SIZE   = 480
FRAME_SKIP   = 2

# ── ZONE SETTINGS ────────────────────────────────────────
TOUCH_IOU_THRESHOLD = 0.10    # overlap fraction = person touching zone
ZONE_STOP_SECONDS   = 3.0     # seconds inside zone = counted as a visit
ZONE_STOP_PIXELS    = 40      # wider pixel range — catches pacing/loitering too

# ── ZONE TYPES ───────────────────────────────────────────
ZONE_TYPE_HIGH  = 'HIGH'      # bike, cash, storage — strict
ZONE_TYPE_WATCH = 'WATCH'     # shelf, entrance — relaxed

ZONE_TYPE_MULTIPLIER = {
    ZONE_TYPE_HIGH:  1.3,
    ZONE_TYPE_WATCH: 0.7,
}

# ── RISK SCORE ───────────────────────────────────────────
RISK_THRESHOLD   = 60         # alert when score reaches this
ALERT_COOLDOWN   = 60         # seconds between alerts
SCORE_DECAY_RATE = 8          # score drops 8 pts per second when no threat

# ── DWELL / VISIT ─────────────────────────────────────────
DWELL_WARN_SEC      = 10      # accumulated time to start scoring
DWELL_HIGH_SEC      = 30      # accumulated time for high score
DWELL_LINGER_SEC    = 60      # 60+ seconds = lingering alert
VISIT_WINDOW_SEC    = 120     # window to count repeated visits (2 minutes)
VISIT_SUSPICIOUS    = 2       # 2 visits = suspicious

# ── WATCH ZONE ───────────────────────────────────────────
WATCH_GRACE_SEC     = 10      # ignore first 10 seconds in WATCH zone
RUNNING_SPEED_PX    = 25      # pixels per frame = running speed

# ── BEHAVIOR & TRACKING ARCHITECTURE (CUSTOS 2.6) ────────
ENABLE_EXPERIMENTAL_BEHAVIORS = False  # Strict guard: only VALIDATED behaviors affect production risk
TRACK_MATCH_IOU          = 0.30       # Minimum IoU for track association
TRACK_EXPIRATION_SEC     = 3.0        # Expire track after 3s unseen
DWELL_RADIUS_PX          = 50         # Spatial bounding radius for stationary dwell analysis

# ── CROUCHING (UNVALIDATED - DISABLED) ───────────────────
# Legacy bbox shrink heuristics are disabled. Future posture relies on PoseEngine.
CROUCH_SHRINK_RATIO  = 0.65
CROUCH_MIN_SECONDS   = 3.0

# ── NIGHT / DAY MODE ─────────────────────────────────────
# Schedule is fallback only. Manual key (G/D) always wins.
# Auto-detect: no activity for 30 min = switch to Guard Mode.
GUARD_MODE_START     = 22     # 10 PM  (24hr format)
GUARD_MODE_END       = 7      # 7 AM
NIGHT_SCORE_MULT     = 2.0    # all scores doubled in Guard Mode
AUTO_GUARD_IDLE_MIN  = 30     # minutes of no activity = auto Guard Mode

# ── RECORDING ────────────────────────────────────────────
RECORDING_ENABLED    = True
RECORDING_DIR        = 'data/recordings'
RECORDING_CHUNK_MIN  = 5      # save a new video file every 5 minutes
RECORDING_KEEP_HOURS = 24     # delete recordings older than this

# ── TAMPER DETECTION ─────────────────────────────────────
TAMPER_BUFFER_SEC    = 10     # rolling pre-tamper buffer length in seconds
TAMPER_DARK_THRESH   = 30     # brightness below this = possibly covered
TAMPER_STD_THRESH    = 10     # std deviation below this = very uniform = covered
TAMPER_CONFIRM_SEC   = 2.0    # must be covered this long before alerting

# ── DISPLAY ──────────────────────────────────────────────
SHOW_PREVIEW   = True
SNAPSHOT_DIR   = 'data/snapshots'

# ── YOLO CLASS IDs (COCO) ────────────────────────────────
CLASS_PERSON     = 0
CLASS_CAR        = 2
CLASS_MOTORCYCLE = 3
CLASS_HANDBAG    = 26
CLASS_SUITCASE   = 28

# ── PEOPLE INTELLIGENCE & FACE RECOGNITION ───────────────
FACE_DETECTOR_PATH       = 'data/weights/face_detection_yunet_2023mar.onnx'
FACE_RECOGNIZER_PATH     = 'data/weights/face_recognition_sface_2021dec.onnx'
FACE_MATCH_THRESHOLD     = 0.40    # SFace cosine similarity threshold (OpenCV benchmark default: 0.363)
FACE_CLUSTER_THRESHOLD   = 0.38    # Minimum similarity to cluster unknown face appearances
FACE_MIN_SIZE_PX         = 36      # Minimum face bounding box size in pixels
FACE_MIN_BLUR_VAR        = 35.0    # Minimum Laplacian variance for blur filter
FACE_MIN_CONFIDENCE      = 0.60    # YuNet face detection confidence threshold
FACE_CACHE_PER_TRACK     = True    # Cache resolved identity per active track for maximum performance
PEOPLE_DATA_DIR          = 'data/people'
PEOPLE_PROFILES_DIR      = 'data/people/profiles'
PEOPLE_CLUSTERS_DIR      = 'data/people/clusters'
PEOPLE_APPEARANCES_DIR   = 'data/people/appearances'

