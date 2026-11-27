"""Rotate mildly tilted images or rectify a four-corner perspective view."""

import cv2
import numpy as np


def resize_for_analysis(image, max_dimension=2200):
    if max_dimension <= 0:
        raise ValueError('max_dimension must be positive')
    h, w = image.shape[:2]
    factor = min(1.0, float(max_dimension) / max(w, h))
    if factor == 1:
        return image.copy(), factor
    return cv2.resize(image, (round(w * factor), round(h * factor)),
                      interpolation=cv2.INTER_AREA), factor


def _grid_alignment_score(gray, angle):
    h, w = gray.shape
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(gray, matrix, (w, h),
                             flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REFLECT_101)
    gx = cv2.Sobel(rotated, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(rotated, cv2.CV_32F, 0, 1, ksize=3)
    # Use the central portion to avoid the photograph/tray's outer border.
    xa, xb = round(.20*w), round(.85*w)
    ya, yb = round(.12*h), round(.88*h)
    p_x = np.abs(gx[ya:yb, xa:xb]).mean(axis=0)
    p_y = np.abs(gy[ya:yb, xa:xb]).mean(axis=1)
    p_x = cv2.GaussianBlur(p_x[None, :], (1, 7), 0).ravel()
    p_y = cv2.GaussianBlur(p_y[:, None], (1, 7), 0).ravel()
    return float(p_x.std() / max(1., p_x.mean()) +
                 p_y.std() / max(1., p_y.mean()))


def estimate_rotation(image, max_degrees=15):
    """Find the angle yielding the strongest repeating vertical/horizontal walls."""
    h, w = image.shape[:2]
    scale = min(1., 750. / max(w, h))
    small = cv2.resize(image, (round(w * scale), round(h * scale)),
                       interpolation=cv2.INTER_AREA) if scale < 1. else image
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    # Coarse-to-fine optimization is more stable and faster than a single Hough
    # line direction (which often finds the big outside frame instead).
    candidates = np.arange(-max_degrees, max_degrees + .01, 1.0)
    scores = [(_grid_alignment_score(gray, float(a)), float(a)) for a in candidates]
    best = max(scores)[1]
    fine = np.arange(max(-max_degrees, best - 1.),
                     min(max_degrees, best + 1.) + .01, .2)
    return max(fine, key=lambda a: _grid_alignment_score(gray, float(a)))


def _rotate_expand(image, angle):
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.)
    c, s = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_w, new_h = int(np.ceil(h * s + w * c)), int(np.ceil(h * c + w * s))
    matrix[0, 2] += (new_w - w) / 2
    matrix[1, 2] += (new_h - h) / 2
    return cv2.warpAffine(image, matrix, (new_w, new_h),
                          borderValue=(25, 25, 25)), matrix


def rectify_image(image, max_dimension=2200, rotation='auto', corners=None):
    """Return working image, applied angle, processing scale, and correction mode.

    Corners are clockwise (TL,TR,BR,BL) in ORIGINAL image coordinates and
    should mark the four outer grid corners (not the wooden holder edges).
    """
    working, scale = resize_for_analysis(image, max_dimension)
    if corners is not None:
        pts = np.asarray(corners, dtype=np.float32)
        if pts.shape != (4, 2):
            raise ValueError('corners must be four x,y pairs (TL TR BR BL)')
        pts = pts * scale
        width = round(max(np.linalg.norm(pts[1] - pts[0]),
                          np.linalg.norm(pts[2] - pts[3])))
        height = round(max(np.linalg.norm(pts[3] - pts[0]),
                           np.linalg.norm(pts[2] - pts[1])))
        if min(width, height) < 100:
            raise ValueError('Perspective corner coordinates are too close together')
        target = np.float32([[0, 0], [width-1, 0],
                             [width-1, height-1], [0, height-1]])
        H = cv2.getPerspectiveTransform(pts, target)
        return cv2.warpPerspective(working, H, (width, height)), 0., scale, 'manual-perspective'
    angle = estimate_rotation(working) if rotation == 'auto' else float(rotation)
    if abs(angle) < .05:
        return working, angle, scale, 'unrotated'
    result, _ = _rotate_expand(working, angle)
    return result, float(angle), scale, 'auto-rotation' if rotation == 'auto' else 'manual-rotation'


def select_corners(image):
    """Interactively click TL,TR,BR,BL on the original picture, Enter to accept."""
    h, w = image.shape[:2]
    scale = min(1., 1050. / max(h, w))
    shown = cv2.resize(image, (round(w*scale), round(h*scale)))
    points = []
    window = 'Click four OUTER grid corners: TL, TR, BR, BL | Enter accept | R reset'

    def on_mouse(event, x, y, flags, userdata):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append((x / scale, y / scale))
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)
    try:
        while True:
            frame = shown.copy()
            for i, (x, y) in enumerate(points):
                cv2.circle(frame, (int(x * scale), int(y * scale)), 6, (0,255,0), -1)
                cv2.putText(frame, str(i+1), (int(x*scale)+6, int(y*scale)-6),
                            cv2.FONT_HERSHEY_SIMPLEX, .65, (0,255,255), 2)
            cv2.imshow(window, frame)
            key = cv2.waitKey(25) & 0xff
            if key in (13, 10) and len(points) == 4:
                return points
            if key in (ord('r'), ord('R')):
                points.clear()
            if key in (27, ord('q')):
                raise RuntimeError('Corner selection canceled')
    finally:
        cv2.destroyWindow(window)
