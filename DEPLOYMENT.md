# Custos - Deployment & Packaging Guide

This document outlines the steps required to package the Custos AI Surveillance System into a standalone Windows Desktop Application (`.exe`), manage updates, and handle user authentication.

## 1. Authentication (Google OAuth)
Custos now supports **Sign in with Google** alongside the default local admin login.

### Setup Instructions:
1. Ensure your Google Cloud Console project is set up with an **OAuth Client ID** (Web Application).
2. The authorized redirect URIs must include: `http://localhost:5000/auth/callback`
3. The Client ID and Client Secret are stored securely in the local `.env` file.
4. When users launch the app, they will be greeted with the login screen where they can authenticate via their Google Account.

*Note: For local admin access without Google, the default credentials are `admin` / `Varunthej@8630` (configurable in the `.env` file).*

---

## 2. The Auto-Updater System
Custos features an **Over-The-Air (OTA) Auto-Updater**. 

### How it works:
1. Upon startup, `run_server.py` triggers the `updater.py` module.
2. The updater checks a remote `version.json` file (configurable via `UPDATE_URL` in `config/settings.py`).
3. If the remote version is higher than the local `APP_VERSION`, a native Windows prompt alerts the user.
4. If accepted, the app silently downloads the `.zip` update, extracts it, closes the active Python process, applies the new files via a batch script, and restarts itself instantly.

### How to push an update to users:
1. Make your code changes locally.
2. Zip the updated files into `update.zip`.
3. Host `update.zip` and a `version.json` file (e.g., on GitHub Releases).
4. Update your hosted `version.json` to reflect the new version number and download URL.
5. The next time users launch Custos, they will be prompted to install it.

---

## 3. Packaging into a Standalone `.exe`
To distribute Custos to users who do not have Python installed, you must package the application using **PyInstaller**. 

We use the `--onedir` strategy. Unlike `--onefile` (which takes 60 seconds to silently extract massive AI libraries like PyTorch every time the app opens), `--onedir` creates a folder that launches instantly.

### Build Instructions:
1. Open your terminal in the project folder.
2. Ensure your virtual environment is active (if you used `setup.bat`, it should be).
3. Run the automated build script:
   ```cmd
   python build.py
   ```
4. The script will:
   - Install `pyinstaller`.
   - Download the YOLOv8 weights (if missing).
   - Package the Python backend, Flask UI, config files, and YOLO models.

### Output:
Once the build completes (usually 3-5 minutes), you will see a new `dist` folder.
Navigate to: **`dist/Custos/`**
Inside this folder, you will find `Custos.exe`. Double-clicking this will launch the entire application seamlessly.

---

## 4. Distribution Guide
To share Custos with clients or other laptops:

1. Right-click the **`dist/Custos`** folder.
2. Select **Send to > Compressed (zipped) folder**.
3. Share this `.zip` file with your users (via Google Drive, USB, etc.).
4. Instruct the user to **unzip** the folder on their desktop.
5. They simply double-click `Custos.exe` to launch the security dashboard. No Python installation, terminal commands, or setup required!
