"""
Plate standardization and localisation.

`PlateRecognizer.__init__` constructs an EasyOCR reader, which downloads ~100MB
of weights. These tests exercise the real methods on an instance built without
running `__init__`, so the geometry and string logic are covered without the
model. OCR accuracy itself needs real footage and is not asserted here.
"""

import cv2
import numpy as np
import pytest

from ai_engine.plate_recognizer import PlateRecognizer


@pytest.fixture()
def recognizer():
    r = PlateRecognizer.__new__(PlateRecognizer)
    r.state_codes = [
        "GJ", "MH", "DL", "RJ", "MP", "UP", "HR", "PB", "KA", "TN", "KL",
        "AP", "TS", "WB", "BR", "OD", "JH", "CG", "UK", "HP", "AS", "GA",
        "CH", "JK", "PY", "AR", "MN", "ML", "MZ", "NL", "SK", "TR", "LD", "AN",
    ]
    return r


# ---------------------------------------------------------------- validation
def test_accepts_real_registration_formats(recognizer):
    for plate in ["GJ01AB1234", "GJ1AB1234", "MH12DE9999", "GJ27EF9012", "22BH1234A"]:
        assert recognizer.is_valid_indian_plate(plate), plate


def test_rejects_malformed_and_unknown_state_codes(recognizer):
    for plate in ["", "GJ", "ABCDEFGH", "1234567890", "GJ01AB123", "ZZ01AB1234"]:
        assert not recognizer.is_valid_indian_plate(plate), plate


# ---------------------------------------------------------------- correction
def test_corrects_confusable_characters_by_position(recognizer):
    # '6' for 'G' in the state code, 'O' for '0' in the RTO code, and 'Z' for
    # '2' in the trailing digits -- three rewrites in one read.
    corrected, changed = recognizer.correct_indian_plate_ambiguities("6JO1AB1Z34")
    assert corrected == "GJ01AB1234"
    assert changed == 3
    assert recognizer.is_valid_indian_plate(corrected)


def test_reports_how_many_characters_were_rewritten(recognizer):
    """
    The count is what lets the caller discount confidence. Without it a string
    reshaped into looking valid is indistinguishable from a clean read.
    """
    _, untouched = recognizer.correct_indian_plate_ambiguities("GJ01AB1234")
    assert untouched == 0

    _, rewritten = recognizer.correct_indian_plate_ambiguities("GJOIAB1234")
    assert rewritten == 2


def test_bh_series_survives_correction(recognizer):
    """
    BH plates lead with two digits. The standard state-code pass forces the
    first two characters to letters, which would corrupt every one of them.
    """
    corrected, _ = recognizer.correct_indian_plate_ambiguities("22BH1234A")
    assert corrected == "22BH1234A"
    assert recognizer.is_valid_indian_plate(corrected)


def test_short_input_is_returned_untouched(recognizer):
    corrected, changed = recognizer.correct_indian_plate_ambiguities("GJ01")
    assert corrected == "GJ01"
    assert changed == 0


# ---------------------------------------------------------------- localisation
def _vehicle_with_plate(plate_box=(170, 250, 140, 34)):
    """
    Synthetic rear-of-vehicle: dark body, light plate rectangle low down,
    carrying dark vertical strokes standing in for characters.
    """
    img = np.full((320, 480, 3), 45, dtype=np.uint8)
    cv2.rectangle(img, (60, 120), (420, 300), (70, 70, 75), -1)  # body

    x, y, w, h = plate_box
    cv2.rectangle(img, (x, y), (x + w, y + h), (235, 235, 235), -1)
    for i in range(8):
        cx = x + 8 + i * 16
        cv2.rectangle(img, (cx, y + 7), (cx + 7, y + h - 7), (25, 25, 25), -1)
    return img


def _overlaps(box_a, box_b):
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b
    return not (ax + aw < bx or bx + bw < ax or ay + ah < by or by + bh < ay)


def test_locates_a_plate_shaped_region(recognizer):
    plate_box = (170, 250, 140, 34)
    candidates = recognizer.locate_plate_candidates(_vehicle_with_plate(plate_box))

    assert candidates, "expected at least one plate candidate"
    assert any(_overlaps(box, plate_box) for _region, box in candidates)


def test_located_region_has_plate_like_proportions(recognizer):
    candidates = recognizer.locate_plate_candidates(_vehicle_with_plate())
    for _region, (_x, _y, w, h) in candidates:
        assert 1.8 <= w / h <= 6.5


def test_returns_nothing_for_a_blank_crop_so_the_caller_falls_back(recognizer):
    """An empty list is the signal to fall back to whole-crop OCR."""
    blank = np.full((240, 360, 3), 90, dtype=np.uint8)
    assert recognizer.locate_plate_candidates(blank) == []


def test_ignores_lettering_in_the_upper_third(recognizer):
    """
    Windscreen permits and roof-line text sit high on the vehicle. Anything
    above the cut-off must not be offered as a plate.
    """
    img = np.full((320, 480, 3), 45, dtype=np.uint8)
    cv2.rectangle(img, (60, 120), (420, 300), (70, 70, 75), -1)
    # A plate-shaped sticker near the very top of the crop.
    x, y, w, h = 160, 8, 150, 32
    cv2.rectangle(img, (x, y), (x + w, y + h), (235, 235, 235), -1)
    for i in range(8):
        cx = x + 8 + i * 17
        cv2.rectangle(img, (cx, y + 6), (cx + 7, y + h - 6), (25, 25, 25), -1)

    for _region, (_bx, by, _bw, _bh) in recognizer.locate_plate_candidates(img):
        assert by >= int(320 * 0.30) - 10


def test_tiny_and_empty_crops_are_handled(recognizer):
    assert recognizer.locate_plate_candidates(None) == []
    assert recognizer.locate_plate_candidates(np.zeros((0, 0, 3), dtype=np.uint8)) == []
    assert recognizer.locate_plate_candidates(np.zeros((10, 10, 3), dtype=np.uint8)) == []
