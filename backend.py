#Backend for Tab 2's barcode generator.

#Public interface expected by Tab 2:
#plan_pages(request) -> {"page_count": int}
#render_preview(request, page_index) -> PNG bytes
#export_barcodes(request, path) -> None

#Request format:
#{"barcodes": [{"text": "LOT-2026-10-0001"}, ...]}

#Install dependencies:
#pip install python-barcode pillow reportlab

from io import BytesIO
import math
import re

import barcode
from barcode.writer import ImageWriter
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


# Tab 2 reads these constants to choose the save-file extension and description.
BARCODE_FILE_EXTENSION = ".pdf"
BARCODE_FILE_DESCRIPTION = "Printable barcode PDF"

# Printable page layout: 3 columns x 7 rows = 21 labels per US Letter page.
PAGE_SIZE = letter
COLUMNS = 4
ROWS = 8
LABELS_PER_PAGE = COLUMNS * ROWS
MARGIN_PT = 18
LABEL_GAP_PT = 0
LABEL_WIDTH_PT = (PAGE_SIZE[0] - 2 * MARGIN_PT - (COLUMNS - 1) * LABEL_GAP_PT) / COLUMNS
LABEL_HEIGHT_PT = (PAGE_SIZE[1] - 2 * MARGIN_PT - (ROWS - 1) * LABEL_GAP_PT) / ROWS

# Preview resolution. The preview is only for on-screen viewing; PDF export uses
# the original generated barcode image and vector text/borders.
PREVIEW_DPI = 110
PT_TO_PX = PREVIEW_DPI / 72.0
PREVIEW_WIDTH = round(PAGE_SIZE[0] * PT_TO_PX)
PREVIEW_HEIGHT = round(PAGE_SIZE[1] * PT_TO_PX)

_TEXT_PATTERN = re.compile(r"^[\x20-\x7E]+$")


def _get_texts(request):
    """Validate and return the ordered barcode strings from a Tab 2 request."""
    if not isinstance(request, dict):
        raise ValueError("Barcode request must be a dictionary.")

    barcodes = request.get("barcodes")
    if not isinstance(barcodes, list) or not barcodes:
        raise ValueError("The request must contain at least one barcode.")

    texts = []
    seen = set()
    for index, item in enumerate(barcodes, start=1):
        if not isinstance(item, dict):
            raise ValueError("Barcode %d must be an object." % index)
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Barcode %d has no text." % index)
        text = text.strip()
        if not _TEXT_PATTERN.fullmatch(text):
            raise ValueError(
                "Barcode %d contains unsupported characters. "
                "Use printable ASCII characters." % index
            )
        if text in seen:
            raise ValueError("Duplicate barcode text in request: %s" % text)
        seen.add(text)
        texts.append(text)

    return texts


def _barcode_image(text):
    """Create one Code 128 barcode image in memory, without writing a file."""
    code = barcode.get("code128", text, writer=ImageWriter())
    buffer = BytesIO()
    code.write(
        buffer,
        options={
            "module_width": 0.25,
            "module_height": 15.0,
            "quiet_zone": 3.0,
            "font_size": 10,
            "text_distance": 3.0,
            "write_text": True,
            "dpi": 300,
        },
    )
    buffer.seek(0)
    with Image.open(buffer) as image:
        return image.convert("RGB").copy()


def plan_pages(request):
    """
    Return the number of PDF pages required for the request.

    Tab 2 calls this while inputs are being edited, so keep this function quick:
    page planning does not generate barcode images.
    """
    texts = _get_texts(request)
    return {"page_count": max(1, math.ceil(len(texts) / LABELS_PER_PAGE))}


def _load_font(size, bold=False):
    """Use a common font when available; fall back to Pillow's default."""
    candidates = (
        ["DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf"]
        if bold
        else ["DejaVuSans.ttf", "Arial.ttf", "arial.ttf"]
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_preview_page(texts, page_index):
    """Render one page as a PNG image for the Tab 2 preview canvas."""
    page_count = max(1, math.ceil(len(texts) / LABELS_PER_PAGE))
    if not isinstance(page_index, int) or not 0 <= page_index < page_count:
        raise ValueError("Preview page index is out of range.")

    start = page_index * LABELS_PER_PAGE
    page_texts = texts[start:start + LABELS_PER_PAGE]

    page = Image.new("RGB", (PREVIEW_WIDTH, PREVIEW_HEIGHT), "white")
    draw = ImageDraw.Draw(page)

    margin = round(MARGIN_PT * PT_TO_PX)
    label_width = (PREVIEW_WIDTH - 2 * margin) / COLUMNS
    label_height = (PREVIEW_HEIGHT - 2 * margin) / ROWS
    border_width = max(1, round(0.5 * PT_TO_PX))
    id_font = _load_font(max(10, round(9 * PT_TO_PX)))

    for local_index, text in enumerate(page_texts):
        column = local_index % COLUMNS
        row = local_index // COLUMNS

        x0 = round(margin + column * label_width)
        y0 = round(margin + row * label_height)
        x1 = round(margin + (column + 1) * label_width)
        y1 = round(margin + (row + 1) * label_height)

        draw.rectangle(
            (x0, y0, x1, y1),
            outline=(150, 150, 150),
            width=border_width,
        )

        image = _barcode_image(text)
        max_width = max(1, x1 - x0 - round(16 * PT_TO_PX))
        max_height = max(1, round((label_height - 34) * PT_TO_PX))
        image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

        barcode_x = x0 + (x1 - x0 - image.width) // 2
        barcode_y = y0 + round(8 * PT_TO_PX)
        page.paste(image, (barcode_x, barcode_y))

        # Draw the ID as preview text as well. The barcode image also has its
        # own human-readable text, but this separate label makes the layout clear.
        bbox = draw.textbbox((0, 0), text, font=id_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        text_x = x0 + (x1 - x0 - text_width) // 2
        text_y = y1 - round(10 * PT_TO_PX) - text_height
        draw.text((text_x, text_y), text, fill="black", font=id_font)

    output = BytesIO()
    page.save(output, format="PNG")
    return output.getvalue()


def render_preview(request, page_index):
    """
    Render a requested page and return PNG bytes.

    Tab 2 opens these bytes with PIL.Image.open(io.BytesIO(png)).
    """
    texts = _get_texts(request)
    return _draw_preview_page(texts, page_index)


def export_barcodes(request, path):
    """
    Export every barcode in the request to a printable US letter.

    The layout is 3 columns x 7 rows (21 labels/page). Each label includes a
    Code 128 barcode and its ID. No temporary image files are written.
    """
    texts = _get_texts(request)
    if not path:
        raise ValueError("A destination PDF path is required.")

    pdf = canvas.Canvas(path, pagesize=PAGE_SIZE)
    page_width, page_height = PAGE_SIZE

    for index, text in enumerate(texts):
        if index > 0 and index % LABELS_PER_PAGE == 0:
            pdf.showPage()

        position = index % LABELS_PER_PAGE
        column = position % COLUMNS
        row = position // COLUMNS

        x = MARGIN_PT + column * (LABEL_WIDTH_PT + LABEL_GAP_PT)
        y = page_height - MARGIN_PT - (row + 1) * (LABEL_HEIGHT_PT + LABEL_GAP_PT)

        # Border around each label.
        pdf.setLineWidth(0.4)
        pdf.setStrokeGray(0.65)
        pdf.rect(x, y, LABEL_WIDTH_PT, LABEL_HEIGHT_PT)
        pdf.setStrokeGray(0)

        image = _barcode_image(text)
        max_image_width = LABEL_WIDTH_PT - 16
        max_image_height = LABEL_HEIGHT_PT - 38
        image_width, image_height = image.size
        scale = min(max_image_width / image_width, max_image_height / image_height)

        draw_width = image_width * scale
        draw_height = image_height * scale
        draw_x = x + (LABEL_WIDTH_PT - draw_width) / 2
        draw_y = y + 27 + (max_image_height - draw_height) / 2

        pdf.drawImage(
            ImageReader(image),
            draw_x,
            draw_y,
            width=draw_width,
            height=draw_height,
            preserveAspectRatio=True,
            mask="auto",
        )

        # The barcode's writer already embeds human-readable text; this separate
        # line provides a consistent, readable ID near the bottom of the label.
        pdf.setFont("Helvetica", 8)
        pdf.drawCentredString(x + LABEL_WIDTH_PT / 2, y + 10, text)

    pdf.save()


# path = Path("/mnt/data/backend.py")
# path.write_text(code, encoding="utf-8")
# print(f"Created {path}")






# """Backend placeholders

# Currently this is the ONLY file the GUI calls into

#     start_batch()                             -> Tab 1, once before a run
#     process_image(image_path)                 -> Tab 1, once per photo
#     export_results_to_excel(results, path)    -> Tab 1, "Save Excel file"
#     plan_pages(request)                       -> Tab 2, page count for the summary
#     render_preview(request, page_index)       -> Tab 2, PNG of one page for the preview
#     export_barcodes(request, path)            -> Tab 2, "Save barcodes"

# If a function fails, raise an exception with a short, plain message.
# """

# import io
# import math
# import os
# import random
# import time

# # Tab 2: barcodes
# #
# # The frontend decides WHICH barcodes to print, this file decides HOW they look and where they go
# # Every Tab 2 function gets the same request, plain dicts and lists to stay JSON-friendly:
# #     {"barcodes": [{"text": "L1042-2026-10-0001"}, ...]}
# #
# # TODO(backend): replace the 3 placeholders below with the real barcodes and layout
# #   - plan_pages: count pages only, keep it instant for typing (called on every keystroke)
# #   - render_preview: draw ONE page and return PNG bytes, around 100 dpi is plenty
# #   - export_barcodes: write every page to output_path as a PDF
# #   - preview and export run in a background thread, keep tkinter out of them
# #   - treat the request as read-only, copy it first if you need to change it
# #   I came up with from our talk: reportlab draws the PDF, pypdfium2 renders one page of it as the preview PNG
# #   One drawing path keeps the preview identical to the print

# # File type offered by the "Save barcodes" dialog
# BARCODE_FILE_EXTENSION = ".pdf"
# BARCODE_FILE_DESCRIPTION = "PDF document"

# # Placeholder layout, US Letter upright with barcodes in pairs (two side by side, cut out as one strip)
# PAGE_WIDTH_IN = 8.5
# PAGE_HEIGHT_IN = 11.0
# PAGE_MARGIN_IN = 0.5
# PAIRS_PER_ROW = 1
# ROWS_PER_PAGE = 15
# PLACEHOLDER_DPI = 100


# def plan_pages(request):
#     """How many pages the barcodes fill. Returns {"page_count": int}"""
#     # TODO(backend): real page count from the real layout
#     pairs = math.ceil(len(request["barcodes"]) / 2)
#     return {"page_count": math.ceil(pairs / (PAIRS_PER_ROW * ROWS_PER_PAGE))}


# def render_preview(request, page_index):
#     """PNG bytes of one page, page_index starts at 0"""
#     # TODO(backend): draw the real page, ideally by rendering that page of the real PDF
#     page = _placeholder_page(_split_into_pages(_texts(request))[page_index])
#     out = io.BytesIO()
#     page.save(out, "PNG")
#     return out.getvalue()


# def export_barcodes(request, output_path):
#     """Write every page to output_path as a PDF"""
#     # TODO(backend): write the real PDF with vector barcodes
#     pages = [_placeholder_page(pairs) for pairs in _split_into_pages(_texts(request))]
#     pages[0].save(
#         output_path, "PDF", resolution=PLACEHOLDER_DPI, save_all=True, append_images=pages[1:]
#     )


# def _texts(request):
#     return [barcode["text"] for barcode in request["barcodes"]]


# def _split_into_pages(barcode_texts):
#     """List of pages, each a list of (left, right) pairs in printing order. right is None for an odd one out"""
#     padded = list(barcode_texts) + [None]
#     pairs = [(padded[i], padded[i + 1]) for i in range(0, len(barcode_texts), 2)]
#     per_page = PAIRS_PER_ROW * ROWS_PER_PAGE
#     return [pairs[i : i + per_page] for i in range(0, len(pairs), per_page)]


# def _pair_slots():
#     """(x, y, width, height) in inches from the top-left paper corner, one per pair position"""
#     width = (PAGE_WIDTH_IN - 2 * PAGE_MARGIN_IN) / PAIRS_PER_ROW
#     height = (PAGE_HEIGHT_IN - 2 * PAGE_MARGIN_IN) / ROWS_PER_PAGE
#     return [
#         (PAGE_MARGIN_IN + column * width, PAGE_MARGIN_IN + row * height, width, height)
#         for row in range(ROWS_PER_PAGE)
#         for column in range(PAIRS_PER_ROW)
#     ]


# def _placeholder_page(pairs):
#     """One page with fake bars and the real text of each barcode"""
#     from PIL import Image, ImageDraw  # pip install pillow

#     dpi = PLACEHOLDER_DPI
#     page = Image.new("L", (round(PAGE_WIDTH_IN * dpi), round(PAGE_HEIGHT_IN * dpi)), 255)
#     draw = ImageDraw.Draw(page)
#     draw.text((page.width / 2, 25), "PLACEHOLDER - no real barcodes yet", fill=0, anchor="mm")
#     for (x, y, width, height), pair in zip(_pair_slots(), pairs):
#         left, top = x * dpi, y * dpi
#         right, bottom = (x + width) * dpi, (y + height) * dpi
#         draw.rectangle([left, top, right, bottom], outline=160)  # cut line
#         half = (right - left) / 2
#         for index, text in enumerate(pair):
#             if text is None:
#                 continue
#             cell_left = left + index * half
#             # Random bars seeded by the text to keep each barcode looking the same between renders
#             rng = random.Random(text)
#             bar_x, bar_right = cell_left + 30, cell_left + half - 30
#             while bar_x < bar_right:
#                 bar = rng.choice((1, 1, 2, 3))
#                 draw.rectangle([bar_x, top + 8, bar_x + bar - 1, bottom - 22], fill=0)
#                 bar_x += bar + rng.choice((1, 2, 3))
#             draw.text((cell_left + half / 2, bottom - 12), text, fill=0, anchor="mm")
#     return page


# # Tab 1: tray photos

# class SkipPhoto(Exception):
#     """Raise from process_image to skip a photo without calling it a failure"""


# def start_batch():
#     """forget anything remembered from the previous run"""


# def process_image(image_path):
#     """Analyse ONE tray photo and return its result

#     Currently it waits half a second and returns a dummy result
#     """
#     if not os.path.isfile(image_path):
#         raise FileNotFoundError("The photo could not be found.")
#     time.sleep(0.5)
#     return {"note": "placeholder result"}


# def export_results_to_excel(results, output_path):
#     """Write the results of a finished batch to an Excel file

#     Currently it writes one row per photo with the file name and status
#     """
#     from openpyxl import Workbook  # pip install openpyxl

#     workbook = Workbook()
#     sheet = workbook.active
#     sheet.title = "Results"
#     sheet.append(["Filename", "Status", "Result (placeholder)"])
#     for result in results:
#         if result["ok"]:
#             status, detail = "OK", str(result["data"])
#         elif result["skipped"]:
#             status, detail = "Skipped", result["error"]
#         else:
#             status, detail = "Failed", result["error"]
#         sheet.append([os.path.basename(result["image_path"]), status, detail])
#     workbook.save(output_path)
