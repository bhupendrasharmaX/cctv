import os
import time
import logging
import threading
from typing import Optional, Callable
import cv2
from backend.app.config import SNAPSHOT_DIR, AI_FRAME_SKIP
from backend.app.database import SessionLocal
from backend.app.models import Detection, Camera, utcnow
from backend.app.services.alert_engine import check_and_generate_alert, push_detection

# Enforce RTSP over TCP as mandated by the challenge guidelines
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

logger = logging.getLogger("cctv.stream_worker")


class StreamWorker(threading.Thread):
    """
    Resilient live stream ingestion worker for a single CCTV camera feed.
    - Forces RTSP over TCP to prevent packet loss.
    - Uses stream PTS (CAP_PROP_POS_MSEC) alongside wall-clock capture time.
    - Implements frame-skipping (evaluating 2-3 FPS) to eliminate processing lag and GPU strain.
    - Implements automatic reconnect with exponential backoff on network dropouts.
    """
    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        detector,
        recognizer,
        frame_skip: int = AI_FRAME_SKIP,
        on_detection_callback: Optional[Callable] = None
    ):
        super().__init__(name=f"Worker-{camera_id}", daemon=True)
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.detector = detector
        self.recognizer = recognizer
        self.frame_skip = max(1, frame_skip)
        self.on_detection_callback = on_detection_callback
        self.running = True
        self.connected = False
        self.last_error: Optional[str] = None
        self.reconnect_attempts = 0
        self.total_frames_read = 0
        self.total_detections = 0
        # Wakes the reconnect backoff immediately on stop() instead of leaving the
        # thread parked in a sleep for up to 30 seconds after shutdown.
        self._stop_event = threading.Event()

    def stop(self):
        """Signal the worker to terminate gracefully."""
        self.running = False
        self._stop_event.set()

    def _persist_detection(self, plate_res, vehicle, pts_ms, snapshot_rel_path):
        """Write one sighting and run it past the watchlist."""
        db = SessionLocal()
        try:
            cam = db.query(Camera).filter(Camera.camera_id == self.camera_id).first()
            det = Detection(
                camera_id=self.camera_id,
                plate_number=plate_res["plate_number"],
                plate_raw=plate_res.get("plate_raw", plate_res["plate_number"]),
                confidence=plate_res["confidence"],
                vehicle_type=vehicle["vehicle_type"],
                pts_timestamp_ms=pts_ms,
                capture_timestamp=utcnow(),
                snapshot_path=snapshot_rel_path
            )
            db.add(det)
            db.commit()
            db.refresh(det)

            self.total_detections += 1
            logger.info(
                f"[{self.camera_id}] DETECTED: {det.plate_number} ({det.vehicle_type}, "
                f"conf: {det.confidence:.2f}, PTS: {pts_ms}ms)"
            )

            if cam:
                push_detection(det, cam)
                check_and_generate_alert(db, det, cam)

            if self.on_detection_callback:
                self.on_detection_callback(det)
        except Exception as e:
            logger.error(f"[{self.camera_id}] Failed to persist detection: {e}")
            db.rollback()
        finally:
            db.close()

    def _process_frame(self, frame, pts_ms):
        vehicles = self.detector.detect_vehicles(frame)

        for v in vehicles:
            crop = v["crop"]
            plate_res = self.recognizer.recognize_plate(crop)
            if not plate_res:
                continue

            plate_num = plate_res["plate_number"]
            ts_str = utcnow().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"{self.camera_id}_{plate_num}_{ts_str}.jpg"
            snap_path = SNAPSHOT_DIR / filename
            try:
                cv2.imwrite(str(snap_path), crop)
                rel_path = f"/snapshots/{filename}"
            except Exception as e:
                logger.warning(f"[{self.camera_id}] Could not write snapshot: {e}")
                rel_path = None

            self._persist_detection(plate_res, v, pts_ms, rel_path)

    def run(self):
        logger.info(f"[{self.camera_id}] Starting stream worker on: {self.rtsp_url}")

        while self.running:
            cap = None
            try:
                cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    raise ConnectionError(f"Failed to open video capture for {self.rtsp_url}")

                logger.info(f"[{self.camera_id}] RTSP stream connected successfully over TCP.")
                self.connected = True
                self.last_error = None
                self.reconnect_attempts = 0 # Reset backoff counter
                frame_idx = 0

                while self.running and cap.isOpened():
                    # Fast grab to keep internal FFMPEG buffer completely drained
                    if not cap.grab():
                        logger.warning(f"[{self.camera_id}] Stream read returned empty. Connection may have dropped.")
                        break

                    frame_idx += 1
                    self.total_frames_read += 1

                    # Adaptive frame-skipping: only retrieve and run AI inference every N frames
                    if frame_idx % self.frame_skip != 0:
                        continue

                    ret, frame = cap.retrieve()
                    if not ret or frame is None:
                        continue

                    # Extract presentation timestamp (PTS in milliseconds)
                    pts_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
                    self._process_frame(frame, pts_ms)

            except Exception as e:
                self.last_error = str(e)
                logger.error(f"[{self.camera_id}] Stream error: {e}")
            finally:
                self.connected = False
                if cap:
                    cap.release()

            # Automatic reconnect with exponential backoff
            if self.running:
                self.reconnect_attempts += 1
                backoff = min(30, 2 ** min(self.reconnect_attempts, 5))
                logger.warning(f"[{self.camera_id}] Reconnecting in {backoff}s (attempt #{self.reconnect_attempts})...")
                # Interruptible: stop() returns immediately instead of waiting
                # out the full backoff.
                if self._stop_event.wait(timeout=backoff):
                    break

        self.connected = False
        logger.info(f"[{self.camera_id}] Stream worker stopped.")
