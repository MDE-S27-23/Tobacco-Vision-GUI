"""The combined Excel report of a batch of tray photos (Tab 1's "Save Excel file")

Each photo holds two lots (the tray's halves), named by the QR label on each half.
Lots that were photographed again later (a retake) are left out, only the newest photo
of each lot is used. Sizes are the seedling's leaf area seen from above, in mm^2, and
assume the cell spacing in image_backend.CELL_PITCH_IN.

Sheets:
  Lots          one row per lot (tray half): label, bay, variant, lot and statistics
  By Variant    the same statistics with all lots of a variant pooled
  By Bay        ... of a bay pooled
  Distribution  how many seedlings fall in each size range, with a chart
  Cells         every cell of every lot, for filtering and pivot tables
  <photo>       one tray map per photo, cells colored by seedling size
  Settings      how the numbers were made, and photos that could not be used
"""

import datetime
import math
import os

import numpy as np
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import image_backend as ib

HEADER_FILL = PatternFill("solid", fgColor="DDEBF7")
EMPTY_FILL = PatternFill("solid", fgColor="FFE699")
COVERED_FILL = PatternFill("solid", fgColor="BFBFBF")
RETAKEN_FILL = PatternFill("solid", fgColor="EDEDED")
WARNING_FONT = Font(color="B00020")
BOLD = Font(bold=True)
THIN = Side(style="thin", color="A6A6A6")
THICK = Side(style="thick", color="000000")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)

STAT_HEADERS = [
    "Cells", "Seedlings", "Empty cells", "Covered by label", "Seedling presence (%)",
    "Mean size (mm²)", "SD (mm²)", "Median (mm²)", "Q1 (mm²)", "Q3 (mm²)", "IQR (mm²)",
    "Min (mm²)", "Max (mm²)", "Mean leaf color",
]


# Statistics


def statistics(cells):
    """Numbers for one group of cell records (lot, variant, bay...)"""
    judged = [c for c in cells if c["status"] in (ib.SEEDLING, ib.EMPTY)]
    seedlings = [c for c in judged if c["status"] == ib.SEEDLING]
    areas = np.array([c["area"] for c in seedlings], dtype=float)
    stats = {
        "cells": len(judged),
        "seedlings": len(seedlings),
        "empty": len(judged) - len(seedlings),
        "covered": sum(1 for c in cells if c["status"] == ib.COVERED),
        "presence": 100.0 * len(seedlings) / len(judged) if judged else None,
        "mean": None, "sd": None, "median": None, "q1": None, "q3": None, "iqr": None,
        "min": None, "max": None, "color": _mean_color(seedlings),
    }
    if len(areas):
        q1, median, q3 = np.percentile(areas, [25, 50, 75])
        stats.update(
            mean=float(areas.mean()), median=float(median), q1=float(q1), q3=float(q3),
            iqr=float(q3 - q1), min=float(areas.min()), max=float(areas.max()),
            sd=float(areas.std(ddof=1)) if len(areas) > 1 else None,
        )
    return stats


def _mean_color(seedlings):
    """Leaf-area-weighted mean color as RRGGBB, or None"""
    total = sum(c["area"] for c in seedlings if c["color"])
    if not total:
        return None
    b, g, r = (sum(c["area"] * c["color"][k] for c in seedlings if c["color"]) / total
               for k in range(3))
    return "%02X%02X%02X" % tuple(max(0, min(255, int(round(v)))) for v in (r, g, b))


def _stat_values(stats):
    def rounded(value, digits=2):
        return None if value is None else round(value, digits)

    return [
        stats["cells"], stats["seedlings"], stats["empty"], stats["covered"],
        rounded(stats["presence"], 1), rounded(stats["mean"]), rounded(stats["sd"]),
        rounded(stats["median"]), rounded(stats["q1"]), rounded(stats["q3"]),
        rounded(stats["iqr"]), rounded(stats["min"]), rounded(stats["max"]),
        "#" + stats["color"] if stats["color"] else None,
    ]


# Which data goes in


def collect(results):
    """(photos, lots, problems): the photos used, every lot (tray half) that goes into
    the report, and the photos that could not be used. Retaken lots are left out"""
    retaken = ib.find_retakes(results)
    photos, lots, problems = [], [], []
    for index, result in enumerate(results):
        data = result.get("data")
        if not result.get("ok") or not isinstance(data, dict) or "sections" not in data:
            if not result.get("skipped"):
                problems.append((os.path.basename(result["image_path"]),
                                 result.get("error") or "not processed"))
            continue
        gone = retaken.get(index, {})
        if ib.whole_photo_retaken(data, gone):
            continue
        photo = {"data": data, "retaken": gone, "lots": []}
        photos.append(photo)
        for s_index, section in enumerate(data["sections"]):
            if s_index in gone:
                continue
            cells = [c for c in data["cells"] if c["section"] == s_index]
            lot = {"photo": data, "section": section, "cells": cells,
                   "stats": statistics(cells)}
            lots.append(lot)
            photo["lots"].append(lot)
    return photos, lots, problems


def _lot_sort_key(lot):
    s = lot["section"]
    return (s["bay"] is None, s["bay"] or 0, s["variant"] or "", s["lot"] or 0,
            s["label"] or "", lot["photo"]["file"])


# The workbook


def export(results, output_path):
    photos, lots, problems = collect(results)
    if not lots:
        raise ValueError("None of the photos could be used, so there is nothing to save.")
    lots.sort(key=_lot_sort_key)
    workbook = Workbook()
    _lots_sheet(workbook.active, lots)
    _group_sheet(workbook.create_sheet("By Variant"), lots, "variant", "Variant")
    _group_sheet(workbook.create_sheet("By Bay"), lots, "bay", "Bay")
    _distribution_sheet(workbook.create_sheet("Distribution"), lots)
    _cells_sheet(workbook.create_sheet("Cells"), lots)
    used_names = set(workbook.sheetnames)
    for photo in photos:
        _tray_map(workbook, photo, used_names)
    _settings_sheet(workbook.create_sheet("Settings"), photos, problems)
    workbook.save(output_path)
    return output_path


def _header(sheet, headers, widths=None):
    sheet.append(headers)
    for cell in sheet[sheet.max_row]:
        cell.font = BOLD
        cell.fill = HEADER_FILL
        cell.alignment = CENTER
    sheet.row_dimensions[sheet.max_row].height = 32
    for index, header in enumerate(headers, start=1):
        width = (widths or {}).get(header, max(10, min(24, len(header) + 2)))
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A%d" % (sheet.max_row + 1)   # a string: sheet.cell() would add a row


def _paint_color(sheet, column):
    """Fill the 'Mean leaf color' cells with the color itself"""
    for row in sheet.iter_rows(min_row=2, min_col=column, max_col=column):
        cell = row[0]
        if isinstance(cell.value, str) and cell.value.startswith("#"):
            cell.fill = PatternFill("solid", fgColor=cell.value[1:])
            cell.font = Font(color="FFFFFF")


def _lots_sheet(sheet, lots):
    sheet.title = "Lots"
    headers = (["Label", "Bay", "Variant", "Lot", "Photo", "Tray half", "Photo taken"]
               + STAT_HEADERS + ["Cell spacing from QR (in)", "Warnings"])
    _header(sheet, headers, {"Label": 18, "Photo": 26, "Photo taken": 19, "Warnings": 40,
                             "Tray half": 11})
    for lot in lots:
        s, data = lot["section"], lot["photo"]
        warnings = s["warnings"] + [w for w in data["warnings"] if w.startswith("only")]
        sheet.append([s["label"] or "(no label)", s["bay"], s["variant"], s["lot"],
                      data["file"], s["name"], (data["taken"] or "")[:19] or None]
                     + _stat_values(lot["stats"])
                     + [round(data["pitch_in_from_qr"], 3) if data["pitch_in_from_qr"] else None,
                        "; ".join(warnings) or None])
        if warnings:
            sheet.cell(row=sheet.max_row, column=len(headers)).font = WARNING_FONT
    _paint_color(sheet, headers.index("Mean leaf color") + 1)
    sheet.auto_filter.ref = sheet.dimensions


def _group_sheet(sheet, lots, key, title):
    headers = [title, "Lots"] + STAT_HEADERS
    _header(sheet, headers)
    groups = {}
    for lot in lots:
        groups.setdefault(lot["section"][key], []).append(lot)
    for value in sorted(groups, key=lambda v: (v is None, v if v is not None else 0)
                        if key == "bay" else (v is None, str(v or ""))):
        members = groups[value]
        cells = [c for lot in members for c in lot["cells"]]
        name = value if value is not None else "(no label)"
        sheet.append([name, len(members)] + _stat_values(statistics(cells)))
    _paint_color(sheet, headers.index("Mean leaf color") + 1)
    sheet.auto_filter.ref = sheet.dimensions


def _bin_width(largest):
    """A round bin width giving about 12 bins up to `largest`"""
    raw = max(largest, 1e-6) / 12
    power = 10 ** math.floor(math.log10(raw))
    for step in (1, 2, 2.5, 5, 10):
        if step * power >= raw:
            return step * power
    return 10 * power


def _distribution_sheet(sheet, lots):
    variants = sorted({lot["section"]["variant"] or "(no label)" for lot in lots})
    areas = {v: [] for v in variants}
    for lot in lots:
        variant = lot["section"]["variant"] or "(no label)"
        areas[variant] += [c["area"] for c in lot["cells"] if c["status"] == ib.SEEDLING]
    everything = [a for values in areas.values() for a in values]
    if not everything:
        sheet.append(["No seedlings were found."])
        return
    width = _bin_width(float(np.percentile(everything, 99)))
    bins = int(math.ceil(max(everything) / width))
    _header(sheet, ["Seedling size (mm²)"] + variants + ["All"],
            {"Seedling size (mm²)": 20})
    for b in range(bins):
        low, high = b * width, (b + 1) * width
        counts = [sum(1 for a in areas[v] if low <= a < high or (b == bins - 1 and a == high))
                  for v in variants]
        sheet.append(["%g - %g" % (low, high)] + counts + [sum(counts)])
    chart = BarChart()
    chart.type = "col"
    chart.grouping = "clustered" if len(variants) > 1 else "standard"
    chart.title = "Seedling sizes"
    chart.x_axis.title = "Seedling size (mm²)"
    chart.y_axis.title = "Seedlings"
    last_series = len(variants) + (1 if len(variants) == 1 else 0)
    data = Reference(sheet, min_col=2, max_col=1 + last_series, min_row=1, max_row=1 + bins)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(Reference(sheet, min_col=1, min_row=2, max_row=1 + bins))
    chart.x_axis.delete = False   # openpyxl hides the axes unless told otherwise
    chart.y_axis.delete = False
    chart.legend.position = "r"
    chart.width, chart.height = 24, 12
    sheet.add_chart(chart, "%s2" % get_column_letter(len(variants) + 4))


def _cells_sheet(sheet, lots):
    headers = ["Label", "Bay", "Variant", "Lot", "Photo", "Tray half", "Cell", "Row",
               "Column", "Status", "Size (mm²)", "Leaf regions", "Leaf color", "Quality"]
    _header(sheet, headers, {"Label": 18, "Photo": 26, "Status": 13})
    for lot in lots:
        s, data = lot["section"], lot["photo"]
        for c in lot["cells"]:
            color = None
            if c["color"]:
                b, g, r = (max(0, min(255, int(round(v)))) for v in c["color"])
                color = "#%02X%02X%02X" % (r, g, b)
            sheet.append([s["label"], s["bay"], s["variant"], s["lot"], data["file"], s["name"],
                          c["name"], c["row"], c["column"], _status_text(c["status"]),
                          round(c["area"], 2) if c["status"] == ib.SEEDLING else None,
                          c["leaves"] or None, color, c["quality"]])
    sheet.auto_filter.ref = sheet.dimensions


def _status_text(status):
    return {ib.SEEDLING: "Seedling", ib.EMPTY: "Empty", ib.COVERED: "Under label",
            ib.INVALID: "Not judged"}.get(status, status)


def _size_fill(area, low, high):
    """Light green for small seedlings to dark green for big ones"""
    t = 0.0 if high <= low else max(0.0, min(1.0, (area - low) / (high - low)))
    start, end = (226, 239, 218), (55, 120, 40)
    r, g, b = (int(round(s + (e - s) * t)) for s, e in zip(start, end))
    return PatternFill("solid", fgColor="%02X%02X%02X" % (r, g, b)), t > 0.55


def _tray_map(workbook, photo, used_names):
    data = photo["data"]
    stem = os.path.splitext(data["file"])[0][:28]
    name, n = stem, 2
    while name in used_names:
        name = "%s (%d)" % (stem[:24], n)
        n += 1
    used_names.add(name)
    sheet = workbook.create_sheet(name)
    rows, columns = data["rows"], data["columns"]
    areas = [c["area"] for c in data["cells"] if c["status"] == ib.SEEDLING]
    low, high = (np.percentile(areas, [5, 95]) if areas else (0, 1))
    top = 4  # the grid starts at this sheet row, column B

    sheet["A1"] = data["file"]
    sheet["A1"].font = Font(bold=True, size=13)
    labels = []
    for index, section in enumerate(data["sections"]):
        text = "%s: %s" % (section["name"], section["label"] or "no label")
        if index in photo["retaken"]:
            text += " (retaken in %s, not used)" % photo["retaken"][index]
        labels.append(text)
    sheet["A2"] = "   |   ".join(labels)
    if data["warnings"]:
        sheet["A3"] = "Check: " + "; ".join(data["warnings"])
        sheet["A3"].font = WARNING_FONT

    for c in range(columns):   # column letters and row numbers, like the cell names
        cell = sheet.cell(row=top, column=c + 2, value=get_column_letter(c + 1))
        cell.font, cell.alignment = BOLD, CENTER
        sheet.column_dimensions[get_column_letter(c + 2)].width = 7.5
    for r in range(rows):
        cell = sheet.cell(row=top + 1 + r, column=1, value=r + 1)
        cell.font, cell.alignment = BOLD, CENTER
        sheet.row_dimensions[top + 1 + r].height = 30
    sheet.column_dimensions["A"].width = 5

    split = data["sections"][1] if len(data["sections"]) > 1 else None
    for record in data["cells"]:
        r, c = record["row"] - 1, record["column"] - 1
        cell = sheet.cell(row=top + 1 + r, column=c + 2)
        cell.alignment = CENTER
        cell.font = Font(size=9)
        if record["section"] in photo["retaken"]:
            cell.fill = RETAKEN_FILL
        elif record["status"] == ib.SEEDLING:
            cell.value = round(record["area"], 1)
            cell.fill, dark = _size_fill(record["area"], low, high)
            if dark:
                cell.font = Font(size=9, color="FFFFFF")
        elif record["status"] == ib.EMPTY:
            cell.value = "-"
            cell.fill = EMPTY_FILL
        elif record["status"] == ib.COVERED:
            cell.value = "label"
            cell.fill = COVERED_FILL
        else:
            cell.value = "?"
        left = THICK if split and split["columns"][0] and c == split["columns"][0] else THIN
        top_side = THICK if split and split["rows"][0] and r == split["rows"][0] else THIN
        cell.border = Border(left=left, right=THIN, top=top_side, bottom=THIN)

    key_row = top + rows + 2
    sheet.cell(row=key_row, column=2, value="Numbers are seedling sizes in mm². "
               "Darker green = bigger.  - = empty cell,  label = under the QR label "
               "(not counted),  grey = retaken in a later photo.")
    sheet.freeze_panes = sheet.cell(row=top + 1, column=2)


def _settings_sheet(sheet, photos, problems):
    pitches = [p["data"]["pitch_in_from_qr"] for p in photos if p["data"]["pitch_in_from_qr"]]
    rows = [
        ("Made", datetime.datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Photos used", len(photos)),
        ("Cell spacing used for sizes (in)", ib.CELL_PITCH_IN),
        ("", "ASSUMED, not measured. Sizes scale with its square: 5% wider cells "
             "would make every size about 10% bigger."),
        ("Cell spacing estimated from the QR codes (in)",
         round(float(np.mean(pitches)), 3) if pitches else "no labels read"),
        ("", "From the QR codes' printed size (%d dpi printer), averaged over %d label(s). "
             "Use it to replace the assumed spacing once it looks steady."
         % (ib.LABEL_DPI, len(pitches))),
        ("Tray layout", "%d x %d cells, two lots of %d x %d side by side"
         % (12, 24, 12, 12)),
        ("Seedling size", "Leaf area seen from above (green pixels in the cell)"),
        ("Seedling presence", "Seedlings / cells that could be judged (cells under a "
                              "label are not counted)"),
        ("Q1, Q3, IQR", "The middle half of the sizes lies between Q1 and Q3; IQR = Q3 - Q1"),
        ("Retakes", "When a lot's label is in more than one photo, only the newest photo "
                    "is used (camera clock, else list order)"),
        ("Analysis", "Prototype-Bounding-Boxes Version3 leaf detection on the tray "
                     "straightened to 128 pixels per cell"),
    ]
    sheet.column_dimensions["A"].width = 42
    sheet.column_dimensions["B"].width = 100
    for key, value in rows:
        sheet.append([key, value])
        sheet.cell(row=sheet.max_row, column=1).font = BOLD
        sheet.cell(row=sheet.max_row, column=2).alignment = Alignment(wrap_text=True)
    if problems:
        sheet.append([])
        sheet.append(["Photos that could not be used", ""])
        sheet.cell(row=sheet.max_row, column=1).font = BOLD
        for name, error in problems:
            sheet.append([name, error])
