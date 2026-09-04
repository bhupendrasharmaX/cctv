import os
import time
import datetime
import logging
import threading
from pathlib import Path
from typing import Optional, Callable
import cv2
from backend.app.config import SNAPSHOT_DIR, AI_FRAME_SKIP
from backend.app.database import SessionLocal
from backend.app.models import Detection, Camera
from backend.app.services.alert_engine import check_and_generate_alert

# Enforce RTSP over TCP as mandated by the challenge guidelines
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

logger = logging.getLogger("cctv.stream_worker")

class StreamWorker(threading.Thread):
    """
    Resilient live stream ingestion worker for a single CCTV camera feed.
    - Forces RTSP over TCP to prevent packet loss.
    - Uses stream PTS (CAP_PROP_POS_MSEC) instead of wall-clock arrival time.
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
        self.reconnect_attempts = 0
        self.total_frames_read = 0
        self.total_detections = 0

    def stop(self):
        """Signal the worker to terminate gracefully."""
        self.running = False

    def run(self):
        logger.info(f"[{self.camera_id}] Starting stream worker on: {self.rtsp_url}")

        while self.running:
            cap = None
            try:
                # Open RTSP stream with FFMPEG backend over TCP
                cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    raise ConnectionError(f"Failed to open video capture for {self.rtsp_url}")

                logger.info(f"[{self.camera_id}] RTSP stream connected successfully over TCP.")
                self.reconnect_attempts = 0 # Reset backoff counter
                frame_idx = 0

                while self.running and cap.isOpened():
                    # Fast grab to keep internal FFMPEG buffer completely drained
                    grabbed = cap.grab()
                    if not grabbed:
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

                    # 1. Run Vehicle Detection (YOLOv8)
                    vehicles = self.detector.detect_vehicles(frame)

                    for v in vehicles:
                        crop = v["crop"]
                        # 2. Run ANPR OCR on vehicle crop
                        plate_res = self.recognizer.recognize_plate(crop)
                        if plate_res:
                            plate_num = plate_res["plate_number"]
                            conf = plate_res["confidence"]
                            raw = plate_res.get("plate_raw", plate_num)

                            # Save crop snapshot
                            ts_str = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
                            filename = f"{self.camera_id}_{plate_num}_{ts_str}.jpg"
                            snap_path = SNAPSHOT_DIR / filename
                            try:
                                cv2.imwrite(str(snap_path), crop)
                                rel_path = f"/snapshots/{filename}"
                            except Exception:
                                rel_path = None

                            # Persist detection in database
                            db = SessionLocal()
                            try:
                                cam = db.query(Camera).filter(Camera.camera_id == self.camera_id).first()
                                det = Detection(
                                    camera_id=self.camera_id,
                                    plate_number=plate_num,
                                    plate_raw=raw,
                                    confidence=conf,
                                    vehicle_type=v["vehicle_type"],
                                    pts_timestamp_ms=pts_ms,
                                    capture_timestamp=datetime.datetime.utcnow(),
                                    snapshot_path=rel_path
                                )
                                db.add(det)
                                db.commit()
                                db.refresh(det)

                                self.total_detections += 1
                                logger.info(
                                    f"[{self.camera_id}] DETECTED: {plate_num} ({v['vehicle_type']}, "
                                    f"conf: {conf:.2f}, PTS: {pts_ms}ms)"
                                )

                                # Watchlist match & real-time alert trigger
                                if cam:
                                    check_and_generate_alert(db, det, cam)

                                if self.on_detection_callback:
                                    self.on_detection_callback(det)
                            finally:
                                db.close()

            except Exception as e:
                logger.error(f"[{self.camera_id}] Stream error: {e}")
            finally:
                if cap:
                    cap.release()

            # Automatic reconnect with exponential backoff
            if self.running:
                self.reconnect_attempts += 1
                backoff = min(30, 2 ** min(self.reconnect_attempts, 5))
                logger.warning(f"[{self.camera_id}] Reconnecting in {backoff}s (attempt #{self.reconnect_attempts})...")
                time.sleep(backoff)

        logger.info(f"[{self.camera_id}] Stream worker stopped.")
