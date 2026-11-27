"""Backend for Tab 1 (Image Processing): seedling trays, one photo at a time

The GUI calls:

    start_batch()                           -> once before a run
    process_image(image_path)               -> once per photo, returns a dict (see below)
    describe(data, retaken)                 -> ("ok" / "warning" / "skipped", status text)
    find_retakes(results)                   -> which lots were photographed again later
    export_results_to_excel(results, path)  -> "Save Excel file" (tray_report.py)
    cleanup()                               -> delete the "check this" pictures

For each photo:
  1. Read the QR-code labels on the FULL-SIZE photo (qr_reader.py)
  2. Find the tray's cells and straighten the tray to 128 pixels per cell (tray_grid.py)
  3. Find and measure the seedlings in every cell (vision/, the Prototype-Bounding-Boxes
     repo's Version3 code, unchanged)
  4. Mark the cells under a label as "covered", split the tray into its two lots
     (12 x 12 halves) and give each half the label lying on it

A tray holds two lots side by side, each with its own label. The halves are measured
separately, the photo's status and its tray map show both.

If a photo has a problem (no label, only part of the tray found...), a marked-up copy
is saved in a temporary folder, for the GUI to open on double-click. cleanup() deletes
it; the folder of a run that crashed is deleted the next time the program starts.
"""

import datetime
import os
import re
import shutil
import sys
import tempfile

import numpy as np

_VISION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision")
if _VISION not in sys.path:
    sys.path.insert(0, _VISION)

import cv2  # noqa: E402

import config  # noqa: E402  (vision/config.py)
import label_backend  # noqa: E402
import qr_reader  # noqa: E402
import tray_grid  # noqa: E402
from leaf_analysis import analyze_cells  # noqa: E402
from models import GridInfo  # noqa: E402

CELL_PITCH_IN = 1.0   # ASSUMED centre-to-centre cell spacing, not measured yet
LABEL_DPI = label_backend.DEFAULT_DPI  # for the QR code's printed size
COVERED_FRACTION = 0.3   # a cell this much under a label can't be judged
CHECK_IMAGE_WIDTH = 2400
CHECK_DIR_PREFIX = "TobaccoVisionGUI-check-"

# Statuses of a cell
SEEDLING = "SEEDLING"
EMPTY = "NO_SEEDLING"
COVERED = "COVERED"
INVALID = "INVALID_CELL"

_LABEL_TEXT = re.compile(r"^Bay(\d+)-([A-Za-z0-9]+)-(\d+)$", re.IGNORECASE)


class SkipPhoto(Exception):
    """Raise from process_image to skip a photo without calling it a failure"""


class PhotoFailed(Exception):
    """A photo that could not be analysed. check_image is a marked-up copy, or None"""

    def __init__(self, message, check_image=None):
        super().__init__(message)
        self.check_image = check_image


def _tune_vision():
    """vision/'s settings for the straightened 128 px-per-cell tray. See README"""
    config.CELL_PITCH_X_IN = config.CELL_PITCH_Y_IN = CELL_PITCH_IN


_tune_vision()


# Batch and temporary files


_check_dir = None


def start_batch():
    """Forget the previous run, including its check pictures"""
    cleanup()


def cleanup():
    """Delete this run's check pictures"""
    global _check_dir
    if _check_dir is not None:
        shutil.rmtree(_check_dir, ignore_errors=True)
        _check_dir = None


def remove_stale_check_folders():
    """Delete check-picture folders left behind by a copy of the program that crashed"""
    root = tempfile.gettempdir()
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        if not name.startswith(CHECK_DIR_PREFIX):
            continue
        try:
            pid = int(name[len(CHECK_DIR_PREFIX):].split("-")[0])
        except ValueError:
            continue
        if pid != os.getpid() and not _process_running(pid):
            shutil.rmtree(os.path.join(root, name), ignore_errors=True)


def _process_running(pid):
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _check_image_path(photo_path):
    global _check_dir
    if _check_dir is None or not os.path.isdir(_check_dir):
        _check_dir = tempfile.mkdtemp(prefix="%s%d-" % (CHECK_DIR_PREFIX, os.getpid()))
    stem = os.path.splitext(os.path.basename(photo_path))[0]
    return os.path.join(_check_dir, "%s_check.jpg" % stem)


# One photo


def load_photo(path):
    """BGR image, turned upright as the camera recorded it"""
    if not os.path.isfile(path):
        raise PhotoFailed("photo not found")
    try:
        data = np.fromfile(path, dtype=np.uint8)  # works with any characters in the path
    except OSError as error:
        raise PhotoFailed("could not open the photo (%s)" % error.strerror) from error
    photo = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if photo is None:
        raise PhotoFailed("not a photo, or the file is damaged")
    return photo


def photo_taken(path):
    """When the camera took the photo ("YYYY-MM-DD HH:MM:SS"), or None"""
    try:
        from PIL import Image

        with Image.open(path) as image:
            exif = image.getexif()
            taken = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal, DateTime
            sub = exif.get_ifd(0x8769).get(37521)                     # SubsecTimeOriginal
    except Exception:
        return None
    if not taken:
        return None
    try:
        when = datetime.datetime.strptime(str(taken).strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    text = when.strftime("%Y-%m-%d %H:%M:%S")
    if sub and str(sub).strip().isdigit():
        text += "." + str(sub).strip()
    return text


def process_image(image_path):
    """Analyse ONE tray photo. Returns a dict, see analyse_photo"""
    photo = load_photo(image_path)
    return analyse_photo(photo, image_path)


def analyse_photo(photo, image_path, cell_px=tray_grid.CELL_PX, make_check_image=True):
    labels = qr_reader.read_labels(photo)                       # 1. full size
    location = tray_grid.locate_tray(photo)                     # 2.
    if location is None:
        check = None
        if make_check_image:
            check = _save_failed_check(photo, labels, image_path, "tray not found")
        raise PhotoFailed("tray not found", check)
    tray = tray_grid.straighten(photo, location, cell_px)

    grid = _even_grid(location.rows, location.columns, cell_px)   # 3.
    cells, _, contours = analyze_cells(tray, grid)

    label_shapes = [_label_in_tray(label, location) for label in labels]   # 4.
    covered = _covered_cells(label_shapes, location.rows, location.columns)
    sections = _sections(location.rows, location.columns, location.complete)
    warnings = []
    if not location.complete:
        warnings.append("only %d x %d cells found" % (location.rows, location.columns))
    _assign_labels(sections, labels, label_shapes, warnings)

    cell_rows = []
    for cell in cells:
        row, column = cell.row - 1, cell.column - 1
        status = cell.status
        if (row, column) in covered:
            status = COVERED
        record = {
            "row": cell.row, "column": cell.column, "name": cell.excel_cell,
            "section": _section_of(sections, row, column),
            "status": status, "area": 0.0, "leaves": 0, "color": None,
            "quality": cell.quality_flag,
        }
        if status == SEEDLING:
            record["area"] = float(cell.total_leaf_area_mm2)
            record["leaves"] = len(cell.leaves)
            record["color"] = _cell_color(cell)
        cell_rows.append(record)

    pitches = [shape["pitch_in"] for shape in label_shapes if shape["pitch_in"]]
    data = {
        "file": os.path.basename(image_path),
        "path": image_path,
        "taken": photo_taken(image_path),
        "rows": location.rows,
        "columns": location.columns,
        "complete": location.complete,
        "sections": sections,
        "cells": cell_rows,
        "warnings": warnings,
        "pitch_in_from_qr": float(np.mean(pitches)) if pitches else None,
        "check_image": None,
    }
    if warnings and make_check_image:
        data["check_image"] = _save_check(tray, data, contours, label_shapes, cell_px,
                                          image_path)
    return data


def _even_grid(rows, columns, cell_px):
    mm_per_px = CELL_PITCH_IN * config.MM_PER_INCH / cell_px
    return GridInfo(
        x_lines=[c * cell_px for c in range(columns + 1)],
        y_lines=[r * cell_px for r in range(rows + 1)],
        pitch_x_px=float(cell_px), pitch_y_px=float(cell_px),
        mm_per_px_x=mm_per_px, mm_per_px_y=mm_per_px,
        correction_mode="cell-lattice",
    )


def _cell_color(cell):
    """Leaf-area-weighted mean color (B, G, R) of a cell's leaves"""
    total = sum(leaf.area_px for leaf in cell.leaves)
    if not total:
        return None
    return tuple(
        sum(leaf.area_px * leaf.mean_bgr[k] for leaf in cell.leaves) / total for k in range(3)
    )


# Labels on the tray


def _label_in_tray(label, location):
    """The whole 3 x 1 inch label's outline in tray cell units, worked out from where
    its QR code is, plus the cell spacing its printed size implies"""
    width, height = label_backend._label_size_dots(LABEL_DPI)
    modules = len(label_backend._make_qr_matrix(label.text))
    module, edge = label_backend._qr_layout(modules, height, label_backend._safe_margin_dots(LABEL_DPI))
    shape = {"text": label.text, "outline": None, "qr": None, "pitch_in": None}
    qr_u, qr_v = location.photo_to_cells(label.corners[:, 0], label.corners[:, 1])
    qr_cells = np.stack([qr_u, qr_v], axis=1)
    shape["qr"] = qr_cells
    if module is None:
        return shape
    size = modules * module
    top = (height - size) / 2.0
    qr_on_label = np.float32([[edge, top], [edge + size, top],
                              [edge + size, top + size], [edge, top + size]])
    matrix = cv2.getPerspectiveTransform(qr_on_label, qr_cells.astype(np.float32))
    label_corners = np.float32([[0, 0], [width, 0], [width, height], [0, height]]).reshape(-1, 1, 2)
    shape["outline"] = cv2.perspectiveTransform(label_corners, matrix).reshape(4, 2)
    # Cell spacing implied by the QR code's printed size (if printed at LABEL_DPI)
    side_cells = np.mean([np.linalg.norm(qr_cells[i] - qr_cells[(i + 1) % 4]) for i in range(4)])
    if side_cells > 0:
        shape["pitch_in"] = (size / float(LABEL_DPI)) / side_cells
    return shape


def _covered_cells(label_shapes, rows, columns, px=16):
    """Cells that are at least COVERED_FRACTION under a label"""
    mask = np.zeros((rows * px, columns * px), np.uint8)
    for shape in label_shapes:
        if shape["outline"] is not None:
            cv2.fillPoly(mask, [np.round(shape["outline"] * px).astype(np.int32)], 1)
    covered = set()
    for r in range(rows):
        for c in range(columns):
            if mask[r * px:(r + 1) * px, c * px:(c + 1) * px].mean() >= COVERED_FRACTION:
                covered.add((r, c))
    return covered


def _sections(rows, columns, complete):
    """The lots in the photo: two 12 x 12 halves of a whole tray, else one part"""
    half_r, half_c = tray_grid.TRAY_ROWS, tray_grid.TRAY_COLUMNS // 2
    if complete and (rows, columns) == (half_r, 2 * half_c):
        parts = [("Left half", (0, rows), (0, half_c)), ("Right half", (0, rows), (half_c, columns))]
    elif complete and (rows, columns) == (2 * half_c, half_r):
        parts = [("Top half", (0, half_c), (0, columns)), ("Bottom half", (half_c, rows), (0, columns))]
    else:
        parts = [("Whole photo", (0, rows), (0, columns))]
    return [{"name": name, "rows": r, "columns": c, "label": None, "bay": None,
             "variant": None, "lot": None, "warnings": []} for name, r, c in parts]


def _section_of(sections, row, column):
    for index, section in enumerate(sections):
        if section["rows"][0] <= row < section["rows"][1] and \
                section["columns"][0] <= column < section["columns"][1]:
            return index
    return 0


def _assign_labels(sections, labels, label_shapes, warnings):
    """Give each half the label lying on it (or nearest to it)"""
    found = [[] for _ in sections]
    for label, shape in zip(labels, label_shapes):
        u, v = shape["qr"].mean(axis=0)

        def distance(section):
            (r0, r1), (c0, c1) = section["rows"], section["columns"]
            return np.hypot(max(c0 - u, 0, u - c1), max(r0 - v, 0, v - r1))

        nearest = min(range(len(sections)), key=lambda i: distance(sections[i]))
        found[nearest].append(label.text)
    for section, texts in zip(sections, found):
        where = section["name"].lower()
        if len(texts) == 1:
            section["label"] = texts[0]
            match = _LABEL_TEXT.match(texts[0])
            if match:
                section["bay"] = int(match.group(1))
                section["variant"] = match.group(2)
                section["lot"] = int(match.group(3))
            else:
                warning = 'unknown label "%s"' % texts[0]
                section["warnings"].append(warning)
                warnings.append(warning)
        elif not texts:
            warning = "no label found" if len(sections) == 1 else "no label on the %s" % where
            section["warnings"].append(warning)
            warnings.append(warning)
        else:
            warning = "%d labels on the %s: %s" % (len(texts), where, ", ".join(texts))
            section["warnings"].append(warning)
            warnings.append(warning)


# Status text and retakes


def find_retakes(results):
    """Lots photographed again in a later photo (usually because the first was blurry).

    results: the GUI's list of {"ok", "data", ...}. Returns {index in results:
    {section index: file name of the newer photo}}. Newer means taken later by the
    camera's clock, or later in the list when a photo has no date."""
    entries = []
    for index, result in enumerate(results):
        data = result.get("data") if result.get("ok") else None
        if not isinstance(data, dict) or "sections" not in data:
            continue
        for s_index, section in enumerate(data["sections"]):
            if section.get("label"):
                entries.append((section["label"], index, s_index, data.get("taken"), data["file"]))
    all_dated = all(taken for _, _, _, taken, _ in entries)
    newest = {}
    for label, index, s_index, taken, name in entries:
        rank = (taken if all_dated else "", index)
        if label not in newest or rank > newest[label][0]:
            newest[label] = (rank, index, name)
    retaken = {}
    for label, index, s_index, taken, name in entries:
        _, newest_index, newest_name = newest[label]
        if newest_index != index:
            retaken.setdefault(index, {})[s_index] = newest_name
    return retaken


def whole_photo_retaken(data, retaken_sections):
    """True when every labelled lot in the photo was photographed again later"""
    labelled = [i for i, s in enumerate(data["sections"]) if s.get("label")]
    return bool(labelled) and all(i in retaken_sections for i in labelled)


def describe(data, retaken_sections=None):
    """("ok" | "warning" | "skipped", status text) for the photo list"""
    retaken_sections = retaken_sections or {}
    if not isinstance(data, dict) or "sections" not in data:
        return "ok", ""
    if whole_photo_retaken(data, retaken_sections):
        newer = sorted(set(retaken_sections.values()))
        return "skipped", "retaken in %s" % ", ".join(newer)
    parts = []
    for index, section in enumerate(data["sections"]):
        if section.get("label"):
            text = section["label"]
            if index in retaken_sections:
                text += " (retaken in %s)" % retaken_sections[index]
            parts.append(text)
    warnings = list(data["warnings"])
    if not parts and all(w.startswith("no label") for w in data["warnings"]
                         if not w.startswith("only")):
        # no half has a label: say it once
        warnings = ["no label found"] + [w for w in warnings if w.startswith("only")]
    text = ",  ".join(parts)
    if warnings:
        text = (text + "  -  " if text else "") + "; ".join(warnings)
    return ("warning" if warnings else "ok"), text


# Check pictures


def _save_check(tray, data, contours, label_shapes, cell_px, image_path):
    """The straightened tray with the grid, seedlings, labels and problems drawn on"""
    picture = tray.copy()
    rows, columns = data["rows"], data["columns"]
    for record in data["cells"]:
        r, c = record["row"] - 1, record["column"] - 1
        x0, y0 = c * cell_px, r * cell_px
        if record["status"] == COVERED:   # hatched, drawn inside the cell only
            inside = picture[y0:y0 + cell_px, x0:x0 + cell_px]
            for k in range(0, 2 * cell_px, 16):
                cv2.line(inside, (k, 0), (0, k), (255, 160, 0), 2)
        elif record["status"] == EMPTY:
            cv2.rectangle(picture, (x0 + 6, y0 + 6), (x0 + 18, y0 + 18), (0, 165, 255), -1)
    for c in range(columns + 1):
        cv2.line(picture, (c * cell_px, 0), (c * cell_px, rows * cell_px), (200, 200, 200), 1)
    for r in range(rows + 1):
        cv2.line(picture, (0, r * cell_px), (columns * cell_px, r * cell_px), (200, 200, 200), 1)
    for *_, contour, _ in contours:
        cv2.drawContours(picture, [contour], -1, (255, 0, 255), 2)
    for section in data["sections"][1:]:   # the line between the two lots
        (r0, _), (c0, _) = section["rows"], section["columns"]
        if c0:
            cv2.line(picture, (c0 * cell_px, 0), (c0 * cell_px, rows * cell_px), (0, 255, 255), 5)
        else:
            cv2.line(picture, (0, r0 * cell_px), (columns * cell_px, r0 * cell_px), (0, 255, 255), 5)
    for shape in label_shapes:
        if shape["outline"] is not None:
            points = np.round(shape["outline"] * cell_px).astype(np.int32)
            cv2.polylines(picture, [points], True, (255, 255, 0), 4)
    lines = [data["file"]] + ["- " + w for w in data["warnings"]]
    return _write_check(picture, lines, image_path)


def _save_failed_check(photo, labels, image_path, problem):
    picture = photo.copy()
    for label in labels:
        cv2.polylines(picture, [np.round(label.corners).astype(np.int32)], True, (255, 255, 0), 8)
    lines = [os.path.basename(image_path), "- " + problem]
    try:
        return _write_check(picture, lines, image_path)
    except Exception:
        return None


def _write_check(picture, lines, image_path):
    scale = min(1.0, CHECK_IMAGE_WIDTH / picture.shape[1])
    if scale < 1.0:
        picture = cv2.resize(picture, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    line_height = 44
    banner = np.full((line_height * len(lines) + 16, picture.shape[1], 3), 255, np.uint8)
    for i, text in enumerate(lines):
        cv2.putText(banner, text, (14, 38 + i * line_height), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                    (0, 0, 180) if i else (0, 0, 0), 2, cv2.LINE_AA)
    picture = np.vstack([banner, picture])
    path = _check_image_path(image_path)
    ok, encoded = cv2.imencode(".jpg", picture, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return None
    encoded.tofile(path)
    return path


def export_results_to_excel(results, output_path):
    """Write the results of a finished batch to one Excel file"""
    import tray_report

    tray_report.export(results, output_path)


def self_test():
    """Analyse a drawn tray with two labels. Raises on failure"""
    import tray_testing

    photo, texts = tray_testing.synthetic_tray()
    data = analyse_photo(photo, "self-test.jpg", make_check_image=False)
    labels = [s["label"] for s in data["sections"]]
    if (data["rows"], data["columns"]) != (12, 24) or not data["complete"]:
        raise AssertionError("The test tray's grid came out %dx%d" % (data["rows"], data["columns"]))
    if labels != texts:
        raise AssertionError("The test labels were read as %r" % labels)
    seedlings = sum(1 for c in data["cells"] if c["status"] == SEEDLING)
    if seedlings < 200:
        raise AssertionError("Only %d test seedlings were found" % seedlings)
    return True


remove_stale_check_folders()
