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
