import re
import cv2
import logging
import numpy as np
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger("cctv.plate_recognizer")

# Indian registration formats.
#   Standard : [2 letters state][1-2 digits RTO][0-3 letters series][4 digits]
#   BH series: [2 digits year]BH[4 digits][1-2 letters]
STANDARD_PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$")
# Older/other registrations occasionally carry no letter series at all.
SHORT_PLATE_RE = re.compile(r"^[A-Z]{2}[0-9]{1,2}[0-9]{4}$")
BH_PLATE_RE = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")


class PlateRecognizer:
    """
    Automated Number Plate Recognition (ANPR) for Indian vehicle registrations.

    The pipeline is: locate candidate plate regions inside the vehicle box ->
    preprocess each region -> OCR -> standardize and validate.

    The localisation stage matters. Running OCR across a whole vehicle crop
    feeds the reader every painted word on the vehicle -- dealer decals, transport
    permit text, bumper stickers -- and lets any of them outrank the plate.
    """

    def __init__(self, gpu: bool = True):
        import torch
        use_gpu = gpu and torch.cuda.is_available()
        logger.info(f"Initializing EasyOCR reader (GPU: {use_gpu})")
        import easyocr
        self.reader = easyocr.Reader(['en'], gpu=use_gpu)

        # Indian state codes list
        self.state_codes = [
            "GJ", "MH", "DL", "RJ", "MP", "UP", "HR", "PB", "KA", "TN", "KL",
            "AP", "TS", "WB", "BR", "OD", "JH", "CG", "UK", "HP", "AS", "GA",
            "CH", "JK", "PY", "AR", "MN", "ML", "MZ", "NL", "SK", "TR", "LD", "AN",
        ]

    # ------------------------------------------------------------------
    # Stage 1: locate the plate inside the vehicle box
    # ------------------------------------------------------------------
    def locate_plate_candidates(
        self,
        vehicle_crop: np.ndarray,
        max_candidates: int = 3,
    ) -> List[Tuple[np.ndarray, Tuple[int, int, int, int]]]:
        """
        Find plate-shaped regions in a vehicle crop.

        Uses a blackhat morphological pass to isolate dark characters on a light
        plate, then keeps contours whose shape and placement match a plate.
        Returns (region_image, (x, y, w, h)) ordered best-first; an empty list
        means the caller should fall back to the whole crop.
        """
        if vehicle_crop is None or vehicle_crop.size == 0:
            return []

        h, w = vehicle_crop.shape[:2]
        if h < 20 or w < 40:
            return []

        gray = (cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY)
                if len(vehicle_crop.shape) == 3 else vehicle_crop)

        # Plates sit low on a vehicle. Ignoring the top third removes
        # windscreen permits and roof-line text before they can compete.
        y_offset = int(h * 0.30)
        search = gray[y_offset:, :]
        if search.size == 0:
            return []

        # Blackhat lifts dark glyphs sitting on a lighter plate background.
        rect_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
        blackhat = cv2.morphologyEx(search, cv2.MORPH_BLACKHAT, rect_kernel)

        # Horizontal gradient: plate text is a dense run of vertical strokes.
        grad = cv2.Sobel(blackhat, ddepth=cv2.CV_32F, dx=1, dy=0, ksize=-1)
        grad = np.absolute(grad)
        min_val, max_val = float(grad.min()), float(grad.max())
        if max_val - min_val < 1e-6:
            return []
        grad = (255 * ((grad - min_val) / (max_val - min_val))).astype("uint8")

        grad = cv2.GaussianBlur(grad, (5, 5), 0)
        grad = cv2.morphologyEx(grad, cv2.MORPH_CLOSE, rect_kernel)
        _, thresh = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        # Close along the text line so separated characters merge into one blob.
        thresh = cv2.morphologyEx(
            thresh, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (21, 5)),
        )
        thresh = cv2.dilate(thresh, None, iterations=1)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        scored = []
        crop_area = float(h * w)
        for contour in contours:
            cx, cy, cw, ch = cv2.boundingRect(contour)
            if ch == 0 or cw == 0:
                continue

            aspect = cw / float(ch)
            area_ratio = (cw * ch) / crop_area

            # Single-row Indian plates run roughly 2:1 to 6:1. The generous
            # lower bound keeps two-row plates (common on motorcycles) in play.
            if not (1.8 <= aspect <= 6.5):
                continue
            if not (0.01 <= area_ratio <= 0.35):
                continue
            if cw < 40 or ch < 12:
                continue

            # Pad slightly so glyphs at the edge are not clipped.
            pad_x, pad_y = int(cw * 0.04) + 3, int(ch * 0.12) + 3
            x1 = max(0, cx - pad_x)
            y1 = max(0, cy - pad_y + y_offset)
            x2 = min(w, cx + cw + pad_x)
            y2 = min(h, cy + ch + pad_y + y_offset)
            region = vehicle_crop[y1:y2, x1:x2]
            if region.size == 0:
                continue

            # Prefer bigger, lower regions: the plate is usually the largest
            # plate-shaped thing and sits below any other lettering.
            score = area_ratio + (y1 / float(h)) * 0.35
            scored.append((score, region, (x1, y1, x2 - x1, y2 - y1)))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [(region, box) for _, region, box in scored[:max_candidates]]

    # ------------------------------------------------------------------
    # Stage 2: preprocess a candidate region
    # ------------------------------------------------------------------
    def preprocess_plate_region(self, img: np.ndarray) -> np.ndarray:
        """Enhance plate visibility for OCR using contrast normalization."""
        if img is None or img.size == 0:
            return img

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

        # Resize for consistent character height
        h, w = gray.shape
        if h < 60 and h > 0:
            scale = 60.0 / h
            gray = cv2.resize(gray, (max(1, int(w * scale)), 60), interpolation=cv2.INTER_CUBIC)

        filtered = cv2.bilateralFilter(gray, 11, 17, 17)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(filtered)

    # ------------------------------------------------------------------
    # Stage 3: standardize and validate
    # ------------------------------------------------------------------
    def correct_indian_plate_ambiguities(self, text: str) -> Tuple[str, int]:
        """
        Correct optical character confusion (0/O/D, 8/B, 1/I/L) using Indian
        registration syntax. Returns (corrected, characters_changed).

        The change count is reported so a caller can tell a clean read from one
        this function reshaped into looking valid -- previously the correction
        was applied unconditionally and could manufacture a plausible plate out
        of unrelated text.
        """
        clean = "".join(c for c in text.upper() if c.isalnum())
        if len(clean) < 6:
            return clean, 0

        chars = list(clean)
        changed = 0

        # Both directions of the same confusion set, applied per position.
        letter_map = {'0': 'O', '1': 'I', '2': 'Z', '4': 'A', '5': 'S', '6': 'G', '7': 'T', '8': 'B'}
        digit_map = {
            'O': '0', 'D': '0', 'Q': '0', 'I': '1', 'L': '1', 'Z': '2',
            'A': '4', 'S': '5', 'G': '6', 'T': '7', 'B': '8',
        }

        def swap(index, mapping):
            nonlocal changed
            if index < len(chars) and chars[index] in mapping:
                chars[index] = mapping[chars[index]]
                changed += 1

        # BH-series plates lead with two digits, so the standard state-code
        # correction would corrupt them. Detect and handle them separately.
        if len(chars) >= 8 and "".join(chars[2:4]) == "BH":
            swap(0, digit_map)
            swap(1, digit_map)
            for i in range(4, min(8, len(chars))):
                swap(i, digit_map)
            return "".join(chars), changed

        # 1. State code: first two characters must be letters.
        for i in range(min(2, len(chars))):
            swap(i, letter_map)

        # 2. RTO code: characters 2-3 must be digits.
        for i in range(2, min(4, len(chars))):
            swap(i, digit_map)

        # 3. Final four characters must be digits.
        if len(chars) >= 8:
            for i in range(len(chars) - 4, len(chars)):
                swap(i, digit_map)

        return "".join(chars), changed

    def is_valid_indian_plate(self, plate: str) -> bool:
        """True when the string matches a real Indian registration format."""
        if not plate:
            return False
        if BH_PLATE_RE.match(plate):
            return True
        if STANDARD_PLATE_RE.match(plate) or SHORT_PLATE_RE.match(plate):
            # A well-formed plate still has to carry a real state code.
            return plate[:2] in self.state_codes
        return False

    # ------------------------------------------------------------------
    # Stage 4: recognition
    # ------------------------------------------------------------------
    def _read_region(self, region: np.ndarray, source: str) -> List[Dict[str, Any]]:
        """OCR one region and return standardized plate candidates."""
        prep = self.preprocess_plate_region(region)
        if prep is None or prep.size == 0:
            return []

        try:
            results = self.reader.readtext(
                prep,
                allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                detail=1,
                paragraph=False,
            )
        except Exception as e:
            logger.warning(f"OCR failed on {source} region: {e}")
            return []

        candidates = []
        for _bbox, text, conf in results:
            raw_clean = "".join(c for c in str(text).upper() if c.isalnum())
            corrected, changed = self.correct_indian_plate_ambiguities(text)

            # Prefer the uncorrected read when it is already a valid plate.
            if self.is_valid_indian_plate(raw_clean):
                plate, changed = raw_clean, 0
            elif self.is_valid_indian_plate(corrected):
                plate = corrected
            else:
                plate = corrected

            valid = self.is_valid_indian_plate(plate)
            confidence = float(conf)
            # Each rewritten character is a character the camera did not
            # actually resolve, so discount the score rather than reporting the
            # reader's confidence in a string it never read.
            confidence *= max(0.5, 1.0 - 0.08 * changed)
            if source == "vehicle_fallback":
                # Read off the whole vehicle box, so it could be any lettering.
                confidence *= 0.85

            if not valid and not (len(plate) >= 8 and conf > 0.55):
                continue

            candidates.append({
                "plate_number": plate,
                "plate_raw": str(text),
                "confidence": round(confidence, 3),
                "is_standard_hsrp": valid,
                "corrections_applied": changed,
                "source": source,
            })

        return candidates

    def recognize_plate(self, vehicle_crop: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Scan a vehicle crop for a license plate.
        Returns the best candidate, or None when nothing plate-like was read.
        """
        if vehicle_crop is None or vehicle_crop.size == 0:
            return None

        candidates: List[Dict[str, Any]] = []

        for region, box in self.locate_plate_candidates(vehicle_crop):
            found = self._read_region(region, source="plate_region")
            for item in found:
                item["plate_bbox"] = list(box)
            candidates.extend(found)
            # A validated read from a located plate is as good as this gets.
            if any(item["is_standard_hsrp"] for item in found):
                break

        # Only fall back to the whole vehicle box when localisation found
        # nothing usable, so the old behaviour remains a safety net rather than
        # the primary path.
        if not any(item["is_standard_hsrp"] for item in candidates):
            candidates.extend(self._read_region(vehicle_crop, source="vehicle_fallback"))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x["is_standard_hsrp"], x["confidence"]), reverse=True)
        return candidates[0]
