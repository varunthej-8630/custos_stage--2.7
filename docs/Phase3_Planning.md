# CUSTOS — Phase 3 Progress Report
**Project:** Custos Digital Perimeter — Asset Interaction Anomaly Detection  
**Phase:** 3 — Dashboard Security, Tunneling & Website Integration  
**Date:** March 11, 2026

---

## Overview
Phase 3 focused on securing the CUSTOS dashboard with login authentication, setting up public access via Cloudflare Tunnel, and integrating a Live Demo request button into the Custos marketing website.

---

## 1. Login Authentication (Username & Password)

### What was done
Added a simple login system to protect the CUSTOS dashboard from unauthorized access.

### Changes made to `web_server.py`
- Updated Flask imports to include `session`, `redirect`, `url_for`, `request`
- Added `app.secret_key = 'custos_secret_2026'` for session management
- Added `/login` route (GET + POST) with username/password validation
- Added `/logout` route that clears session and redirects to login
- Protected the `/` dashboard route — redirects to `/login` if not authenticated
- Added `LOGIN_HTML` — a styled login page matching CUSTOS dark theme

### Credentials
| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | `Varunthej@8630` |

### Changes made to `dashboard/index.html`
- Added **Logout** button in the topbar (top right, next to YOLOv8 chip)
- Clicking logout hits `/logout` route and returns to login page

---

## 2. Telegram Alerts Fixed

### Problem
Terminal was showing:
```
[ALERTS] No Telegram token — terminal alerts only.
```

### Fix
Updated `config.py` with correct values:
- `TELEGRAM_BOT_TOKEN` — obtained from @BotFather on Telegram
- `TELEGRAM_CHAT_ID` — obtained from @userinfobot on Telegram

### Result
Terminal now shows:
```
[ALERTS] Telegram bot ready.
```
Alerts fire correctly to Telegram when risk threshold is crossed.

---

## 3. ngrok Disabled

### Problem
ngrok free plan bandwidth was exceeded (`ERR_NGROK_725`) due to heavy MJPEG video stream usage.

### Fix
Disabled ngrok tunnel in `web_server.py` by changing `try:` to `if False:` in the tunnel block.

### Result
Server runs cleanly without attempting ngrok connection. Dashboard accessible locally at `http://localhost:5000`.

---

## 4. Cloudflare Tunnel Setup

### Why Cloudflare
- ngrok free plan: 1GB/month bandwidth limit (too low for video streaming)
- Cloudflare Tunnel: no bandwidth limit, completely free, no account required

### Installation
Downloaded `cloudflared-windows-amd64.exe` directly from GitHub releases into the project folder (no installer needed).

### How to run
**Terminal 1 — Start the server:**
```powershell
cd D:\custos-digital-perimeter--p2-main\custos-digital-perimeter--p2-main
python web_server.py
```

**Terminal 2 — Start the tunnel:**
```powershell
cd D:\custos-digital-perimeter--p2-main\custos-digital-perimeter--p2-main
.\cloudflared-windows-amd64.exe tunnel --url http://localhost:5000
```

### Output
```
Your quick Tunnel has been created! Visit it at:
https://[random-name].trycloudflare.com
```

### Important notes
- URL changes every time cloudflared is restarted
- No account or auth token required
- No bandwidth limits
- Tunnel only works while both terminals are running

---

## 5. Website Integration (custos-xi.vercel.app)

### What was done
Added a **"▶ Request Live Demo"** button to the Hero section of the Custos marketing website.

### File changed
`src/sections/Hero.jsx`

### Button behavior
- Clicking opens WhatsApp with pre-filled message:  
  *"Hi, I'd like to request a live demo of Custos!"*
- Sent to: `+91 74166 36417`

### Live Demo workflow
| Step | Who | Action |
|------|-----|--------|
| 1 | Visitor | Clicks "Request Live Demo" on website |
| 2 | Visitor | Sends WhatsApp message to Varun |
| 3 | Varun | Starts `python web_server.py` |
| 4 | Varun | Starts cloudflared tunnel |
| 5 | Varun | Copies Cloudflare URL and sends to visitor |
| 6 | Visitor | Opens URL, logs in with `admin/custos123` |
| 7 | Visitor | Views live CUSTOS dashboard from anywhere |

### Website performance optimizations
Reduced 3D animation load in `Hero.jsx`:
- Particle count: `4000` → `1000`
- Stars count: `3000` → `1000`
- Blob geometry: `128x128` → `32x32`
- Inner core geometry: `64x64` → `32x32`

---

## 6. Files Modified in Phase 3

| File | Changes |
|------|---------|
| `web_server.py` | Login/logout routes, session auth, LOGIN_HTML, ngrok disabled |
| `dashboard/index.html` | Logout button added to topbar |
| `config.py` | Telegram token and chat ID updated |
| `src/sections/Hero.jsx` | Live Demo button added, performance optimized |

---

## 7. Current System Architecture

```
Browser (Visitor)
     ↓
Cloudflare Tunnel (trycloudflare.com)
     ↓
Login Page (/login)
     ↓ [admin/custos123]
CUSTOS Dashboard (Flask + SocketIO)
     ↓
Detection Thread (YOLOv8 + Camera)
     ↓
Risk Engine → Alert Manager → Telegram
```

---

## Phase 3 Summary

| Feature | Status |
|---------|--------|
| Login page | ✅ Done |
| Logout button | ✅ Done |
| Telegram alerts | ✅ Fixed |
| ngrok disabled | ✅ Done |
| Cloudflare tunnel | ✅ Working |
| Website Live Demo button | ✅ Done |
| WhatsApp request flow | ✅ Done |
| Performance optimization | ✅ Done |

---

*CUSTOS — Asset Interaction Anomaly Detection*  
*Built by Parimi Varun Thej*




PS C:\Users\varun\OneDrive\Desktop\custos-digital-perimeter--p3-main> $env:PATH += ";C:\Users\varun\AppData\Local\Programs\Python\Python314"

PS C:\Users\varun\OneDrive\Desktop\custos-digital-perimeter--p3-main> C:/Users/varun/AppData/Local/Programs/Python/Python314/python.exe web_server.py