# CUSTOS Stage 2.8 — Deployment & Production Guide

This document outlines the deployment, security hardening, and operational guidelines for running CUSTOS Stage 2.8 in edge and on-premise production environments.

---

## 1. Production Runtime Architecture

CUSTOS Stage 2.8 uses a hybrid threaded architecture:
- **Web Application & API**: Served via `Waitress` WSGI production server (`run_production.py`) or Flask-SocketIO threaded runner (`run_server.py`).
- **Computer Vision Pipelines**: Multi-camera threaded pipelines running OpenCV + YOLOv8 + YuNet + SFace.
- **Asynchronous Storage**: Background queue worker processing snapshots and video buffer clips without blocking the main CV threads.
- **Database**: SQLite with Write-Ahead Logging (WAL) and 30s busy timeout, or remote PostgreSQL via `CUSTOS_DATABASE_URI`.

---

## 2. Environment Configuration (`.env`)

Copy `.env.example` to `.env` in the project root and configure the required settings:

```ini
# Application Secrets
CUSTOS_SECRET=your_secure_random_secret_here
CUSTOS_ADMIN_PASSWORD=your_initial_admin_password

# Database Configuration (Defaults to instance/custos.db)
# CUSTOS_DATABASE_URI=sqlite:///instance/custos.db
# CUSTOS_DATABASE_URI=postgresql://user:pass@localhost:5432/custos

# Socket.IO & CORS (Comma-separated origins, or * for all)
CUSTOS_CORS_ORIGINS=*

# Telegram Incident Dispatch (Optional)
TELEGRAM_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Google OAuth Single Sign-On (Optional)
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
```

---

## 3. Starting the Production Server

### Windows Service or Scheduled Task
To launch the production server using Waitress:

```powershell
python run_production.py
```

Or using the standard development server:

```powershell
python run_server.py
```

### Windows Startup Batch Files
- `setup.bat`: Creates virtual environment and installs dependencies.
- `start.bat`: Starts the CUSTOS server.
- `stop.bat`: Stops background server processes.

---

## 4. Verification & Health Checks

Verify that the system is running and healthy:
1. Access the web dashboard at `http://localhost:5000`
2. Check system status API at `GET /state`
3. Check camera listings at `GET /list_cameras`
4. Inspect application logs in `logs/app.log`

