# CUSTOS 2.7 — Edge AI Autonomous Threat Detection & Incident Intelligence Platform

[![Build Status](https://img.shields.io/badge/build-passing-brightgreen.svg)](https://github.com/)
[![Tests](https://img.shields.io/badge/tests-85%2F85%20passed-success.svg)](https://github.com/)
[![Python Version](https://img.shields.io/badge/python-3.8%20%7C%203.9%20%7C%203.10%20%7C%203.11-blue.svg)](https://python.org)
[![Framework](https://img.shields.io/badge/framework-Flask%20%7C%20Socket.IO%20%7C%20OpenCV%20%7C%20YOLOv8-orange.svg)](https://github.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**CUSTOS** is a production-grade, real-time Computer Vision & Edge AI security system designed for automated perimeter defense, zone intrusion detection, physical camera tamper protection, and verifiable video evidence generation.

Built on top of a zero-mock, SQLite-backed architecture, CUSTOS bridges low-latency frame processing with an end-to-end Incident Lifecycle Engine, providing security operators with an instant Command Center, synchronized Alert Center, and full Evidence Review Center.

---

## Table of Contents
1. [Key Capabilities](#key-capabilities)
2. [System Architecture](#system-architecture)
3. [Incident, Alert & Evidence Lifecycle](#incident-alert--evidence-lifecycle)
4. [Project Structure](#project-structure)
5. [Prerequisites & Requirements](#prerequisites--requirements)
6. [Installation & Setup](#installation--setup)
7. [Running the Application](#running-the-application)
8. [Web Dashboard & Navigation](#web-dashboard--navigation)
9. [REST API Documentation](#rest-api-documentation)
10. [Socket.IO Real-Time Events](#socketio-real-time-events)
11. [Configuration & Environment Variables](#configuration--environment-variables)
12. [Automated Testing Suite](#automated-testing-suite)
13. [Real Camera Acceptance Test Protocol](#real-camera-acceptance-test-protocol)
14. [Windows Startup & Auto-Run Configuration](#windows-startup--auto-run-configuration)

---

## Key Capabilities

### 1. High-Accuracy AI Perception & Multi-Object Tracking
- **YOLOv8 Vision Perception**: Detects persons, bags, and secondary objects with calibrated confidence filtering.
- **Persistent Multi-Object Tracking**: Trajectory smoothing and track ID maintenance across temporary micro-occlusions.
- **Dynamic Dual-Zone Monitoring**: Supports **HIGH SECURITY** (instant breach detection) and **OBSERVATION / WATCH** zones (dwell tracking and behavioral escalation).

### 2. Zero-Spam Incident Lifecycle State Machine
- **Deterministic Deduplication**:
  - Person/Zone Breach: `("zone", camera_id, subject_id, zone_name, "ZONE_BREACH")`
  - Camera Tamper: `("tamper", camera_id, "TAMPER")`
- **Zero Duplicate Alerts**: When a person stays inside a HIGH zone or a camera remains covered, CUSTOS maintains **ONE canonical Incident** and **ONE active Alert**, updating duration and timeline in real-time without alert spam.
- **Resilient Exit Grace Period**: Tracks leaving zones enter a configurable grace period ($3.0\text{--}5.0\,\text{s}$) to prevent track flicker from fracturing incidents.

### 3. 7-Condition Optical Tamper Detection & 15-Second Pre-Roll
- **Optical Conditions Detected**:
  1. Lens Obstruction (Laplacian blur variance drop)
  2. Lens Covering / Sudden Darkness (Mean intensity drop)
  3. Camera Shift / Displacement (Frame delta vs. background reference)
  4. Video Signal Lost / Disconnection
  5. Frame Freezing (Consecutive identical frames)
  6. Sudden Brightness / Flare
  7. Sudden Darkness Shock
- **Temporal State Confirmation**: Requires sustained abnormal states ($0.8\,\text{s}$) before confirming tamper, preventing transient glitches from triggering false alarms.
- **Rolling In-Memory Circular Frame Buffer**: Continuously maintains $\approx 15\,\text{seconds}$ of raw camera footage ($\approx 375\text{--}450$ frames).
- **Comprehensive Tamper MP4 Evidence**: Final tamper video contains:
  $$\text{15s Pre-Tamper Footage} + \text{Trigger Moment} + \text{Obstruction Duration} + \text{Recovery Footage}$$

### 4. Verifiable Media Verification Pipeline
- **Strict Post-Write Integrity**: Every JPEG snapshot and MP4 video is verified on disk (`file_size > 0`, `cv2.imread` dimensions valid, `cv2.VideoCapture` container readable).
- **Honest State Reporting**: Sets `snapshot_status='AVAILABLE'|'FAILED'` and `video_status='AVAILABLE'|'RECORDING'|'FAILED'`. No fake video players or broken placeholders.

---

## System Architecture

```
                               ┌────────────────────────┐
                               │  Camera VideoCapture   │
                               └───────────┬────────────┘
                                           │ (Single Frame Read)
                     ┌─────────────────────┴─────────────────────┐
                     ▼                                           ▼
         ┌───────────────────────┐                   ┌───────────────────────┐
         │ Rolling 15s Pre-Roll  │                   │ Temporal Tamper       │
         │ Circular Frame Buffer │                   │ Detection Engine      │
         └───────────┬───────────┘                   └───────────┬───────────┘
                     │                                           │
                     ▼                                           ▼
         ┌───────────────────────────────────────────────────────────┐
         │ YOLOv8 Perception + Multi-Object Tracker + Zone Monitor   │
         └─────────────────────────────┬─────────────────────────────┘
                                       │
                                       ▼
         ┌───────────────────────────────────────────────────────────┐
         │             Incident Lifecycle Manager                    │
         │  - Deterministic Key Deduplication                        │
         │  - Instant Trigger Snapshot Capture & Verification        │
         │  - MP4 Video Recording (Pre-Roll + Live + Post-Grace)     │
         │  - Continuous Dwell & Timeline Updates                    │
         └──────────────┬─────────────────────────────┬──────────────┘
                        │                             │
                        ▼                             ▼
         ┌────────────────────────────┐ ┌────────────────────────────┐
         │ SQLite ORM Persistence     │ │ Flask-SocketIO Realtime    │
         │ (models.py, database_mgr)  │ │ (alert_created, evidence)  │
         └──────────────┬─────────────┘ └─────────────┬──────────────┘
                        │                             │
                        ▼                             ▼
         ┌───────────────────────────────────────────────────────────┐
         │     CUSTOS Unified Web Interface (Port 5000)              │
         │  [Live Monitor]   [Alert Center]   [Evidence Center]      │
         └───────────────────────────────────────────────────────────┘
```

---

## Incident, Alert & Evidence Lifecycle

CUSTOS maintains a strict 1-to-1 canonical relationship:

$$\mathbf{Security\ Event} \longrightarrow \mathbf{Incident} \longrightarrow \begin{cases} \mathbf{Alert} & \text{(Severity, Explanations, Operator Resolution)} \\ \mathbf{Evidence} & \text{(Verified Snapshot, MP4 Video, Audit Timeline)} \end{cases}$$

### High-Zone Entry Lifecycle Flow
```
[ENTRY] Person enters HIGH Zone
   │
   ├── 1. Canonical Incident #101 created in SQLite
   ├── 2. Exactly ONE Alert created and emitted over Socket.IO
   ├── 3. Trigger Snapshot written to data/snapshots/incident_101_*.jpg and verified
   └── 4. Video Recording initialized with 15s pre-event buffer
   │
[DWELL] Person remains in HIGH Zone (2 minutes)
   │
   ├── 1. Incident #101 dwell time, score, and timeline updated periodically
   └── 2. ZERO additional alerts or database duplicate rows created
   │
[EXIT] Person exits HIGH Zone
   │
   ├── 1. Exit Grace Period (3.5 seconds) initiates
   ├── 2. Post-event frames captured
   ├── 3. MP4 Video encoded (data/snapshots/incident_101_*.mp4) & validated
   ├── 4. Incident status marked 'Closed' and Evidence marked 'COMPLETE'
   └── 5. Socket.IO emits 'incident_closed' and 'evidence_updated'
   │
[RE-ENTRY] Person enters HIGH Zone again
   │
   └── Brand NEW Incident #102 is created with fresh lifecycle
```

---

## Project Structure

```text
custos-stage2.5/
│
├── run_production.py          # Root entry point (Production server with logging & background workers)
├── run_server.py              # Lightweight server launcher
│
└── custos-stage2.5/           # Core Project Package
    ├── .env.example           # Template for environment variables (Telegram token, Chat ID, Secret Keys)
    ├── .gitignore             # Git ignore rules
    ├── requirements.txt       # Python dependencies (PyTorch, Ultralytics, Flask, OpenCV, SQLAlchemy, etc.)
    ├── DEPLOYMENT.md          # Production deployment guide
    ├── README.md              # Project quickstart and comprehensive documentation
    ├── run_production.py      # Production runner (initializes directories, cameras, workers, and SocketIO)
    ├── run_server.py          # Development server runner
    ├── run_debug.py           # Headless CLI debug runner (tests AI inference without Web UI)
    │
    ├── config/                # System Configuration
    │   └── settings.py        # Centralized thresholds, zone multipliers, model paths, alert intervals
    │
    ├── engine/                # Core AI & Computer Vision Intelligence
    │   ├── ai_engine.py           # High-level orchestrator connecting perception, tracking, and risk
    │   ├── perception_engine.py   # YOLOv8 object detection layer (persons, vehicles, bags)
    │   ├── detector.py            # Low-level model inference wrapper
    │   ├── tracker.py             # Multi-object bounding-box tracking across frames
    │   ├── tracking_engine.py     # Trajectory and velocity calculation
    │   ├── behavior_engine.py     # Suspicious behavior heuristics (crouching, loitering, fast movement)
    │   ├── behavior_analyzer.py   # Calibrated spatial & temporal movement analyzer
    │   ├── zone_monitor.py        # Zone boundary checking (HIGH vs WATCH zones) & IoU overlap
    │   ├── zone_selector.py       # GUI / interactive zone polygon definition
    │   ├── zone_store.py          # Zone persistence & configuration loading
    │   ├── risk_engine.py         # Real-time risk scoring engine (0-100 scale, decay, night multiplier)
    │   ├── risk_explainer.py      # Evidence-backed risk explainability generator
    │   ├── decision_engine.py     # Escalation logic (decides whether to alarm, snapshot, or notify)
    │   ├── response_engine.py     # Dispatches actions based on decisions
    │   ├── tamper_detector.py     # Lens occlusion, black screen, blur & optical tampering detection
    │   ├── frame_buffer.py        # Dedicated rolling in-memory 15-second circular pre-tamper buffer
    │   ├── media_recorder.py      # Frame capture, MP4 video encoding & disk validation
    │   ├── incident_lifecycle.py  # Canonical Incident Lifecycle Manager (entry, dwell, exit, tamper)
    │   ├── evidence_engine.py     # Snapshot generation & recording chunk manager
    │   ├── evidence_cache.py      # Pre-event circular buffer for instant evidence capture
    │   ├── evidence_deduplicator.py # Filters redundant alerts for the same incident
    │   ├── camera_manager.py      # Multi-camera thread pool manager (Webcam 0, RTSP feeds)
    │   ├── pipeline.py            # End-to-end frame processing loop
    │   ├── health_monitor.py      # System FPS, CPU/GPU, and camera health monitor
    │   ├── person_memory.py       # Short-term track memory across temporary occlusions
    │   ├── storage_queue.py       # Asynchronous SQLite storage queue (non-blocking DB writes)
    │   └── logger.py              # Structured application logger
    │
    ├── database/              # Persistence & ORM
    │   ├── models.py              # SQLAlchemy schemas (Incident, Alert, Evidence, ThreatEvent, User, Zone)
    │   └── database_manager.py    # Database connection manager, lifecycle updates & stats queries
    │
    ├── instance/              # Local Storage
    │   └── custos.db              # SQLite Database storing threat records, zones, and user accounts
    │
    ├── web/                   # Web Server & Real-time Telemetry
    │   ├── server.py              # Flask + Flask-SocketIO API, MJPEG video streaming, and auth routes
    │   ├── alert_manager.py       # Telegram Bot notifications & WebSocket browser toast dispatcher
    │   └── models.py              # API request/response schemas
    │
    ├── frontend/              # Command Center Web Dashboard
    │   ├── index.html             # Unified Command Center (Live Monitor, Alert Center, Evidence Center)
    │   └── app.js                 # Dashboard logic (Socket.IO client, zone canvas editor, audio alarms)
    │
    ├── data/                  # Assets & Binary Storage
    │   ├── weights/yolov8n.pt     # YOLOv8 neural network weights
    │   ├── snapshots/             # Verified JPG snapshots & MP4 video evidence
    │   └── recordings/            # Continuous recording chunks
    │
    ├── docs/                  # Project Documentation
    │   ├── Phase3_Planning.md     # Phase 3 feature breakdown & roadmap
    │   └── changelog.md           # Version release log
    │
    └── tests/                 # Automated Test Suite (85/85 Passing)
        ├── conftest.py            # Pytest fixtures & mock video feeds
        ├── test_ai_engine.py
        ├── test_alert_manager.py
        ├── test_alerts_api.py
        ├── test_behavior_analyzer.py
        ├── test_end_to_end_integration.py
        ├── test_evidence_api.py
        ├── test_evidence_intelligence.py
        ├── test_health_and_memory.py
        ├── test_incident_lifecycle.py
        ├── test_live_acceptance_pipeline.py
        ├── test_media_recorder.py
        ├── test_models.py
        ├── test_real_world_acceptance.py
        ├── test_real_world_simulation.py
        ├── test_risk_explainability.py
        ├── test_server_api.py
        ├── test_storage_queue.py
        ├── test_tamper_detector.py      # Optical condition checks & temporal state machine tests
        ├── test_tamper_lifecycle.py     # Pre-tamper rolling buffer + MP4 video recording test
        ├── test_vision_perception.py
        ├── test_vision_tracking.py
        ├── test_vision_zones.py
        └── test_zone_store.py
```

---

## Prerequisites & Requirements

- **Operating System**: Windows 10/11, Ubuntu 20.04+, or macOS
- **Python**: `3.8`, `3.9`, `3.10`, or `3.11`
- **Video Input**: Standard USB Webcam (`0`), Integrated Laptop Camera, or RTSP Network Stream (`rtsp://...`)
- **GPU (Optional)**: CUDA 11.8+ for accelerated YOLOv8 inference (CPU inference is fully supported by default)

---

## Installation & Setup

### 1. Clone or Extract the Repository
```bash
cd custos-stage2.5
```

### 2. Create and Activate Virtual Environment
**On Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
```

**On Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Verify YOLOv8 Weights
Ensure `data/weights/yolov8n.pt` is present (the engine will automatically download the lightweight Nano weights if missing).

---

## Running the Application

### Production Server (Recommended)
```bash
python run_production.py
```

### Development Server
```bash
python run_server.py
```

### Headless CLI Debug Mode (No Web UI)
```bash
python run_debug.py
```

After startup, open your browser and navigate to:
```
http://localhost:5000
```

### Default Authentication Credentials
| Role | Username | Password |
| :--- | :--- | :--- |
| **System Administrator** | `admin` | `admin123` |

---

## Web Dashboard & Navigation

The CUSTOS Web Dashboard features three integrated views:

### 1. Live Monitor
- **Real-Time Video Feed**: High-framerate MJPEG stream with dynamic bounding boxes, track IDs, and risk gauges.
- **Interactive Zone Drawer**: Click-and-drag to draw and configure **HIGH SECURITY** (Red) and **OBSERVATION** (Green) zones directly on the canvas.
- **Situation Briefing**: Real-time natural language threat assessment and active track summary.

### 2. Alert Center
- **Server-Side Filter & Search**: Query alerts by Severity (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`), Status (`Active`, `Resolved`), Camera ID, Zone Name, and Date Range.
- **Explainable Reasons & Recommended Action**: Clear breakdown of AI detection signals and recommended operator response.
- **Operator Resolution**: Single-click alert resolution updating SQLite and broadcasting real-time status updates via Socket.IO.

### 3. Evidence Center
- **Verified Media Preview**: View trigger JPEG snapshots and stream validated MP4 video clips directly in the browser.
- **Pre-Roll Playback**: Review pre-tamper and pre-intrusion footage recorded prior to alarm confirmation.
- **Chronological Audit Timeline**: Second-by-second breakdown of entry, dwell, escalation, recovery, and closure events.
- **Direct Export**: Download evidence packages for external reporting.

---

## REST API Documentation

All data endpoints require session authentication (or provide standard JSON error envelopes `{ "status": "error", "message": "..." }`).

### Authentication
- `POST /login` — Authenticate operator (`username`, `password`).
- `GET /logout` — Terminate session.
- `GET /api/auth/status` — Returns current authentication status and user metadata.

### Alert Center Endpoints
- `GET /api/alerts?page=1&limit=10&status=Active&severity=CRITICAL&search=zone` — Paginated, searchable alert records.
- `GET /api/alerts/stats` — Real-time aggregate counts (`total_alerts`, `active_alerts`, `critical_alerts`, `today_alerts`, `resolved_alerts`).
- `GET /api/alerts/<id>` — Retrieve single alert detail with linked incident metadata.
- `POST /api/alerts/<id>/resolve` — Mark alert as resolved (`resolved_by`, `resolution_notes`).

### Evidence Center Endpoints
- `GET /api/evidence?page=1&limit=10&media_type=ALL&search=tamper` — Paginated evidence records.
- `GET /api/evidence/stats` — Media stats (`total_records`, `total_snapshots`, `total_clips`, `tamper_count`).
- `GET /api/evidence/<id>` — Complete evidence package with chronological timeline.
- `GET /api/evidence/<id>/media/<type>` — Securely serves validated JPEG snapshots or MP4 videos (`image/jpeg` or `video/mp4`).
- `POST /api/evidence/<id>/export` — Generates a downloadable JSON evidence export.

### Zones & Live Ingestion Endpoints
- `POST /api/zones` — Persist active zone coordinates and types (`[{ "x1": ..., "y1": ..., "x2": ..., "y2": ..., "type": "HIGH" }]`).
- `POST /api/zones/clear` — Clear all defined zones for a camera.
- `POST /api/monitoring/toggle` — Enable or disable active AI perception and risk scoring.
- `GET /video_feed` — Stream live annotated MJPEG video.

---

## Socket.IO Real-Time Events

The backend emits structured, deduplicated events over WebSockets to synchronize the UI without page reloads:

| Event Name | Direction | Payload | Description |
| :--- | :--- | :--- | :--- |
| `alert_created` | Server $\rightarrow$ Client | Alert Dict | Emitted when a new canonical incident creates an active alert |
| `alert_updated` | Server $\rightarrow$ Client | Alert Dict | Emitted when dwell duration or score updates |
| `alert_resolved` | Server $\rightarrow$ Client | `{ "incident_id": ... }` | Emitted when an operator resolves an alert |
| `evidence_created` | Server $\rightarrow$ Client | Evidence Dict | Emitted upon trigger snapshot generation |
| `evidence_updated` | Server $\rightarrow$ Client | Evidence Dict | Emitted when MP4 video is finalized and validated |
| `tamper_started` | Server $\rightarrow$ Client | `{ "camera_id": 0, "reasons": [...] }` | Emitted when optical tampering is confirmed |
| `tamper_resolved` | Server $\rightarrow$ Client | `{ "camera_id": 0, "incident_id": ... }` | Emitted when camera view is restored |
| `incident_closed` | Server $\rightarrow$ Client | `{ "incident_id": ..., "camera_id": 0 }` | Emitted when exit grace period concludes |

---

## Configuration & Environment Variables

System parameters are defined in [`config/settings.py`](file:///c:/Users/VARUN%20THEJ/Downloads/custos-folder/custos-stage2.5/custos-stage2.5/config/settings.py) and can be overridden via `.env`:

```ini
# Camera & Video Ingestion
CAMERA_SOURCE=0
CAMERA_WARMUP_FRAMES=10
CAMERA_TARGET_FPS=30

# Pre-Tamper & Rolling Buffer
PRE_TAMPER_SECONDS=15.0
TAMPER_CONFIRM_SECONDS=0.8
TAMPER_RECOVERY_SECONDS=3.0

# Incident Lifecycle
INCIDENT_EXIT_GRACE_SECONDS=3.5
SNAPSHOT_DIR=data/snapshots

# Risk Engine Weights
RISK_THRESHOLD_HIGH=70
RISK_THRESHOLD_CRITICAL=85
NIGHT_MODE_MULTIPLIER=1.3

# Web Server
PORT=5000
SECRET_KEY=custos_production_secret_key_2026
```

---

## Automated Testing Suite

CUSTOS includes an automated test suite covering unit tests, API integration tests, and full end-to-end lifecycle verification.

### Run All Tests
```bash
python -m pytest
```

### Run Specific Test Modules
```bash
# Tamper lifecycle and 15s pre-roll validation
python -m pytest tests/test_tamper_lifecycle.py -s

# HIGH Zone breach lifecycle and deduplication
python -m pytest tests/test_incident_lifecycle.py -s

# End-to-end live pipeline acceptance
python -m pytest tests/test_live_acceptance_pipeline.py -s

# Media recorder snapshot & MP4 disk validation
python -m pytest tests/test_media_recorder.py -s
```

### Test Suite Summary (85 / 85 Passing)
```
============================= 85 passed in 17.68s =============================
tests\test_ai_engine.py ..................................               [ 18%]
tests\test_end_to_end_integration.py ....................               [ 34%]
tests\test_incident_lifecycle.py .                                       [ 41%]
tests\test_live_acceptance_pipeline.py .                                 [ 42%]
tests\test_media_recorder.py ...                                         [ 45%]
tests\test_tamper_detector.py ...                                        [ 84%]
tests\test_tamper_lifecycle.py .                                         [ 85%]
tests\test_vision_perception.py ....                                     [ 90%]
tests\test_vision_tracking.py ....                                       [ 95%]
tests\test_vision_zones.py ...                                           [ 98%]
tests\test_zone_store.py .                                               [100%]
```

---

## Real Camera Acceptance Test Protocol

Follow this procedure to validate the physical camera pipeline live:

### 1. Zone Intrusion & Deduplication Verification
1. Launch CUSTOS: `python run_production.py`
2. Open `http://localhost:5000` and log in with `admin` / `admin123`.
3. In **Live Monitor**, draw a **HIGH SECURITY** zone across the middle of your camera view.
4. Step into the HIGH zone:
   - Verify **exactly ONE Alert** appears in Alert Center.
   - Verify trigger snapshot is recorded.
5. Remain standing inside the HIGH zone for 30–60 seconds:
   - Verify **0 duplicate alerts** are created.
   - Verify dwell duration and live score update continuously.
6. Step out of the HIGH zone:
   - Verify the incident closes after the 3.5-second grace period.
   - Go to **Evidence Center** and play the finalized MP4 video clip.

### 2. Tamper Detection & Pre-Tamper Footage Verification
1. Let the camera run uncovered for at least $20\,\text{seconds}$ so the in-memory circular buffer fills.
2. Physically cover the camera lens with your hand or a dark cloth.
3. Observe:
   - Tamper confirmation triggers after $0.8\,\text{s}$.
   - **Exactly ONE Tamper Alert** is created in Alert Center.
4. Keep the camera covered for $5\text{--}10\,\text{seconds}$ (0 duplicate alerts generated).
5. Uncover the camera:
   - Recovery detected after continuous healthy frames.
   - Incident closes and MP4 video is finalized.
6. Open **Evidence Center** $\rightarrow$ Tamper Record:
   - Play the MP4 video: Confirm it clearly shows **10–15 seconds BEFORE the camera was covered**, the full tamper event, and the camera recovery.

---

## Windows Startup & Auto-Run Configuration

To configure CUSTOS as a continuous Windows background service starting automatically at system boot:

1. Press `Win + R`, type `taskschd.msc`, and press **Enter**.
2. Click **Create Task** in the right Actions panel.
3. **General Tab**:
   - Name: `CUSTOS 2.7 AI Surveillance`
   - Select **"Run whether user is logged on or not"**
   - Check **"Run with highest privileges"**
4. **Triggers Tab**:
   - Click **New...** $\rightarrow$ Set *Begin the task* to **"At startup"**.
5. **Actions Tab**:
   - Click **New...** $\rightarrow$ Action: **"Start a program"**.
   - Program: `cmd.exe`
   - Arguments: `/c "cd /d C:\Path\To\custos-stage2.5 && venv\Scripts\python.exe run_production.py"`
6. **Conditions Tab**:
   - Uncheck *"Stop if the computer switches to battery power"*.
7. Click **OK** and provide your Windows credentials.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
