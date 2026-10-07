"""Backend placeholders

Currently this is the ONLY file the GUI calls into. 

    start_batch()                             -> Tab 1, once before a run
    process_image(image_path)                 -> Tab 1, once per photo
    export_results_to_excel(results, path)    -> Tab 1, "Save Excel file"
    make_barcode_text(plant, year, month, n)  -> Tab 2, text inside a barcode
    render_page_preview(barcode_texts)        -> Tab 2, optional preview picture
    export_barcodes(barcode_texts, path)      -> Tab 2, "Save barcodes"

If a function fails, raise an exception with a short, plain message.
"""

import os
import time

# Tab 2

# Name shown in the dropdown
PLANT_CODES = {
    "Tobacco": "TOB",
    "Basil": "BAS",
    "Dill": "DIL",
}

BARCODE_NUMBER_DIGITS = 4   # numbers are zero-padded

# File type offered by the "Save barcodes" dialog.
BARCODE_FILE_EXTENSION = ".pdf"
BARCODE_FILE_DESCRIPTION = "PDF document"

def make_barcode_text(plant, year, month, number):
    """Return the text encoded in one barcode"""
    return "%s-%04d-%02d-%0*d" % (
        PLANT_CODES[plant],
        year,
        month,
        BARCODE_NUMBER_DIGITS,
        number,
    )

# Barcodes are printed in pairs. Two barcodes side by side with no # gap, cut out as one strip
PAGE_WIDTH_IN = 8.5  # US Letter, upright
PAGE_HEIGHT_IN = 11.0
PAGE_MARGIN_IN = 0.5

PAIRS_PER_ROW = 1
ROWS_PER_PAGE = 15


def split_into_pages(barcode_texts):
    """Arrange barcodes the way they are printed. Returns a list of pages. Each page is a list of pairs in printing order"""
    padded = list(barcode_texts) + [None]
    pairs = [(padded[i], padded[i + 1]) for i in range(0, len(barcode_texts), 2)]
    per_page = PAIRS_PER_ROW * ROWS_PER_PAGE
    return [pairs[i : i + per_page] for i in range(0, len(pairs), per_page)]


def pair_slots():
    """Where each pair sits on a page. Returns (x, y, width, height) in inches from the top-left paper corner, one entry per pair position, in printing order.
    """
    width = (PAGE_WIDTH_IN - 2 * PAGE_MARGIN_IN) / PAIRS_PER_ROW
    height = (PAGE_HEIGHT_IN - 2 * PAGE_MARGIN_IN) / ROWS_PER_PAGE
    return [
        (PAGE_MARGIN_IN + column * width, PAGE_MARGIN_IN + row * height, width, height)
        for row in range(ROWS_PER_PAGE)
        for column in range(PAIRS_PER_ROW)
    ]


def render_page_preview(barcode_texts):

    return None


def export_barcodes(barcode_texts, output_path):
    """writes US Letter pages with the right layout the text of each barcode, but an empty box where the bars will go"""
    from PIL import Image, ImageDraw  # pip install pillow

    dpi = 100
    page_size = (round(PAGE_WIDTH_IN * dpi), round(PAGE_HEIGHT_IN * dpi))
    slots = pair_slots()
    pages = []
    for pairs in split_into_pages(barcode_texts):
        page = Image.new("1", page_size, 1)  # black and white keeps it small
        draw = ImageDraw.Draw(page)
        draw.text(
            (page_size[0] / 2 - 100, 20), "PLACEHOLDER - no real barcodes yet", fill=0
        )
        for (x, y, width, height), pair in zip(slots, pairs):
            left, top = x * dpi, y * dpi
            right, bottom = (x + width) * dpi, (y + height) * dpi
            draw.rectangle([left, top, right, bottom], outline=0)  # cut line
            half = (right - left) / 2
            for index, text in enumerate(pair):
                if text is None:
                    continue
                cell_left = left + index * half
                draw.rectangle(
                    [cell_left + 20, top + 8, cell_left + half - 20, bottom - 22],
                    outline=0,
                )
                draw.text(
                    (cell_left + half / 2 - 3 * len(text), bottom - 18), text, fill=0
                )
        pages.append(page)
    pages[0].save(
        output_path, "PDF", resolution=dpi, save_all=True, append_images=pages[1:]
    )


# Tab 1: tray photos

class SkipPhoto(Exception):
    """Raise from process_image to skip a photo without calling it a failure"""


def start_batch():
    """forget anything remembered from the previous run"""


def process_image(image_path):
    """Analyse ONE tray photo and return its result

    Currently it waits half a second and returns a dummy result
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError("The photo could not be found.")
    time.sleep(0.5)
    return {"note": "placeholder result"}


def export_results_to_excel(results, output_path):
    """Write the results of a finished batch to an Excel file

    Currently it writes one row per photo with the file name and status
    """
    from openpyxl import Workbook  # pip install openpyxl

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Results"
    sheet.append(["Filename", "Status", "Result (placeholder)"])
    for result in results:
        if result["ok"]:
            status, detail = "OK", str(result["data"])
        elif result["skipped"]:
            status, detail = "Skipped", result["error"]
        else:
            status, detail = "Failed", result["error"]
        sheet.append([os.path.basename(result["image_path"]), status, detail])
    workbook.save(output_path)
