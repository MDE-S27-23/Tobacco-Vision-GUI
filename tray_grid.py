"""Find the tray's cells in a photo and straighten the tray to a standard picture

vision/grid_detection.py finds the cell walls by how strongly the brightness changes at
their edges, and drops outer walls whose edges look weak. On the customer's styrofoam
float trays the outermost walls run straight into the tray's wide white rim, so whole
edge rows or columns got dropped, which shifts every cell name (A1 is no longer the real
A1). Zoomed-out photos also confused it with the background.

This module finds the cells themselves instead: each one is a dark square of soil inside
bright walls. From the squares it works out where every cell of the tray is, also
correcting a slightly tilted camera (perspective), adds edge rows/columns that are
hidden or dim, and then straightens the tray into a picture with exactly CELL_PX pixels
per cell, taken from the full-size photo. vision/'s leaf analysis then runs on that
picture with a perfectly even grid, so its pixel-based settings mean the same thing for
every photo, close-up or zoomed out.
"""

import os
import sys

import cv2
import numpy as np

_VISION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision")
if _VISION not in sys.path:
    sys.path.insert(0, _VISION)   # vision/ modules import each other by plain name

TRAY_ROWS = 12      # 288-cell float tray, two lots of 12 x 12 side by side
TRAY_COLUMNS = 24
CELL_PX = 128       # pixels per cell in the straightened tray (about a 3200 px wide photo)
WORKING_SIZE = 3200  # longest side of the photo while looking for the cells

# A row or column is added at the tray's edge when its wall-vs-soil contrast is at
# least this fraction of a typical one
MIN_CELL_CONTRAST_FRACTION = 0.35
EVIDENCE_PX = 32    # pixels per cell while measuring that contrast


class TrayLocation:
    """Where the tray's cells are in the ORIGINAL photo

    Tray cell units: (0, 0) is the outer corner of the first cell, (columns, rows) the
    opposite corner. A homography handles a tilted camera, and a small polynomial on
    top of it handles the lens bending straight lines near the photo's edges."""

    def __init__(self, homography, bend_x, bend_y, offset, columns, rows, complete,
                 cell_size_px):
        self.homography = homography    # 3x3, found-cell units -> photo pixels
        self.bend_x = bend_x            # polynomial coefficients, see _bend_terms
        self.bend_y = bend_y
        self.offset = offset            # (column, row) of the tray's first cell in found units
        self.columns = columns
        self.rows = rows
        self.complete = complete
        self.cell_size_px = cell_size_px  # cell spacing in the original photo

    def cells_to_photo(self, u, v):
        """Tray cell units -> photo pixels (arrays of any shape)"""
        u = np.asarray(u, dtype=np.float64) + self.offset[0]
        v = np.asarray(v, dtype=np.float64) + self.offset[1]
        terms = _bend_terms(u, v)
        return _apply_homography(self.homography, u + terms @ self.bend_x,
                                 v + terms @ self.bend_y)

    def photo_to_cells(self, x, y):
        """Photo pixels -> tray cell units (inverse of cells_to_photo)"""
        u0, v0 = _apply_homography(np.linalg.inv(self.homography), x, y)
        u, v = u0, v0
        for _ in range(5):   # the bend is small, so this settles fast
            terms = _bend_terms(u, v)
            u, v = u0 - terms @ self.bend_x, v0 - terms @ self.bend_y
        return u - self.offset[0], v - self.offset[1]

    def sample(self, image, u0, u1, v0, v1, px, interpolation=cv2.INTER_LINEAR,
               border=cv2.BORDER_REPLICATE):
        """Straightened picture of tray cells u0..u1 x v0..v1, px pixels per cell"""
        xs = u0 + (np.arange(int(round((u1 - u0) * px))) + 0.5) / px
        ys = v0 + (np.arange(int(round((v1 - v0) * px))) + 0.5) / px
        u, v = np.meshgrid(xs, ys)
        map_x, map_y = self.cells_to_photo(u, v)
        return cv2.remap(image, map_x.astype(np.float32), map_y.astype(np.float32),
                         interpolation, borderMode=border)


def _apply_homography(matrix, x, y):
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    w = matrix[2, 0] * x + matrix[2, 1] * y + matrix[2, 2]
    return ((matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2]) / w,
            (matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2]) / w)


BEND_SCALE = 24.0   # keeps the polynomial terms near 1


def _bend_terms(u, v):
    """Cubic polynomial terms in cell units, shape (..., 10)"""
    a, b = np.asarray(u) / BEND_SCALE, np.asarray(v) / BEND_SCALE
    return np.stack([np.ones_like(a), a, b, a * a, a * b, b * b,
                     a * a * a, a * a * b, a * b * b, b * b * b], axis=-1)


# Finding the cells


def _square_boxes(gray, min_cells):
    """Centres and sizes of the dark squares (cells), at the darkness level that
    separates them best. Stained walls join neighbouring cells at a high level,
    small or dim cells break up at a low one"""
    otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    height, width = gray.shape
    separate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    best = []
    for factor in (0.45, 0.6, 0.75, 0.9, 1.0):
        dark = (gray < otsu * factor).astype(np.uint8) * 255
        dark = cv2.erode(dark, separate)  # cut thin bridges across the walls
        contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w < 8 or h < 8 or w > width / 6 or h > height / 4:
                continue
            if not 0.7 <= w / h <= 1.43:
                continue
            if cv2.contourArea(contour) < 0.6 * w * h:  # a square, not a ragged blob
                continue
            boxes.append((x + w / 2, y + h / 2, (w + h) / 2 + 4))  # +4 undoes the erosion
        if len(boxes) < min_cells:
            continue
        typical = float(np.median([b[2] for b in boxes]))
        boxes = [b for b in boxes if 0.7 * typical <= b[2] <= 1.3 * typical]
        if len(boxes) > len(best):
            best = boxes
    return best


def _index_along(values, tolerance):
    """Group positions into rows (or columns) and number them, counting a skipped
    row/column. Returns (index per value or -1, number of rows/columns)"""
    order = np.argsort(values)
    groups = []
    for i in order:
        if groups and values[i] - values[groups[-1][-1]] < tolerance:
            groups[-1].append(i)
        else:
            groups.append([i])
    counts = np.array([len(g) for g in groups])
    # A real row/column has many cells, stray dark squares outside the tray don't
    keep = [g for g, c in zip(groups, counts) if c >= max(3, 0.25 * counts.max())]
    if len(keep) < 3:
        return None, 0
    centres = np.array([float(np.median(values[g])) for g in keep])
    pitch = float(np.median(np.diff(centres)))
    # Longest run with steady spacing (one or two missing rows/columns allowed)
    runs, run = [], [0]
    for k in range(1, len(keep)):
        steps = (centres[k] - centres[run[-1]]) / pitch
        if 0.7 <= steps <= 3.3 and abs(steps - round(steps)) < 0.3:
            run.append(k)
        else:
            runs.append(run)
            run = [k]
    runs.append(run)
    run = max(runs, key=len)
    index = np.full(len(values), -1)
    position = 0
    for n, k in enumerate(run):
        if n:
            position += int(round((centres[k] - centres[run[n - 1]]) / pitch))
        index[keep[k]] = position
    return index, position + 1


def _cell_contrast(evidence, k, axis, cross):
    """Wall brightness minus soil brightness for column k (axis=0) or row k (axis=1)
    of the evidence picture, measured over the rows (or columns) `cross`.
    None where it runs outside the photo"""
    gray, inside = evidence
    p = EVIDENCE_PX
    a, b = cross[0] * p, cross[1] * p
    if axis == 0:
        strip, ok = gray[a:b, k * p:(k + 1) * p], inside[a:b, k * p:(k + 1) * p]
        profile = strip.mean(axis=0) if strip.size else None
    else:
        strip, ok = gray[k * p:(k + 1) * p, a:b], inside[k * p:(k + 1) * p, a:b]
        profile = strip.mean(axis=1) if strip.size else None
    if profile is None or len(profile) != p or ok.mean() < 0.95:
        return None
    # Across the strip: walls at both ends, soil in the middle
    edge = max(2, p // 8)
    walls = min(profile[:edge].mean(), profile[-edge:].mean())
    soil = profile[p // 2 - p // 5:p // 2 + p // 5].mean()
    return float(walls - soil)


def locate_tray(photo, rows=TRAY_ROWS, columns=TRAY_COLUMNS, min_cells=24):
    """Find the tray in a photo (BGR, full size). Returns TrayLocation or None"""
    from rectification import estimate_rotation, resize_for_analysis, _rotate_expand

    working, scale = resize_for_analysis(photo, WORKING_SIZE)
    angle = estimate_rotation(working)
    turned, rotation = _rotate_expand(working, angle)
    to_turned = np.vstack([rotation, [0, 0, 1]]) @ np.diag([scale, scale, 1.0])

    gray = cv2.GaussianBlur(cv2.cvtColor(turned, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    boxes = _square_boxes(gray, min_cells)
    if len(boxes) < min_cells:
        return None
    boxes = np.array(boxes)
    typical = float(np.median(boxes[:, 2]))
    col_index, col_count = _index_along(boxes[:, 0], 0.5 * typical)
    row_index, row_count = _index_along(boxes[:, 1], 0.5 * typical)
    if col_index is None or row_index is None:
        return None
    found = (col_index >= 0) & (row_index >= 0)
    if found.sum() < min_cells:
        return None

    # Cell units -> turned photo, with perspective. RANSAC ignores misplaced squares
    cells = np.stack([col_index[found] + 0.5, row_index[found] + 0.5], axis=1).astype(np.float32)
    points = boxes[found, :2].astype(np.float32)
    homography, inliers = cv2.findHomography(cells, points, cv2.RANSAC, 0.2 * typical)
    if homography is None or inliers.sum() < min_cells:
        return None
    homography = np.linalg.inv(to_turned) @ homography

    # What's left over after the homography is the lens bending lines. Fit it.
    ideal = cells[inliers.ravel() > 0].astype(np.float64)
    photo_points = cv2.perspectiveTransform(
        points[inliers.ravel() > 0].reshape(-1, 1, 2).astype(np.float64),
        np.linalg.inv(to_turned)).reshape(-1, 2)
    seen_u, seen_v = _apply_homography(np.linalg.inv(homography),
                                       photo_points[:, 0], photo_points[:, 1])
    terms = _bend_terms(ideal[:, 0], ideal[:, 1])
    bend_x = np.linalg.lstsq(terms, seen_u - ideal[:, 0], rcond=None)[0]
    bend_y = np.linalg.lstsq(terms, seen_v - ideal[:, 1], rcond=None)[0]

    # A portrait photo (tray turned 90 degrees) has the long side going down
    if row_count > col_count:
        rows, columns = columns, rows

    location = TrayLocation(homography, bend_x, bend_y, (0, 0), col_count, row_count,
                            False, 0.0)
    # Grow (or trim) to the tray's size, judging each extra row/column by its contrast
    margin = 3
    gray_photo = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
    evidence = (
        location.sample(gray_photo, -margin, col_count + margin, -margin, row_count + margin,
                        EVIDENCE_PX).astype(np.float32),
        location.sample(np.ones_like(gray_photo), -margin, col_count + margin, -margin,
                        row_count + margin, EVIDENCE_PX, cv2.INTER_NEAREST,
                        cv2.BORDER_CONSTANT).astype(np.float32),
    )
    col_range, cols_ok = _grow(evidence, [0, col_count], columns, margin, 0, [0, row_count])
    row_range, rows_ok = _grow(evidence, [0, row_count], rows, margin, 1, col_range)

    location.offset = (col_range[0], row_range[0])
    location.columns = col_range[1] - col_range[0]
    location.rows = row_range[1] - row_range[0]
    location.complete = cols_ok and rows_ok
    x0, y0 = location.cells_to_photo(0, 0)
    x1, y1 = location.cells_to_photo(location.columns, location.rows)
    location.cell_size_px = float(np.hypot(x1 - x0, y1 - y0)
                                  / np.hypot(location.columns, location.rows))
    return location


def _grow(evidence, found_range, expected, margin, axis, cross_range):
    """Extend or trim [first, end) to `expected` rows/columns. Returns (range, complete)

    cross_range is the range of the other direction to measure over (cell units)"""
    gray, inside = evidence
    count = (gray.shape[1] if axis == 0 else gray.shape[0]) // EVIDENCE_PX
    cross = (cross_range[0] + margin, cross_range[1] + margin)

    def contrast(i):  # i in cell units, 0 = first found row/column
        k = i + margin
        if not 0 <= k < count:
            return None
        return _cell_contrast(evidence, k, axis, cross)

    first, end = found_range
    known = [c for c in (contrast(i) for i in range(first, end)) if c is not None]
    if not known:
        return found_range, end - first == expected
    floor = MIN_CELL_CONTRAST_FRACTION * float(np.median(known))
    while end - first > expected:  # trim the weaker end
        if (contrast(first) or 0) <= (contrast(end - 1) or 0):
            first += 1
        else:
            end -= 1
    while end - first < expected:
        before, after = contrast(first - 1), contrast(end)
        options = []
        if before is not None and before >= floor:
            options.append((before, -1))
        if after is not None and after >= floor:
            options.append((after, +1))
        if not options:
            return [first, end], False
        if max(options)[1] < 0:
            first -= 1
        else:
            end += 1
    return [first, end], True


def straighten(photo, location, cell_px=CELL_PX):
    """The tray alone, cell_px pixels per cell, straight and evenly spaced"""
    # Shrink first when the photo has much more detail than needed, so the result
    # averages pixels instead of skipping them
    factor = min(1.0, 1.5 * cell_px / location.cell_size_px)
    if factor < 1.0:
        small = cv2.resize(photo, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
        scaled = TrayLocation(np.diag([factor, factor, 1.0]) @ location.homography,
                              location.bend_x, location.bend_y, location.offset,
                              location.columns, location.rows, location.complete,
                              location.cell_size_px * factor)
        return scaled.sample(small, 0, location.columns, 0, location.rows, cell_px)
    return location.sample(photo, 0, location.columns, 0, location.rows, cell_px)
