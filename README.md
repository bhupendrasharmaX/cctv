# Gujarat Police — Unified CCTV & Video Analytics Platform (SENTINEL)

A unified video surveillance, GIS tracking, and automated number plate recognition (ANPR) platform developed for the Gujarat Police CCTV command ecosystem.

## 🚀 Overview

The platform bridges **Model 1** (Central CCTV Registry & GIS Foundation) and **Model 2** (Unified Viewing, Cross-Camera Vehicle Tracking, and Non-Invasive Real-Time Analytics) into an intuitive, high-performance command center dashboard.

### Core Capabilities
- **Multi-Camera Unified Grid:** Flexible `1x1`, `2x2`, and `3x3` viewing modes across junction cameras with synchronized stream management.
- **AI Vehicle Detection & ANPR:** YOLOv8-powered vehicle localization and EasyOCR license plate recognition with confidence scoring.
- **Cross-Camera Vehicle Journey Reconstruction:** Chronological trajectory tracking, spatial timeline reconstruction, and route distance calculation on interactive Leaflet GIS maps.
- **Police Watchlist & Alert Engine:** Instant visual and audio alerting upon detecting blacklisted, stolen, or wanted vehicles with full evidence docket export.
- **Non-Invasive Ingestion:** Respects government CCTV infrastructure constraints by consuming RTSP feeds over TCP without publishing back to source cameras.

---

## 🛠 Tech Stack

- **Backend:** FastAPI, Python 3.10+, SQLAlchemy (SQLite/PostgreSQL)
- **Computer Vision & AI:** Ultralytics YOLOv8, EasyOCR, OpenCV, PyTorch
- **Real-time Communication:** WebSockets for instant multi-client alerts and detection telemetry
- **Frontend & GIS:** Vanilla JavaScript, HTML5/CSS3 (Control Room Dark UI), Leaflet.js
- **Streaming:** RTSP over TCP, PTS timestamp preservation, intelligent frame sampling

---

## 📂 Project Structure

```
├── ai_engine/               # YOLOv8 & OCR detection pipeline and stream workers
│   ├── multi_stream_runner.py
│   ├── plate_recognizer.py
│   ├── stream_worker.py
│   └── vehicle_detector.py
├── backend/                 # FastAPI REST & WebSocket server
│   └── app/
│       ├── config.py
│       ├── database.py
│       ├── main.py
│       ├── models.py
│       ├── routers/         # API endpoints (registry, search, watchlist, alerts)
│       └── services/        # Catalogue sync, alert engine, route tracer
├── data/                    # Database, watchlist seeds, and snapshot storage
│   └── seed_watchlist.json
├── docs/                    # Architecture logs and documentation
│   └── PROGRESS.md
├── frontend/                # Command center web dashboard
│   ├── css/
│   │   └── dashboard.css
│   ├── js/
│   │   ├── alerts.js
│   │   ├── api.js
│   │   ├── map.js
│   │   ├── tracker.js
│   │   └── viewer.js
│   └── index.html
├── scripts/                 # Ingest and stream test utilities
│   ├── simulate_feed.py
│   ├── test_ingest.py
│   └── test_stream.py
├── requirements.txt
├── run.py                   # Platform entry point
└── yolov8n.pt               # Base YOLOv8 weights
```

---

## ⚡ Quickstart Guide

### 1. Prerequisites
- Python 3.10 or higher
- Git

### 2. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/mohittchoudhary/cctv.git
cd cctv
pip install -r requirements.txt
```

Dependencies are layered, because the AI stack is large and only the stream
workers need it:

| File | Contents | Use when |
|---|---|---|
| `requirements-core.txt` | API, dashboard, registry, tracking | Running the command platform without live ANPR |
| `requirements.txt` | core + YOLOv8 + EasyOCR (pulls torch) | Full deployment with AI analytics |
| `requirements-dev.txt` | core + pytest | Running the test suite |

YOLO weights are **not** committed; ultralytics downloads `yolov8n.pt` on first
use. Detector and recognizer imports are lazy, so the API, dashboard and tests
all run without torch installed.

### 3. Launch the Server
```bash
python run.py
```
Or specify a custom host/port:
```bash
python run.py --host 0.0.0.0 --port 8000
```

### 4. Access the Dashboard
- **Command Dashboard:** [http://localhost:8000](http://localhost:8000)
- **Interactive Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)

### 5. Load a Demo Journey
With no government gateway reachable, the platform seeds a representative Gujarat camera
catalogue. To also populate a cross-camera journey to trace:
```bash
python run.py --simulate-demo
```
Then search `GJ01AB1234` in the investigation panel.

### 6. Run the Tests
```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

---

## ⚙️ Configuration

All settings are environment variables with working defaults:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///data/cctv.db` | Datastore. SQLite runs in WAL mode with a busy timeout. |
| `GOVT_GATEWAY_HOST` | `localhost` | Gateway host for `/api/ingest` and stream URLs. |
| `AI_FRAME_SKIP` | `8` | Process 1 frame in N (~3 FPS on a 25 FPS stream). |
| `ALERT_COOLDOWN_SECONDS` | `120` | Repeat sightings of one plate at one camera fold into the existing alert. |
| `HOP_GROUPING_WINDOW_SECONDS` | `120` | Sightings at one camera inside this window are a single visit. |
| `IMPLAUSIBLE_SPEED_KMH` | `160` | Inter-camera speeds above this are flagged for manual verification. |
| `CORS_ALLOW_ORIGINS` | *(empty)* | Comma-separated extra origins. Same-origin needs no entry. |
| `SENTINEL_API_TOKEN` | *(empty)* | Shared platform token. Unset = **open API**. |
| `SNAPSHOT_RETENTION_DAYS` | `30` | Age limit for evidence crops. `0` disables. |
| `SNAPSHOT_MAX_FILES` | `20000` | Ceiling on stored crops, oldest pruned first. `0` disables. |

---

## 🔒 Access Control

Set `SENTINEL_API_TOKEN` and every `/api` route except `/api/health` requires it, as does the
alert WebSocket. The dashboard prompts for the token once and holds it for the browser session.

```bash
SENTINEL_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" python run.py
```

```bash
curl -H "Authorization: Bearer $SENTINEL_API_TOKEN" http://localhost:8000/api/cameras
```

Leaving it unset keeps the API open and logs a warning at startup, which is fine for local
development and nothing else.

**This is a stopgap, not an identity system.** A single shared token gives no per-officer audit
trail and no revocation short of rotating it. Real deployment needs proper identity — tracked in
`docs/PROGRESS.md` along with the other known gaps.
