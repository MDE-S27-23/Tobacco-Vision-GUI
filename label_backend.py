"""Backend for Tab 2's 3 x 1 inch QR-code stake labels, printed on a Zebra label printer.

Request format:
{"barcodes": [{"bay_number": "2", "type": "NC960", "lot_number": "29"}]}
("bay2" also works as a bay number, and the numbers can be ints.)

QR payload: Bay2-NC960-29
Printed next to the QR code, in the same order as the payload:

    +------------------------------------------+
    |  QR   Bay 2                      Lot 29  |
    |  QR               NC960                  |
    +------------------------------------------+

Public interface used by Tab 2:
plan_pages(request) -> {"page_count": int}
render_preview(request, page_index, dpi) -> PNG bytes
export_barcodes(request, path, dpi) -> None, a PDF with one 3 x 1 inch page per stake
make_zpl(request, dpi) -> bytes to send to the Zebra printer
stake_text(record) -> "Bay2-NC960-29"

Every stake is drawn once as a 1-bit picture at the printer's resolution (dpi). The
preview, the PDF and the print job all use that same picture, so what you see is what
prints. The print job sends the picture as a ZPL ^GF graphic, using only old ZPL
commands, since the customer's Zebra ZM400 has 2008 firmware.

Install: pip install "qrcode[pil]" pillow reportlab
"""
import functools
import re
from io import BytesIO

import qrcode
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

BARCODE_FILE_EXTENSION = ".pdf"
BARCODE_FILE_DESCRIPTION = "Printable 3 x 1 inch QR-code stakes"

LABEL_WIDTH_IN = 3.0
LABEL_HEIGHT_IN = 1.0
PAGE_SIZE = (LABEL_WIDTH_IN * inch, LABEL_HEIGHT_IN * inch)

# Zebra print heads come in these resolutions (dots per inch). The ZM400 came in all
# three. 203 dpi = 8 dots/mm (Zebra calls it "200 dpi"), 300 dpi = 12 dots/mm
DPI_CHOICES = (203, 300, 600)
DEFAULT_DPI = 203

# Layout, in inches
SAFE_MARGIN_IN = 0.08     # no ink this close to any edge, the printer may shift the label a little
QR_QUIET_MODULES = 4      # white border a QR code needs to scan, kept on the label itself
MIN_QR_MODULE_DOTS = 3    # below this a scanner may struggle
MIN_TEXT_GAP_IN = 0.12    # between the QR code's border and the text
ROW_GAP_IN = 0.05         # between the rows, below the "y" in "Bay"
MIN_COLUMN_GAP_IN = 0.2   # between "Bay ..." and "Lot ..." when they are long

MIN_NUMBER = 1
MAX_NUMBER = 999

# Windows ships Arial. The others are fallbacks for other systems
FONTS = ("arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf")

_NUMBER = re.compile(r"^(?:bay|lot)?\s*(\d+)$", re.IGNORECASE)
_TYPE = re.compile(r"^[A-Za-z0-9]+$")


def _number(value, what):
    """'2', 'bay2' or 2 -> 2"""
    if isinstance(value, int) and not isinstance(value, bool):
        number = value
    else:
        match = _NUMBER.match(value.strip()) if isinstance(value, str) else None
        if not match:
            raise ValueError("the %s number must be a number, like 2." % what)
        number = int(match.group(1))
    if not MIN_NUMBER <= number <= MAX_NUMBER:
        raise ValueError(
            "the %s number must be between %d and %d." % (what, MIN_NUMBER, MAX_NUMBER)
        )
    return number


def _read_stake(record):
    """One request record -> {"text": "Bay2-NC960-29", "bay": 2, "type": "NC960", "lot": 29}"""
    if not isinstance(record, dict):
        raise ValueError("it must be an object.")
    bay = _number(record.get("bay_number"), "bay")
    stake_type = record.get("type")
    stake_type = stake_type.strip() if isinstance(stake_type, str) else ""
    if not _TYPE.match(stake_type):
        raise ValueError("the type must be letters and digits only, like NC960.")
    lot = _number(record.get("lot_number"), "lot")
    # Keep the required order: Bay Number - type - lot number.
    text = "Bay%d-%s-%d" % (bay, stake_type, lot)
    return {"text": text, "bay": bay, "type": stake_type, "lot": lot}


def stake_text(record):
    """What the QR code of one request record holds, like 'Bay2-NC960-29'"""
    return _read_stake(record)["text"]


def _get_stakes(request):
    if not isinstance(request, dict):
        raise ValueError("QR-code request must be a dictionary.")
    records = request.get("barcodes")
    if not isinstance(records, list) or not records:
        raise ValueError("The request must contain at least one stake.")

    stakes = []
    seen = set()
    for index, record in enumerate(records, start=1):
        try:
            stake = _read_stake(record)
        except ValueError as error:
            raise ValueError("Stake %d: %s" % (index, error)) from None
        if stake["text"] in seen:
            raise ValueError("Duplicate stake information: %s" % stake["text"])
        seen.add(stake["text"])
        stakes.append(stake)
    return stakes


def plan_pages(request):
    """One stake per 3 x 1 inch PDF page."""
    return {"page_count": len(_get_stakes(request))}


# Drawing


def _label_size_dots(dpi):
    return round(LABEL_WIDTH_IN * dpi), round(LABEL_HEIGHT_IN * dpi)


def _safe_margin_dots(dpi):
    return round(SAFE_MARGIN_IN * dpi)


@functools.lru_cache(maxsize=256)
def _load_font(size):
    for name in FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def _make_qr_matrix(text):
    """The QR code's modules as rows of True (black) / False, without the white border"""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # survives scuffs and dirt
        border=0,
    )
    qr.add_data(text)
    qr.make(fit=True)
    return qr.get_matrix()


def _qr_layout(modules, label_height, safe):
    """Largest whole dots per module that keeps the QR border and the safe margin.
    Returns (dots per module, space from the label edge to the QR code)"""
    for module in range(label_height // modules, MIN_QR_MODULE_DOTS - 1, -1):
        edge = max(QR_QUIET_MODULES * module, safe)
        if modules * module + 2 * edge <= label_height:
            return module, edge
    return None, None


def _draw_qr(draw, text, label_height, safe):
    """Draw the QR code at the left, centred top to bottom. Returns (box, dots per module)"""
    matrix = _make_qr_matrix(text)
    modules = len(matrix)
    module, edge = _qr_layout(modules, label_height, safe)
    if module is None:
        raise ValueError("The stake text is too long to fit as a QR code: %s" % text)
    size = modules * module
    x0 = edge
    y0 = (label_height - size) // 2
    for row, cells in enumerate(matrix):
        for column, dark in enumerate(cells):
            if dark:
                x, y = x0 + column * module, y0 + row * module
                draw.rectangle((x, y, x + module - 1, y + module - 1), fill=0)
    return (x0, y0, x0 + size, y0 + size), module


def _metrics(size):
    """(font, capital letter height, descender depth) in dots"""
    font = _load_font(size)
    cap = -font.getbbox("H", anchor="ls")[1]
    descender = font.getbbox("y", anchor="ls")[3]
    return font, cap, descender


def _text_width(font, text):
    left, _, right, _ = font.getbbox(text, anchor="ls")
    return right - left


def _largest(low, high, fits):
    """Largest whole number in low..high where fits() is true (fits only gets harder upward)"""
    while low < high:
        middle = (low + high + 1) // 2
        if fits(middle):
            low = middle
        else:
            high = middle - 1
    return low


def _draw_rows(draw, stake, box, ink_bottom, dpi):
    """Bay / lot on the top row, the type on the bottom row, inside `box`.
    Nothing goes below `ink_bottom`"""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    bay, lot = "Bay %d" % stake["bay"], "Lot %d" % stake["lot"]
    stake_type = stake["type"]
    row_gap = round(ROW_GAP_IN * dpi)
    column_gap = round(MIN_COLUMN_GAP_IN * dpi)

    def type_size(size):
        """The top row's size, or smaller for a long type"""
        return _largest(6, size, lambda s: _text_width(_load_font(s), stake_type) <= width)

    def type_baseline(size):
        """On the box bottom, or raised if letters like g/p/q would hang past ink_bottom"""
        hang = max(0, _load_font(size).getbbox(stake_type, anchor="ls")[3])
        return min(bottom, ink_bottom - hang)

    def fits(size):
        font, cap, _ = _metrics(size)
        bay_hang = font.getbbox(bay, anchor="ls")[3]  # the "y" in "Bay"
        small = type_size(size)
        return (
            _text_width(font, bay) + column_gap + _text_width(font, lot) <= width
            and top + cap + bay_hang + row_gap + _metrics(small)[1] <= type_baseline(small)
        )

    # The largest size where the top row's capitals start at the box top
    # and the bottom row ends at the box bottom
    size = _largest(6, height * 2, fits)
    top_font, cap, _ = _metrics(size)
    small = type_size(size)

    draw.text((left, top + cap), bay, font=top_font, fill=0, anchor="ls")
    draw.text((right, top + cap), lot, font=top_font, fill=0, anchor="rs")
    draw.text(((left + right) // 2, type_baseline(small)), stake_type,
              font=_load_font(small), fill=0, anchor="ms")


def _render_stake(stake, dpi):
    """The whole label as a 1-bit image, one pixel per printer dot (0 = black)"""
    if dpi not in DPI_CHOICES:
        raise ValueError("The printer resolution must be one of %s dpi." % (DPI_CHOICES,))
    width, height = _label_size_dots(dpi)
    page = Image.new("1", (width, height), 1)
    draw = ImageDraw.Draw(page)  # mode "1" draws without anti-aliasing, like the printer
    safe = _safe_margin_dots(dpi)
    (qr_left, qr_top, qr_right, qr_bottom), module = _draw_qr(draw, stake["text"], height, safe)
    text_left = qr_right + max(QR_QUIET_MODULES * module, round(MIN_TEXT_GAP_IN * dpi))
    box = (text_left, qr_top, width - safe, qr_bottom)
    _draw_rows(draw, stake, box, height - safe, dpi)
    return page


def render_preview(request, page_index, dpi=DEFAULT_DPI):
    """PNG bytes of one stake, at the printer's resolution"""
    stakes = _get_stakes(request)
    if not isinstance(page_index, int) or not 0 <= page_index < len(stakes):
        raise ValueError("Preview page index is out of range.")
    output = BytesIO()
    _render_stake(stakes[page_index], dpi).save(output, format="PNG")
    return output.getvalue()


def export_barcodes(request, path, dpi=DEFAULT_DPI):
    """Export one 3 x 1 inch PDF page per stake."""
    stakes = _get_stakes(request)
    if not path:
        raise ValueError("A destination PDF path is required.")

    pdf = canvas.Canvas(path, pagesize=PAGE_SIZE)
    for stake in stakes:
        # The printer's exact dots, stretched over the whole page
        page = _render_stake(stake, dpi).convert("L")
        pdf.drawImage(ImageReader(page), 0, 0, width=PAGE_SIZE[0], height=PAGE_SIZE[1])
        pdf.showPage()
    pdf.save()


# Zebra ZPL


def make_zpl(request, dpi=DEFAULT_DPI):
    """Bytes for a whole print job, one ^XA...^XZ label format per stake"""
    stakes = _get_stakes(request)
    return "".join(_stake_to_zpl(stake, dpi) for stake in stakes).encode("ascii")


def _stake_to_zpl(stake, dpi):
    """ZPL for one stake: the picture as one ^GF graphic field"""
    page = _render_stake(stake, dpi)
    width, height = page.size
    row_bytes = (width + 7) // 8
    total = row_bytes * height
    graphic = _compress_rows(_zpl_bits(page), row_bytes)
    return (
        "^XA"
        "^PW%d^LL%d^LH0,0"        # print width and label length, in dots
        "^FO0,0^GFA,%d,%d,%d,%s^FS"
        "^PQ1"
        "^XZ\n" % (width, height, total, total, row_bytes, graphic)
    )


def _zpl_bits(page):
    """Packed rows with 1 = black, as ZPL wants. Pillow packs 1 = white"""
    width, height = page.size
    row_bytes = (width + 7) // 8
    flipped = bytearray(byte ^ 0xFF for byte in page.tobytes())
    # Rows are padded to whole bytes, keep the padding bits white
    spare_bits = row_bytes * 8 - width
    if spare_bits:
        keep = (0xFF << spare_bits) & 0xFF
        for end in range(row_bytes - 1, len(flipped), row_bytes):
            flipped[end] &= keep
    return bytes(flipped)


def _compress_rows(data, row_bytes):
    """Hex for ^GFA using ZPL's ASCII compression

    ':' repeats the row above, ',' fills the rest of a row with white,
    and runs of one hex digit get a count letter (G..Y = 1..19, g..z = 20..400)
    """
    out = []
    previous = None
    for start in range(0, len(data), row_bytes):
        row = data[start:start + row_bytes].hex().upper()
        if row == previous:
            out.append(":")
            continue
        previous = row
        ink = row.rstrip("0")
        if not ink:
            out.append(",")
            continue
        out.append(_run_length(ink))
        if len(ink) < len(row):
            out.append(",")
    return "".join(out)


def _run_length(hex_digits):
    out = []
    index = 0
    while index < len(hex_digits):
        digit = hex_digits[index]
        end = index
        while end < len(hex_digits) and hex_digits[end] == digit:
            end += 1
        count = end - index
        if count > 1:
            out.append(_count_letters(count))
        out.append(digit)
        index = end
    return "".join(out)


def _count_letters(count):
    letters = []
    while count >= 20:
        twenties = min(count // 20, 20)
        letters.append(chr(ord("g") + twenties - 1))  # g = 20 ... z = 400
        count -= twenties * 20
    if count:
        letters.append(chr(ord("G") + count - 1))  # G = 1 ... Y = 19
    return "".join(letters)


# Self-test, run by the GUI exe's --self-test


def _decompress_rows(graphic, row_bytes):
    """Reverse of _compress_rows"""
    digits_per_row = row_bytes * 2
    rows = []
    current = []
    count = 0
    for char in graphic:
        if "G" <= char <= "Y":
            count += ord(char) - ord("G") + 1
        elif "g" <= char <= "z":
            count += (ord(char) - ord("g") + 1) * 20
        elif char == ":":
            rows.append(rows[-1])
        elif char == ",":
            current.extend("0" * (digits_per_row - len(current)))
        else:
            current.extend(char * (count or 1))
            count = 0
        if len(current) >= digits_per_row:
            rows.append("".join(current[:digits_per_row]))
            current = []
    return bytes.fromhex("".join(rows))


def _check_safe_margin(page, dpi):
    """Raise if any ink is closer to an edge than SAFE_MARGIN_IN"""
    safe = _safe_margin_dots(dpi)
    width, height = page.size
    for band in ((0, 0, width, safe), (0, height - safe, width, height),
                 (0, 0, safe, height), (width - safe, 0, width, height)):
        if page.crop(band).getextrema()[0] == 0:
            raise AssertionError("Ink inside the safe margin at %d dpi" % dpi)


TEST_REQUEST = {"barcodes": [
    {"bay_number": "999", "type": "ABCDEFGH12345678", "lot_number": "999"},  # longest
    {"bay_number": "1", "type": "A", "lot_number": "1"},                     # shortest
    {"bay_number": "bay12", "type": "gypqj", "lot_number": 5},               # letters below the line
]}


def self_test():
    """Draw the test stakes at every resolution and check that the ZPL decodes back to
    exactly the same dots and that nothing is inside the safe margin. Raises on failure"""
    stakes = _get_stakes(TEST_REQUEST)
    for dpi in DPI_CHOICES:
        for stake in stakes:
            page = _render_stake(stake, dpi)
            _check_safe_margin(page, dpi)
            zpl = _stake_to_zpl(stake, dpi)
            row_bytes = (page.width + 7) // 8
            graphic = zpl.split("^GFA,", 1)[1].split(",", 3)[3].split("^FS", 1)[0]
            decoded = _decompress_rows(graphic, row_bytes)
            if not any(decoded):
                raise AssertionError("%s came out blank at %d dpi" % (stake["text"], dpi))
            pixels = page.load()
            for y in range(page.height):
                for x in range(page.width):
                    black = decoded[y * row_bytes + x // 8] >> (7 - x % 8) & 1
                    if black != (pixels[x, y] == 0):
                        raise AssertionError(
                            "ZPL dot (%d, %d) of %s is wrong at %d dpi"
                            % (x, y, stake["text"], dpi)
                        )
    render_preview(TEST_REQUEST, 0)
    return True


if __name__ == "__main__":
    self_test()
    print("Self-test passed.")
