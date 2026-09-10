# SENTINEL — Gujarat Police Unified CCTV & Video Analytics Platform

A video surveillance, GIS tracking and automatic number plate recognition (ANPR) platform for the
Gujarat Police CCTV command ecosystem. It consumes existing government camera feeds without
writing anything back to them, reads plates off sampled frames, reconstructs a vehicle's route
across cameras, and raises alerts when a watchlisted vehicle is seen.

It bridges **Model 1** (central CCTV registry and GIS foundation) and **Model 2** (unified viewing,
cross-camera vehicle tracking, non-invasive real-time analytics).

---

## What it does

**Unified viewing.** A 1×1 / 2×2 / 3×3 camera wall with paging, filtered by district. Feeds are
consumed over WHEP where a gateway offers it.

**ANPR.** Vehicles are detected with YOLOv8 on sampled frames, the plate is localised inside the
vehicle box, and only that region goes to OCR. Reads carry a confidence score that is discounted
when character correction had to rewrite ambiguous glyphs.

**Cross-camera route reconstruction.** Given a plate, the platform groups sightings into checkpoint
visits, computes transit time, distance and implied speed between them, and draws the route on a
Leaflet map. Any leg implying a physically impossible speed is flagged rather than presented as
fact — that pattern is the signature of a misread or cloned plate.

**Investigative search.** Partial plate, camera, vehicle type, confidence floor and an incident
time window. Results export to CSV carrying both IST and UTC timestamps.

**Watchlist and alerting.** Detections are cross-referenced against the watchlist on arrival. Exact
matches raise a CRITICAL alert over WebSocket; single-character near-misses raise a REVIEW alert
showing the plate the camera actually read alongside the entry it resembles. Repeat sightings at
one camera fold into the existing alert instead of raising a burst.

**Evidence docket.** A printable chronological record of a vehicle's movement, carrying a caveat
block when any leg needs manual verification.

---

## Using the console

Five views, all backed by working functionality:

| View | Contents |
|---|---|
| **Live** | Camera wall, GIS map, live ANPR event log, watchlist alert queue |
| **Search** | Trace a known plate, or search sightings when only part of it is known |
| **Alarms** | The alert queue full width, with filters and acknowledge / resolve |
| **Maps** | The registry and any plotted route, full window |
| **System** | Server health, analytics worker state, and whether the API is authenticated |

The sidebar lists the registry's real districts; selecting one filters the camera wall and refits
the map. Watchlist management — add, deactivate, restore — is under **System → Watchlist**.

A full VMS would also carry Playback, device management and several more analytics. This build
records no video, manages no devices and has ANPR as its only analytic, so it offers no navigation
to any of them. Nav that leads nowhere is worse than nav that is absent.

**Without a reachable gateway the camera tiles show a placeholder**, labelled
`REPRESENTATIVE FEED — NO LIVE STREAM` on the canvas itself. That is expected offline, not a
failure; everything else on the console works against real data.

---

## Tech stack

- **Backend:** FastAPI, Python 3.10+, SQLAlchemy (SQLite, PostgreSQL-ready)
- **Vision:** Ultralytics YOLOv8, EasyOCR, OpenCV
- **Real-time:** WebSocket fan-out for alerts, detections and worker status
- **Frontend:** Vanilla JavaScript, Leaflet, no build step
- **Streaming:** RTSP over TCP, frame sampling to stay within laptop-scale compute

---

## Project structure

```
ai_engine/                  YOLOv8 detection, plate recognition, stream workers
  multi_stream_runner.py      Worker pool, shared models, reaping
  plate_recognizer.py         Plate localisation, OCR, Indian plate validation
  stream_worker.py            One camera: RTSP/TCP, frame skip, reconnect backoff
  vehicle_detector.py         YOLOv8 vehicle boxes (lazy torch import)
backend/app/
  config.py                   Environment-driven settings
  database.py                 Engine, session, SQLite WAL pragmas
  models.py                   ORM models, Pydantic schemas, UTC helpers
  security.py                 Shared-token guard for HTTP and WebSocket
  timewindow.py               Shared ?from=/?to= parsing and validation
  routers/                    registry, search, watchlist, alerts, stream_control
  services/                   alert_engine, route_tracer, catalogue, retention
frontend/
  index.html                  Console shell
  css/console.css             Single stylesheet
  js/                         utils, api, viewer, map, events, alerts, tracker,
                              search, dashboard
data/
  seed_watchlist.json         Representative watchlist records
  snapshots/                  Evidence crops (pruned by retention policy)
docs/PROGRESS.md            Phase status, known gaps, key decisions
scripts/                    Feed simulation and manual ingest/stream checks
tests/                      64 tests, run in CI on Python 3.10 and 3.12
feed_check.py               Standalone RTSP/PTS/reconnect verification
run.py                      Entry point
```

---

## Quickstart

### Prerequisites

Python 3.10 or higher, and Git.

### Install

```bash
pip install -r requirements.txt
```

Dependencies are layered, because the AI stack is large and only the stream workers need it:

| File | Contents | Use when |
|---|---|---|
| `requirements-core.txt` | API, dashboard, registry, tracking | Running the platform without live ANPR |
| `requirements.txt` | core + YOLOv8 + EasyOCR (pulls torch) | Full deployment with AI analytics |
| `requirements-dev.txt` | core + pytest | Running the test suite |

YOLO weights are **not** committed; ultralytics downloads `yolov8n.pt` on first use. Detector and
recognizer imports are lazy, so the API, dashboard and tests all run without torch installed.

### Run

```bash
python run.py
```

```bash
python run.py --host 0.0.0.0 --port 8000
```

- Console: [http://localhost:8000](http://localhost:8000)
- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### Load a demo journey

With no gateway reachable the platform seeds a representative Gujarat camera catalogue. To also
populate a cross-camera journey worth tracing:

```bash
python run.py --simulate-demo
```

Then trace `GJ01AB1234` under **Search**.

### Tests

```bash
pip install -r requirements-dev.txt
```

```bash
python -m pytest tests/ -q
```

---

## Configuration

All settings are environment variables with working defaults:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///data/cctv.db` | Datastore. SQLite runs in WAL mode with a busy timeout. |
| `GOVT_GATEWAY_HOST` | `localhost` | Gateway host for `/api/ingest` and stream URLs. |
| `AI_FRAME_SKIP` | `8` | Process 1 frame in N (~3 FPS on a 25 FPS stream). |
| `VEHICLE_CONF_THRESHOLD` | `0.35` | Minimum YOLO confidence for a vehicle box. |
| `ALERT_COOLDOWN_SECONDS` | `120` | Repeat sightings of one plate at one camera fold into the existing alert. |
| `FUZZY_MATCH_MIN_LENGTH` | `8` | Below this length a one-character edit is too weak to act on. |
| `HOP_GROUPING_WINDOW_SECONDS` | `120` | Sightings at one camera inside this window are a single visit. |
| `IMPLAUSIBLE_SPEED_KMH` | `160` | Inter-camera speeds above this are flagged for manual verification. |
| `MAX_PAGE_SIZE` | `500` | Upper bound on any `limit` parameter. |
| `CORS_ALLOW_ORIGINS` | *(empty)* | Comma-separated extra origins. Same-origin needs no entry. |
| `SENTINEL_API_TOKEN` | *(empty)* | Shared platform token. Unset = **open API**. |
| `SNAPSHOT_RETENTION_DAYS` | `30` | Age limit for evidence crops. `0` disables. |
| `SNAPSHOT_MAX_FILES` | `20000` | Ceiling on stored crops, oldest pruned first. `0` disables. |

There are no migrations yet. Schema changes require deleting `data/cctv.db`.

---

## Access control

Set `SENTINEL_API_TOKEN` and every `/api` route except `/api/health` requires it, as does the alert
WebSocket. The console prompts for the token once and holds it for the browser session.

```bash
SENTINEL_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" python run.py
```

```bash
curl -H "Authorization: Bearer $SENTINEL_API_TOKEN" http://localhost:8000/api/cameras
```

Leaving it unset keeps the API open and logs a warning at startup, which is fine for local
development and nothing else. An open instance exposes the camera registry including RTSP URLs,
the watchlist with owner names and FIR numbers, and analytics worker control.

**This is a stopgap, not an identity system.** A single shared token gives no per-officer audit
trail and no revocation short of rotating it. Real deployment needs proper identity.

---

## Known limitations

`docs/PROGRESS.md` carries the full list. The ones that matter most:

- **ANPR read accuracy is unmeasured.** Plate localisation is tested for geometry, but end-to-end
  accuracy needs real Gujarat footage and a ground-truth set that does not exist yet.
- **Never validated against a real government feed.** Awaiting a gateway host.
- **Camera reachability is not probed.** Connectivity status is whatever the catalogue reported.
- **PTS is recorded but not used for analytics.** `CAP_PROP_POS_MSEC` resets on reconnect, so it is
  not comparable across cameras; route timings use wall-clock capture time.
- **Snapshot retention has no per-case hold**, so a crop tied to an active investigation can age
  out. Not evidence-grade yet.
