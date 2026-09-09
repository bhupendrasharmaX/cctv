import logging
from typing import List, Dict, Any, Tuple
import numpy as np

logger = logging.getLogger("cctv.vehicle_detector")

class VehicleDetector:
    """
    High-performance vehicle detection module using Ultralytics YOLOv8.
    Leverages NVIDIA CUDA GPU if present, otherwise optimized for multi-core CPU.
    Filters exclusively for vehicles: car, motorcycle, bus, truck.
    """
    def __init__(self, model_name: str = "yolov8n.pt", conf_thresh: float = 0.35):
        # torch and ultralytics are imported here rather than at module scope so
        # the registry, dashboard and API can run (and be tested) without the
        # multi-gigabyte ML stack installed. Only starting an AI worker needs it.
        import torch

        self.conf_thresh = conf_thresh
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        logger.info(f"Initializing VehicleDetector on device: {self.device}")

        from ultralytics import YOLO
        # Ultralytics downloads the weights on first use if they are not present.
        self.model = YOLO(model_name)
        # COCO class IDs: 2: car, 3: motorcycle, 5: bus, 7: truck
        self.target_classes = {2: "CAR", 3: "MOTORCYCLE", 5: "BUS", 7: "TRUCK"}

    def detect_vehicles(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Runs inference on an OpenCV BGR frame.
        Returns list of detected vehicles with bounding box and cropped image.
        """
        results = self.model.predict(
            source=frame,
            classes=list(self.target_classes.keys()),
            conf=self.conf_thresh,
            device=self.device,
            verbose=False
        )

        detections = []
        h, w, _ = frame.shape

        for r in results:
            boxes = r.boxes
            for box in boxes:
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                xyxy = box.xyxy[0].cpu().numpy().astype(int)
                x1, y1, x2, y2 = xyxy

                # Ensure coordinates are within frame bounds
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w, x2), min(h, y2)

                # Skip bounding boxes that are too small (e.g. far background objects)
                box_w = x2 - x1
                box_h = y2 - y1
                if box_w < 60 or box_h < 40:
                    continue

                crop = frame[y1:y2, x1:x2]

                detections.append({
                    "vehicle_type": self.target_classes.get(cls_id, "VEHICLE"),
                    "confidence": round(conf, 3),
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "crop": crop
                })

        return detections
