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
  - Laptop-scale compute throttling (frame sampling, selective processing)
  - PostGIS geospatial representations (prepared, not yet adopted — see Known Gaps)
  - Zero fabricated integrations (representative data is labelled as such in the UI)

---

## Phase Roadmap Status

| Phase | Description | Status | Notes |
|---|---|---|---|
| **Phase 1** | Feed verification (`/api/ingest`, RTSP TCP, PTS, reconnect) | **DONE** | `feed_check.py`; still unvalidated against a real government feed |
| **Phase 2** | Registry API (FastAPI endpoints to store/list metadata) | **DONE** | `/api/cameras`, filters, facets, GeoJSON |
| Phase 3 | Camera registry + bulk import (Postgres/PostGIS schema) | PARTIAL | SQLAlchemy models run on SQLite; no PostGIS, no migrations |
| **Phase 4** | GIS map (Leaflet markers/filters) | **DONE** | Vanilla JS + Leaflet, not React |
| **Phase 5** | RTSP ingestion service (health/reconnect) | **DONE** | `StreamWorker` with interruptible exponential backoff |
| **Phase 6** | Unified multi-camera viewer (grid view, WHEP preview) | **DONE** | 1×1/2×2/3×3 with paging; falls back to a labelled representative feed |
| **Phase 7** | Vehicle detection (YOLOv8 sampled frames) | **DONE** | `VehicleDetector`, frame-skip throttled |
| Phase 8 | ANPR (plate detector + OCR, confidence scoring) | PARTIAL | **No plate-localisation stage** — OCR runs on the whole vehicle crop |
| **Phase 9** | Detection metadata storage | **DONE** | `detections` table, composite plate+time index |
| **Phase 10** | Vehicle search by plate (API + UI) | **DONE** | |
| **Phase 11** | Cross-camera timeline | **DONE** | Time-windowed hop grouping |
| **Phase 12** | GIS route reconstruction | **DONE** | Per-leg polylines; implausible legs drawn separately |
| **Phase 13** | Mock watchlist | **DONE** | `data/seed_watchlist.json`, labelled representative in the UI |
| **Phase 14** | Watchlist matching | **DONE** | Exact-first, then single-edit fuzzy at REVIEW severity |
| **Phase 15** | Real-time alerts (UI surfacing with snapshots) | **DONE** | WebSocket fan-out; covered by `tests/test_live_alert_pipeline.py` |
| **Phase 16** | Camera health monitoring | **PARTIAL** | Worker liveness and reconnect counts are exposed; camera reachability is still whatever the catalogue reported |
| **Phase 17** | Integrated command dashboard | **DONE** | Registry filters, live sighting ticker, alert triage, print-ready docket |
| Phase 18 | Real government feed testing | PENDING | Blocked on gateway host |
| Phase 19 | Performance & frame sampling pass | PENDING | |
| Phase 20 | Deliverables (PPT, HLD, architecture diagrams) | PENDING | |

---

## Known Gaps & Blockers

- **Awaiting gateway `<host>`:** `http://localhost/api/ingest` returns connection refused. The
  platform falls back to the offline Gujarat seed catalogue until a host is supplied.
- **No authentication.** Every endpoint is open: the camera registry (including RTSP URLs), the
  watchlist, and worker control. This must be closed before the platform is exposed beyond
  localhost.
- **No plate localisation.** EasyOCR runs on the full vehicle bounding box, so bumper stickers and
  dealer decals compete with the plate. This is the single largest available accuracy win.
- **PTS is recorded but not used for analytics.** `CAP_PROP_POS_MSEC` is a per-connection offset
  that resets to zero on reconnect, so it is not comparable across cameras as stored. Route
  timings therefore use `capture_timestamp`. Making PTS authoritative needs an absolute clock
  reference from the gateway.
- **SQLite, no migrations.** WAL and a busy timeout are enabled, which is enough for a handful of
  workers, but schema changes still require dropping `data/cctv.db`. Postgres + Alembic before
  any multi-user deployment.
- **Snapshots grow without bound.** No retention policy on `data/snapshots/`.

---

## Key Decisions

1. `feed_check.py` enforces `rtsp_transport;tcp` via FFmpeg capture options.
2. Reconnect follows exponential backoff, 2s doubling to a 30s cap, interruptible on shutdown.
3. **All timestamps are stored as naive UTC and serialized with an explicit `+00:00` offset.**
   The dashboard renders them in `Asia/Kolkata`. Sending naive timestamps made browsers parse
   them as local time, shifting every entry on the evidence docket by 5h30m.
4. **Real-time broadcasts are scheduled onto the server event loop explicitly.** Detections
   originate off-loop (threadpool endpoints, stream workers, scripts), so the loop handle is
   captured in the FastAPI lifespan and used with `run_coroutine_threadsafe`.
5. **Fuzzy plate matches are surfaced as REVIEW, never CRITICAL**, and always display the plate
   the camera actually read alongside the watchlist entry it resembles.
6. **Physically impossible inter-camera speeds are flagged, not rendered as fact** — they are the
   signature of a misread or cloned plate.
7. Watchlist alerts have a per-(plate, camera) cooldown; repeat sightings increment a counter on
   the existing alert instead of raising new ones.

---

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

Covers plate matching and alert suppression (`test_alert_engine.py`), route reconstruction and
timestamp handling (`test_route_tracer.py`), and the end-to-end WebSocket alert path
(`test_live_alert_pipeline.py`).
