"""A drawn tray photo for the self-test: 12 x 24 cells, seedlings and two QR labels"""

import cv2
import numpy as np

import label_backend

TEST_LABELS = ["Bay1-NC960-29", "Bay1-NC960-30"]


def synthetic_tray(pitch=130, seed=1):
    """(BGR photo, [left label text, right label text])"""
    rng = np.random.default_rng(seed)
    rows, columns = 12, 24
    margin = 3 * pitch
    height, width = rows * pitch + 2 * margin, columns * pitch + 2 * margin
    photo = np.full((height, width, 3), (215, 222, 226), np.uint8)      # table
    cv2.rectangle(photo, (margin - pitch // 2, margin - pitch // 2),
                  (width - margin + pitch // 2, height - margin + pitch // 2),
                  (170, 200, 215), -1)                                   # tray rim
    wall = pitch // 7
    for r in range(rows):
        for c in range(columns):
            x0, y0 = margin + c * pitch + wall // 2, margin + r * pitch + wall // 2
            x1, y1 = x0 + pitch - wall, y0 + pitch - wall
            cv2.rectangle(photo, (x0, y0), (x1, y1), (28, 30, 34), -1)   # soil
            if rng.random() < 0.85:                                      # a seedling
                cx, cy = (x0 + x1) // 2 + int(rng.integers(-15, 16)), (y0 + y1) // 2
                size = int(rng.integers(6, 14))
                for side in (-1, 1):
                    cv2.ellipse(photo, (cx + side * size, cy), (size, size * 2 // 3),
                                int(rng.integers(0, 180)), 0, 360, (60, 150, 70), -1)
    noise = rng.normal(0, 4, photo.shape)
    photo = np.clip(photo + noise, 0, 255).astype(np.uint8)
    # The labels lie flat on the top row of each half, three cells long
    for text, column in zip(TEST_LABELS, (2, 15)):
        bay, variant, lot = text[3:].split("-")
        stake = {"text": text, "bay": int(bay), "type": variant, "lot": int(lot)}
        label = np.array(label_backend._render_stake(stake, 203).convert("L"))
        label = cv2.cvtColor(cv2.resize(label, (3 * pitch, pitch), interpolation=cv2.INTER_AREA),
                             cv2.COLOR_GRAY2BGR)
        x, y = margin + column * pitch, margin
        photo[y:y + pitch, x:x + 3 * pitch] = label
    return photo, list(TEST_LABELS)
