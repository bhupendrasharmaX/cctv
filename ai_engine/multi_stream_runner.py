import logging
import threading
from typing import Dict, Optional, List, Any
from ai_engine.stream_worker import StreamWorker
from ai_engine.vehicle_detector import VehicleDetector
from ai_engine.plate_recognizer import PlateRecognizer

logger = logging.getLogger("cctv.stream_pool")


class MultiStreamManager:
    """
    Manages concurrent RTSP AI stream workers.
    Shares a single GPU/CPU instance of YOLO and OCR across all streams
    to conserve memory and prevent resource contention on laptops.
    """
    def __init__(self, max_concurrent_streams: int = 5):
        self.max_concurrent_streams = max_concurrent_streams
        self.workers: Dict[str, StreamWorker] = {}
        self.detector = None
        self.recognizer = None
        self._initialized_ai = False
        self._lock = threading.Lock()

    def _init_ai_models(self):
        if not self._initialized_ai:
            logger.info("Loading AI models (YOLOv8 + EasyOCR) for stream processing...")
            self.detector = VehicleDetector()
            self.recognizer = PlateRecognizer(gpu=True)
            self._initialized_ai = True

    def _reap_dead_workers(self) -> int:
        """
        Drop workers whose thread has exited. Without this a crashed stream keeps
        occupying a slot forever and the pool starts refusing new cameras with
        429 while nothing is actually running.
        """
        dead = [cid for cid, w in self.workers.items() if not w.is_alive()]
        for cid in dead:
            logger.info(f"Reaping dead worker for camera '{cid}'.")
            self.workers.pop(cid, None)
        return len(dead)

    def start_worker(self, camera_id: str, rtsp_url: str) -> bool:
        """Start AI worker for a specific camera stream."""
        with self._lock:
            self._reap_dead_workers()

            existing = self.workers.get(camera_id)
            if existing and existing.is_alive():
                logger.info(f"Worker for {camera_id} is already running.")
                return True

            if len(self.workers) >= self.max_concurrent_streams:
                logger.warning(
                    f"Maximum concurrent streams ({self.max_concurrent_streams}) reached. "
                    f"Stop an existing camera before starting {camera_id}."
                )
                return False

            self._init_ai_models()

            worker = StreamWorker(
                camera_id=camera_id,
                rtsp_url=rtsp_url,
                detector=self.detector,
                recognizer=self.recognizer
            )
            worker.start()
            self.workers[camera_id] = worker
            logger.info(f"Spawned AI worker for camera '{camera_id}'. Active workers: {len(self.workers)}")
            return True

    def stop_worker(self, camera_id: str, timeout: float = 5.0) -> bool:
        """Stop AI worker for a camera and wait briefly for it to unwind."""
        with self._lock:
            worker = self.workers.pop(camera_id, None)

        if worker is None:
            return False

        worker.stop()
        worker.join(timeout=timeout)
        if worker.is_alive():
            # The thread is parked in its reconnect backoff; it is a daemon and
            # checks `self.running` on wake, so it will exit on its own.
            logger.info(f"Worker '{camera_id}' still unwinding; it will exit on its next wake-up.")
        logger.info(f"Terminated worker for camera '{camera_id}'.")
        return True

    def stop_all(self):
        """Stop all running stream workers."""
        logger.info("Stopping all camera stream workers...")
        with self._lock:
            workers = list(self.workers.items())
            self.workers.clear()
        for cid, worker in workers:
            worker.stop()
        for cid, worker in workers:
            worker.join(timeout=5.0)

    def is_running(self, camera_id: str) -> bool:
        worker = self.workers.get(camera_id)
        return bool(worker and worker.is_alive())

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            self._reap_dead_workers()
            status_list = []
            for cid, w in self.workers.items():
                status_list.append({
                    "camera_id": cid,
                    "is_alive": w.is_alive(),
                    "frames_read": w.total_frames_read,
                    "detections_count": w.total_detections,
                    "reconnect_attempts": w.reconnect_attempts,
                    "connected": w.connected,
                    "last_error": w.last_error,
                })
            return {
                "active_workers_count": len(self.workers),
                "max_capacity": self.max_concurrent_streams,
                "active_camera_ids": list(self.workers.keys()),
                "workers": status_list
            }


# Global singleton
stream_pool = MultiStreamManager(max_concurrent_streams=5)
