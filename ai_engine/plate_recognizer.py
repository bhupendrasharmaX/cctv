import re
import cv2
import logging
import numpy as np
from typing import Optional, Dict, Any, List

logger = logging.getLogger("cctv.plate_recognizer")

class PlateRecognizer:
    """
    Automated Number Plate Recognition (ANPR) module for Indian vehicle registrations.
    Performs image preprocessing, OCR extraction, and regex-based plate standardization.
    """
    def __init__(self, gpu: bool = True):
        import torch
        use_gpu = gpu and torch.cuda.is_available()
        logger.info(f"Initializing EasyOCR reader (GPU: {use_gpu})")
        import easyocr
        self.reader = easyocr.Reader(['en'], gpu=use_gpu)

        # Indian state codes list
        self.state_codes = [
            "GJ", "MH", "DL", "RJ", "MP", "UP", "HR", "PB", "KA", "TN", "KL", "AP", "TS", "WB", "BR"
        ]

    def preprocess_plate_region(self, img: np.ndarray) -> np.ndarray:
        """Enhance plate visibility for OCR using contrast normalization."""
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img

        # Resize for consistent character height
        h, w = gray.shape
        if h < 60:
            scale = 60.0 / max(1, h)
            gray = cv2.resize(gray, (int(w * scale), 60), interpolation=cv2.INTER_CUBIC)

        # Bilateral filter to reduce noise while preserving edges
        filtered = cv2.bilateralFilter(gray, 11, 17, 17)

        # Contrast Limited Adaptive Histogram Equalization (CLAHE)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(filtered)

        return enhanced

    def correct_indian_plate_ambiguities(self, text: str) -> str:
        """
        Correct common optical character confusion (0 vs O/D, 8 vs B, 1 vs I/L)
        based on Indian registration syntax:
        [2 Letters: State] [2 Digits: RTO] [0-3 Letters: Series] [4 Digits: Number]
        Example: GJ01AB1234
        """
        clean = "".join(c for c in text.upper() if c.isalnum())
        if len(clean) < 6:
            return clean

        chars = list(clean)

        # 1. State code (First 2 characters MUST be letters)
        letter_map = {'0': 'O', '1': 'I', '2': 'Z', '5': 'S', '8': 'B'}
        for i in range(min(2, len(chars))):
            if chars[i] in letter_map:
                chars[i] = letter_map[chars[i]]

        # 2. RTO code (Characters 2 & 3 MUST be digits)
        digit_map = {'O': '0', 'D': '0', 'Q': '0', 'I': '1', 'L': '1', 'Z': '2', 'S': '5', 'B': '8'}
        for i in range(2, min(4, len(chars))):
            if chars[i] in digit_map:
                chars[i] = digit_map[chars[i]]

        # 3. Last 4 characters (MUST be digits)
        if len(chars) >= 8:
            for i in range(len(chars) - 4, len(chars)):
                if chars[i] in digit_map:
                    chars[i] = digit_map[chars[i]]

        return "".join(chars)

    def recognize_plate(self, vehicle_crop: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Scans a vehicle crop for license plates.
        Returns cleaned plate string, raw OCR text, and confidence.
        """
        if vehicle_crop is None or vehicle_crop.size == 0:
            return None

        # Preprocess crop
        prep = self.preprocess_plate_region(vehicle_crop)

        # Run OCR
        results = self.reader.readtext(
            prep,
            allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
            detail=1,
            paragraph=False
        )

        candidates = []
        for bbox, text, conf in results:
            clean_text = self.correct_indian_plate_ambiguities(text)

            # Check if text resembles Indian plate format
            # e.g., GJ01AB1234 or GJ011234 or MH12DE1234
            is_valid_format = False
            if re.match(r'^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$', clean_text):
                is_valid_format = True
            elif len(clean_text) >= 8 and any(clean_text.startswith(sc) for sc in self.state_codes):
                is_valid_format = True

            if is_valid_format or (len(clean_text) >= 7 and conf > 0.4):
                candidates.append({
                    "plate_number": clean_text,
                    "plate_raw": text,
                    "confidence": round(float(conf), 3),
                    "is_standard_hsrp": is_valid_format
                })

        if not candidates:
            return None

        # Sort by confidence and format validity
        candidates.sort(key=lambda x: (x["is_standard_hsrp"], x["confidence"]), reverse=True)
        return candidates[0]
