"""Conservative green-plant segmentation and per-pixel leaf measurements.

Leaf counts and bounding-box lengths are ESTIMATES if leaves overlap. Total
cell foliage area is counted from the accepted binary mask, without assigning
watershed boundary pixels to background.
"""

from typing import List, Tuple

import cv2
import numpy as np
from openpyxl.utils import get_column_letter

import config
from models import CellResult, GridInfo, LeafMeasurement


def _green_mask(roi: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    b, g, r = cv2.split(roi.astype(np.float32))
    exg = 2. * g - r - b
    relative = exg / np.maximum(r + g + b, 1.)
    good_hsv = cv2.inRange(hsv,
                          (config.GREEN_H_MIN, config.GREEN_S_MIN, config.GREEN_V_MIN),
                          (config.GREEN_H_MAX, 255, 255)) > 0
    good_green = ((exg >= config.EXCESS_GREEN_MIN) &
                  (relative >= config.NORMALIZED_EXCESS_GREEN_MIN) &
                  (g >= config.MIN_GREEN_TO_RED_RATIO * (r + 1)))
    mask = (good_hsv & good_green).astype(np.uint8) * 255
    if config.LEAF_OPEN_KERNEL >= 3:
        k = config.LEAF_OPEN_KERNEL | 1
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    if config.LEAF_CLOSE_KERNEL >= 3:
        k = config.LEAF_CLOSE_KERNEL | 1
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    return mask


def _accepted_plant_mask(mask: np.ndarray) -> np.ndarray:
    """Keep sizeable nearby plant parts; reject isolated and peripheral specks."""
    h, w = mask.shape
    cell_area = float(h*w)
    min_part = max(4, int(cell_area * config.MIN_LEAF_AREA_FRACTION))
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    candidates = []
    for i in range(1, count):
        area = int(stats[i, cv2.CC_STAT_AREA])
        cx, cy = centroids[i]
        if area < min_part or area > cell_area * config.MAX_LEAF_AREA_FRACTION:
            continue
        # Parts that lie near the outer analysis ROI edge are often tray walls.
        if not (.06*w < cx < .94*w and .06*h < cy < .94*h):
            continue
        candidates.append((area, i, cx, cy))
    if not candidates:
        return np.zeros_like(mask)
    candidates.sort(reverse=True)
    _, seed_label, cx, cy = candidates[0]
    # A tiny isolated patch at the edge should not be treated as a seedling.
    if abs(cx-w/2) > .40*w or abs(cy-h/2) > .40*h:
        return np.zeros_like(mask)
    keep = [seed_label]
    for _, i, x, y in candidates[1:]:
        if np.hypot((x-cx)/w, (y-cy)/h) <= .30:
            keep.append(i)
    accepted = np.isin(labels, keep).astype(np.uint8) * 255
    if np.count_nonzero(accepted) < cell_area * config.MIN_PLANT_AREA_FRACTION:
        return np.zeros_like(mask)
    return accepted


def _contour_touches_boundary(contour, width, height):
    x, y, w, h = cv2.boundingRect(contour)
    m = config.BOUNDARY_REVIEW_MARGIN_PX
    return x <= m or y <= m or x+w >= width-m or y+h >= height-m


def _bgr_to_hex(values):
    b, g, r = [max(0, min(255, round(x))) for x in values]
    return f'#{r:02X}{g:02X}{b:02X}'


def _split_component(roi: np.ndarray, component: np.ndarray):
    """Estimate overlapping leaves from separate local foliage-thickness peaks.

    A leaf is NOT guaranteed to be distinguishable when touching neighbors.
    The full union mask is measured separately to keep total area accurate.
    """
    if not config.SPLIT_TOUCHING_LEAVES:
        return [component], False
    dist = cv2.distanceTransform(component, cv2.DIST_L2, 5)
    maximum = float(dist.max())
    if maximum < 2.8:
        return [component], False
    smooth = cv2.GaussianBlur(dist, (3, 3), .7)
    radius = max(3, round(min(component.shape) * .09))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius+1, 2*radius+1))
    local_max = ((smooth >= cv2.dilate(smooth, kernel) - 0.0001) &
                 (smooth > max(1.8, .38*maximum))).astype(np.uint8)
    n, peaks, stats, centers = cv2.connectedComponentsWithStats(local_max, 8)
    if n <= 2:
        return [component], False
    options = sorted([(float(smooth[int(y),int(x)]), float(x), float(y))
                      for x,y in centers[1:]], reverse=True)
    selected = []
    for strength,x,y in options:
        if all(np.hypot(x-px,y-py) > min(component.shape)*.12
               for _,px,py in selected):
            selected.append((strength,x,y))
        if len(selected) >= 6:
            break
    if len(selected) < 2:
        return [component], False
    seeds = np.zeros_like(component)
    for i, (_,x,y) in enumerate(selected, start=1):
        cv2.circle(seeds, (round(x),round(y)), 2, i, -1)
    seeds[component == 0] = 0
    # Mark exterior as known background, leaf pixels other than seed cores as
    # unknown. Distance-map watershed splits at the narrowest leaf junctions.
    labels = seeds.astype(np.int32) + 1
    labels[(component > 0) & (seeds == 0)] = 0
    topology = (255 - np.round(245 * dist / maximum)).astype(np.uint8)
    landscape = cv2.cvtColor(topology, cv2.COLOR_GRAY2BGR)
    partitions = cv2.watershed(landscape, labels)
    min_pixels = max(4, component.size * config.MIN_SPLIT_REGION_AREA_FRACTION)
    regions = []
    for i in range(2, len(selected)+2):
        region = ((partitions == i) & (component > 0)).astype(np.uint8)*255
        if cv2.countNonZero(region) >= min_pixels:
            regions.append(region)
    if len(regions) < 2:
        return [component], False
    return regions, True


def _measure_region(region, roi, origin, grid, leaf_number, split):
    # Pixel count, not contourArea: this preserves thin edge pixels and holes.
    area_px = int(cv2.countNonZero(region))
    contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    biggest = max(contours, key=cv2.contourArea)
    pts = np.concatenate([c.reshape(-1, 2) for c in contours], axis=0).astype(np.float32)
    pts[:, 0] *= grid.mm_per_px_x
    pts[:, 1] *= grid.mm_per_px_y
    rect = cv2.minAreaRect(pts.reshape(-1, 1, 2))
    length, width = sorted(rect[1], reverse=True)
    moments = cv2.moments(region, binaryImage=True)
    cx = moments['m10'] / moments['m00']
    cy = moments['m01'] / moments['m00']
    color = cv2.mean(roi, mask=region)[:3]
    flag = 'ESTIMATED_SPLIT' if split else 'OK'
    if _contour_touches_boundary(biggest, region.shape[1], region.shape[0]):
        flag = 'REVIEW_BOUNDARY'
    return LeafMeasurement(
        leaf_number=leaf_number, length_mm=float(length), width_mm=float(width),
        area_mm2=area_px * grid.mm_per_px_x * grid.mm_per_px_y,
        area_px=float(area_px), center_x_px=float(origin[0]+cx),
        center_y_px=float(origin[1]+cy),
        mean_bgr=tuple(float(v) for v in color), mean_hex=_bgr_to_hex(color),
        quality_flag=flag)


def analyze_cells(image: np.ndarray, grid: GridInfo):
    results: List[CellResult] = []
    full_mask = np.zeros(image.shape[:2], np.uint8)
    contour_records = []
    for row in range(grid.rows):
        for col in range(grid.columns):
            left, right = grid.x_lines[col], grid.x_lines[col+1]
            top, bottom = grid.y_lines[row], grid.y_lines[row+1]
            w, h = right-left, bottom-top
            x0 = max(0, left+round(w*config.CELL_INSET_FRACTION))
            x1 = min(image.shape[1], right-round(w*config.CELL_INSET_FRACTION))
            y0 = max(0, top+round(h*config.CELL_INSET_FRACTION))
            y1 = min(image.shape[0], bottom-round(h*config.CELL_INSET_FRACTION))
            cell_name = f'{get_column_letter(col+1)}{row+1}'
            if x1 <= x0 or y1 <= y0:
                results.append(CellResult(row+1, col+1, cell_name,
                                          (left,top,right,bottom), 'INVALID_CELL',
                                          quality_flag='REVIEW'))
                continue
            roi = image[y0:y1, x0:x1]
            foliage = _accepted_plant_mask(_green_mask(roi))
            full_mask[y0:y1,x0:x1] = foliage
            count, labels, stats, centers = cv2.connectedComponentsWithStats(foliage, 8)
            leaf_regions = []
            for i in range(1, count):
                part = (labels == i).astype(np.uint8)*255
                leaves_split, split = _split_component(roi, part)
                for region in leaves_split:
                    if cv2.countNonZero(region) >= max(4, foliage.size * config.MIN_LEAF_AREA_FRACTION):
                        leaf_regions.append((region,split))
            leaf_regions.sort(key=lambda r: cv2.boundingRect(cv2.findContours(r[0], cv2.RETR_EXTERNAL,
                                                                   cv2.CHAIN_APPROX_SIMPLE)[0][0])[0])
            leaves = []
            for leaf_index, (region, split) in enumerate(leaf_regions, 1):
                leaf = _measure_region(region, roi, (x0,y0), grid, leaf_index, split)
                leaves.append(leaf)
                contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for contour in contours:
                    contour[:, 0, 0] += x0
                    contour[:, 0, 1] += y0
                    contour_records.append((row+1, col+1, leaf_index, contour, leaf))
            status = 'SEEDLING' if cv2.countNonZero(foliage) else 'NO_SEEDLING'
            # Summed union foliage area is retained even when watershed divides
            # individual leaf regions imperfectly.
            cell_area = cv2.countNonZero(foliage) * grid.mm_per_px_x * grid.mm_per_px_y
            quality = 'REVIEW' if any(l.quality_flag == 'REVIEW_BOUNDARY' for l in leaves) else 'OK'
            results.append(CellResult(row+1, col+1, cell_name,
                                      (left,top,right,bottom),status,leaves,
                                      float(cell_area), quality))
    return results, full_mask, contour_records
