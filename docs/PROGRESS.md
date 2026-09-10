# SENTINEL — Project Progress & Operational Log

> Single source of truth for Sentinel: Gujarat Police Unified CCTV & Video Analytics Platform.
> Updated at the conclusion of every phase. **Last updated 2026-09-11.**

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
| **Phase 8** | ANPR (plate detector + OCR, confidence scoring) | **DONE** | Morphological plate localisation, then OCR; whole-crop read kept as fallback |
| **Phase 9** | Detection metadata storage | **DONE** | `detections` table, composite plate+time index |
| **Phase 10** | Vehicle search by plate (API + UI) | **DONE** | Partial-plate, camera, type and confidence search with CSV export |
| **Phase 11** | Cross-camera timeline | **DONE** | Time-windowed hop grouping; traces scope to an incident window |
| **Phase 12** | GIS route reconstruction | **DONE** | Per-leg polylines; implausible legs drawn separately |
| **Phase 13** | Mock watchlist | **DONE** | Seeded records; add, deactivate and restore from the UI |
| **Phase 14** | Watchlist matching | **DONE** | Exact-first, then single-edit fuzzy at REVIEW severity |
| **Phase 15** | Real-time alerts (UI surfacing with snapshots) | **DONE** | WebSocket fan-out; covered by `tests/test_live_alert_pipeline.py` |
| **Phase 16** | Camera health monitoring | **PARTIAL** | Worker liveness and reconnect counts are exposed; camera reachability is still whatever the catalogue reported |
| **Phase 17** | Integrated command dashboard | **DONE** | VMS-style console: Live / Search / Alarms / Maps / System, district views, ANPR event log, alert queue, print-ready docket |
| Phase 18 | Real government feed testing | PENDING | Blocked on gateway host |
| Phase 19 | Performance & frame sampling pass | PENDING | |
| Phase 20 | Deliverables (PPT, HLD, architecture diagrams) | PENDING | |

---

## Known Gaps & Blockers

- **Awaiting gateway `<host>`:** `http://localhost/api/ingest` returns connection refused. The
  platform falls back to the offline Gujarat seed catalogue until a host is supplied.
- **Authentication is a single shared token.** `SENTINEL_API_TOKEN` guards the API and the alert
  WebSocket, but it gives no per-officer audit trail and no revocation short of rotation. Real
  deployment needs proper identity. Leaving the variable unset still means an open API.
- **ANPR accuracy is unmeasured.** Plate localisation is in place and its geometry is tested, but
  end-to-end read accuracy needs real Gujarat footage to quantify. No ground-truth set exists yet.
- **PTS is recorded but not used for analytics.** `CAP_PROP_POS_MSEC` is a per-connection offset
  that resets to zero on reconnect, so it is not comparable across cameras as stored. Route
  timings therefore use `capture_timestamp`. Making PTS authoritative needs an absolute clock
  reference from the gateway.
- **SQLite, no migrations.** WAL and a busy timeout are enabled, which is enough for a handful of
  workers, but schema changes still require dropping `data/cctv.db`. Postgres + Alembic before
  any multi-user deployment.
- **Retention is time and count based only.** Snapshots prune on age and a file ceiling; there is
  no per-case hold, so a crop tied to an active investigation can age out. Case-aware retention is
  needed before this is evidence-grade.
- **No single-camera detail view.** There is no screen showing one camera's recent sightings,
  connectivity and worker state together; the information exists but is spread across the map
  popup, the event log and the System view. Convenience, not a functional hole.
- **The alert queue does not paginate.** It fetches the most recent 100 and stops. Past that,
  older alerts are unreachable from the UI even though `/api/alerts` accepts `offset`. Sighting
  search has a Load more; the queue does not.

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
8. **ANPR localises the plate before reading it.** Running OCR across the whole vehicle box fed the
   reader every painted word on the vehicle. Localisation failure falls back to the old whole-crop
   read, so the change cannot lose a detection outright.
9. **Character correction reports how many characters it rewrote**, and confidence is discounted
   per rewrite. Applied blindly, the correction could manufacture a valid-looking plate out of
   unrelated lettering and report it at full confidence.
10. **Every investigative query is bounded by a time window.** Detections,
    alerts and the cross-camera trace share one `?from=`/`?to=` implementation.
    An unscoped trace returns a vehicle's entire recorded history, which is
    rarely what a case wants, and an empty windowed result says so explicitly
    rather than reading as "never seen".
11. **Search inputs are read as IST, not workstation-local.** The dashboard
    renders every timestamp in Asia/Kolkata, so `datetime-local` values are
    stamped +05:30 before being sent. A console whose clock is set elsewhere
    would otherwise search a window hours from the one the operator typed,
    with nothing on screen showing the discrepancy.
12. **Removing a vehicle from the watchlist is a soft deactivate.** The row is
    what ties existing Alert records to their FIR and crime category, so an
    alert that has already been acted on stays explicable afterwards. A
    separate reactivate endpoint restores an entry without the re-POST path's
    habit of silently overwriting its case details.
13. **The console offers no navigation to features that do not exist.** A full
    VMS carries Playback, device management and several analytics; this build
    records nothing, manages no devices and has ANPR as its only analytic. Every
    tab — Live, Search, Alarms, Maps, System — reaches working functionality,
    and sidebar views are the registry's real districts rather than invented
    zones. Nav that leads nowhere is worse than nav that is absent, and it would
    breach the zero-fabricated-integrations constraint above.
14. **AI imports are lazy.** torch, ultralytics and easyocr load only when a worker starts, so the
    API, dashboard and CI run without a multi-gigabyte install. CI asserts this stays true.

---

## Where the code lives

| Remote | Repository | Role |
|---|---|---|
| `standalone` | `bhupendrasharmaX/sentinel` | Not a fork. `main` tracks this, so a bare `git push` goes here. CI runs. |
| `fork` | `bhupendrasharmaX/cctv` | Fork of upstream; carries the PR branch. Push explicitly. |
| `origin` | `mohittchoudhary/cctv` | Upstream. Never pushed to directly. |

**PR #1** against `mohittchoudhary/cctv` carries the full change set (7 commits).
It shows no checks until a maintainer approves the workflow run — GitHub gates
Actions for first-time outside contributors.

Commits must be authored as `bhupendra09x@gmail.com`. A different address on
this machine maps to an unrelated GitHub account, and four commits once had to
be rewritten and force-pushed to correct the attribution.

---

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

64 tests, run in CI on Python 3.10 and 3.12:

| File | Covers |
|---|---|
| `test_alert_engine.py` | Plate matching, fuzzy handling, alert suppression |
| `test_route_tracer.py` | Hop grouping, distance/speed, UTC serialization |
| `test_live_alert_pipeline.py` | End-to-end WebSocket delivery, SSRF guard |
| `test_plate_recognizer.py` | Plate validation, character correction, localisation geometry |
| `test_security.py` | Token enforcement across HTTP and WebSocket |
| `test_retention.py` | Snapshot pruning by age and count |
| `test_timewindow.py` | IST-to-UTC normalization, inverted windows, scoped traces |
| `test_watchlist.py` | Deactivate/restore lifecycle, and that a deactivated vehicle stops alerting |

CI also asserts the app still imports without torch, ultralytics or easyocr present.
