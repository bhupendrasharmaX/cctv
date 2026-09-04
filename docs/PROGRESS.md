# SENTINEL — Project Progress & Operational Log

> Single source of truth for Sentinel: Gujarat Police Unified CCTV & Video Analytics Platform.
> Updated at the conclusion of every phase.

---

## Overall Architecture Status
- **Model 1 (Mandatory):** Central CCTV Registry + GIS Foundation
- **Model 2 (Primary):** Unified Viewing + Non-Invasive Selective Analytics (ANPR, Tracking, Alerts)
- **Constraint Compliance:**
  - Non-invasive ingestion only (never publish back to camera/VMS)
  - Strict TCP transport for RTSP
  - PTS/stream timestamp prioritization over wall-clock
  - Laptop-scale compute throttling (frame sampling, selective processing)
  - PostGIS geospatial representations (prepared for Phase 3/4)
  - Zero fabricated integrations (`// MOCK` / `// REPRESENTATIVE` explicitly labeled)

---

## Phase Roadmap Status

| Phase | Description | Status | Notes |
|---|---|---|---|
| **Phase 1** | **Feed verification (`/api/ingest`, RTSP TCP, PTS, reconnect)** | **IN PROGRESS** | `feed_check.py` implemented; awaiting host credentials/stream URL |
| Phase 2 | Registry API (FastAPI endpoints to store/list metadata) | PENDING | Blocked on Phase 1 validation |
| Phase 3 | Camera registry + bulk import (Postgres/PostGIS schema) | PENDING | |
| Phase 4 | GIS map (React + Leaflet + PostGIS markers/filters) | PENDING | |
| Phase 5 | RTSP ingestion service (controlled subset, health/reconnect) | PENDING | |
| Phase 6 | Unified multi-camera viewer (grid view, WHEP/HLS preview) | PENDING | |
| Phase 7 | Vehicle detection (YOLOv8 sampled frames) | PENDING | |
| Phase 8 | ANPR (plate detector + OCR, confidence scoring) | PENDING | |
| Phase 9 | Detection metadata storage (`vehicle_detections`) | PENDING | |
| Phase 10 | Vehicle search by plate (API + UI) | PENDING | |
| Phase 11 | Cross-camera timeline (chronological detections) | PENDING | |
| Phase 12 | GIS route reconstruction (spatial timeline on map) | PENDING | |
| Phase 13 | Mock watchlist (stolen/wanted/blacklisted plates) | PENDING | |
| Phase 14 | Watchlist matching (detection vs watchlist) | PENDING | |
| Phase 15 | Real-time alerts (UI surfacing with snapshots) | PENDING | |
| Phase 16 | Camera health monitoring (online/offline, reconnect count) | PENDING | |
| Phase 17 | Integrated command dashboard (control-room dark theme) | PENDING | |
| Phase 18 | Real government feed testing | PENDING | |
| Phase 19 | Performance & frame sampling pass | PENDING | |
| Phase 20 | Deliverables (PPT, HLD, Architecture diagrams, reports) | PENDING | |

---

## Known Issues & Blockers
- **Awaiting Gateway `<host>`:** `http://localhost/api/ingest` returned `Connection Refused`. Waiting for user to provide the test environment host IP/port or stream URL.

---

## Key Decisions
1. `feed_check.py` enforces `rtsp_transport;tcp` via FFmpeg capture options.
2. Reconnect loop follows exponential backoff: $t_{next} = \min(t \times 2, 30.0s)$ starting at 2.0s.
3. Stream timing relies strictly on PTS (`cv2.CAP_PROP_POS_MSEC`), not frame arrival wall clock.
