import logging
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

    def _init_ai_models(self):
        if not self._initialized_ai:
            logger.info("Loading AI models (YOLOv8 + EasyOCR) for stream processing...")
            self.detector = VehicleDetector()
            self.recognizer = PlateRecognizer(gpu=True)
            self._initialized_ai = True

    def start_worker(self, camera_id: str, rtsp_url: str) -> bool:
        """Start AI worker for a specific camera stream."""
        if camera_id in self.workers and self.workers[camera_id].is_alive():
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

    def stop_worker(self, camera_id: str) -> bool:
        """Stop AI worker for a camera."""
        if camera_id in self.workers:
            self.workers[camera_id].stop()
            del self.workers[camera_id]
            logger.info(f"Terminated worker for camera '{camera_id}'.")
            return True
        return False

    def stop_all(self):
        """Stop all running stream workers."""
        logger.info("Stopping all camera stream workers...")
        for cid, worker in list(self.workers.items()):
            worker.stop()
        self.workers.clear()

    def get_status(self) -> Dict[str, Any]:
        status_list = []
        for cid, w in self.workers.items():
            status_list.append({
                "camera_id": cid,
                "is_alive": w.is_alive(),
                "frames_read": w.total_frames_read,
                "detections_count": w.total_detections,
                "reconnect_attempts": w.reconnect_attempts
            })
        return {
            "active_workers_count": len(self.workers),
            "max_capacity": self.max_concurrent_streams,
            "workers": status_list
        }

# Global singleton
stream_pool = MultiStreamManager(max_concurrent_streams=5)
