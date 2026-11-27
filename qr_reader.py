"""Reads the QR-code labels in a tray photo

Runs on the FULL-SIZE photo, before anything is shrunk. A label's QR code is only about
0.75 inch wide, so in a whole-tray photo each of its squares is about 6-7 pixels wide.
Shrunk for the leaf analysis, they would be 2-3 pixels, too small to read reliably.

Reads with zxing-cpp. On test photos it read every label (20 of 20, including blurry
ones), in about 0.07 s per photo. OpenCV's own QR readers read 14-17 of the 20 and took
about 0.5-0.65 s, so OpenCV only gets a second try when fewer labels than expected
were found.
"""

import cv2
import numpy as np

EXPECTED_LABELS = 2   # one per lot, two lots per tray


class Label:
    """One QR code: its text and its 4 corners in photo pixels
    (top-left, top-right, bottom-right, bottom-left of the QR code itself)"""

    def __init__(self, text, corners):
        self.text = text
        self.corners = np.asarray(corners, dtype=np.float64).reshape(4, 2)

    @property
    def centre(self):
        return self.corners.mean(axis=0)

    def __repr__(self):
        return "Label(%r)" % self.text


def read_labels(photo):
    """Every QR code in a BGR (or gray) photo, each text once"""
    gray = photo if photo.ndim == 2 else cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
    labels = _read_zxing(gray)
    if len(labels) < EXPECTED_LABELS:
        for label in _read_opencv(gray):
            if label.text not in {known.text for known in labels}:
                labels.append(label)
    return labels


def _read_zxing(gray):
    import zxingcpp

    labels = []
    for result in zxingcpp.read_barcodes(gray, formats=zxingcpp.BarcodeFormat.QRCode):
        if not result.valid or not result.text:
            continue
        p = result.position
        corners = [(p.top_left.x, p.top_left.y), (p.top_right.x, p.top_right.y),
                   (p.bottom_right.x, p.bottom_right.y), (p.bottom_left.x, p.bottom_left.y)]
        if result.text not in {label.text for label in labels}:
            labels.append(Label(result.text, corners))
    return labels


def _read_opencv(gray):
    try:
        found, texts, points, _ = cv2.QRCodeDetector().detectAndDecodeMulti(gray)
    except cv2.error:
        return []
    if not found or points is None:
        return []
    return [Label(text, corners) for text, corners in zip(texts, points) if text]
