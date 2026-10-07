"""Tab 2. choose plant / year / month / barcode numbers and save barcodes"""

import datetime
import random
import re
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, ttk

import backend
from ui_helpers import SaveBar, WrappingLabel, busy_cursor, show_save_error

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

MAX_BARCODE_NUMBER = 10 ** backend.BARCODE_NUMBER_DIGITS - 1  # 9999

WARNING_TEXT = (
    "This program does NOT keep track of the barcodes you have already made."
)
HOW_TO_STEPS = [
    "Choose the plant, the year and the month.",
    "Type the barcode number, or a range such as 1-30 to make many at once.",
    'Click "Save barcodes...", then open the saved file and print it.',
    "Write down the numbers you printed, so you know where to continue next time.",
]


NOTES_WRAP = 660    # The notes span the whole tab
LEFT_WRAP = 370     # Texts under the form

HINT_EMPTY = "Type the barcode number(s) above to continue."
ERROR_FORMAT = "Please type a number like 7, or a range like 1-20."
ERROR_RANGE = "Barcode numbers must be between 1 and %d." % MAX_BARCODE_NUMBER
ERROR_COLOR = "#b00020"

PREVIEW_MIN_LINES = 12  # Smallest height of the page preview

_SINGLE = re.compile(r"^\d+$")
_RANGE = re.compile(r"^(\d+)\s*(?:-|–|—|to)\s*(\d+)$", re.IGNORECASE)


def parse_barcode_numbers(text):
    """Turn '7', '1-20' or '1-20, 25' into a sorted list of unique ints"""

    parts = [part.strip() for part in re.split(r"[,;]", text)]
    parts = [part for part in parts if part]
    if not parts:
        raise ValueError(HINT_EMPTY)

    numbers = set()
    for part in parts:
        match = _RANGE.match(part)
        if _SINGLE.match(part):
            first = last = int(part)
        elif match:
            first, last = sorted((int(match.group(1)), int(match.group(2))))
        else:
            raise ValueError(ERROR_FORMAT)
        if first < 1 or last > MAX_BARCODE_NUMBER:
            raise ValueError(ERROR_RANGE)
        numbers.update(range(first, last + 1))
    return sorted(numbers)


def _plural(count, word):
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


class BarcodeTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.barcode_texts = []  # what "Save barcodes..." will write

        self._preview_pairs = []
        self._preview_image = None
        self._preview_error = ""
        self._preview_photo = None  # keep a reference or Tk drops the image
        self._preview_job = None
        self._redraw_job = None
        self._fonts = {}

        self._build()
        self._on_input_changed()

    # Layout

    def _build(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        default_font = tkfont.nametofont("TkDefaultFont")
        bold = default_font.copy()
        bold.configure(weight="bold")
        self._bold_font = bold
        line_height = default_font.metrics("linespace")

        # Warning and short tutorial
        notes = ttk.LabelFrame(self, text="Important Notes", padding=8)
        notes.grid(row=0, column=0, columnspan=2, sticky="ew")
        notes.columnconfigure(1, weight=1)
        ttk.Label(notes, image="::tk::icons::warning").grid(
            row=0, column=0, padx=(0, 10)
        )
        WrappingLabel(notes, text=WARNING_TEXT, font=bold, wraplength=NOTES_WRAP).grid(
            row=0, column=1, sticky="ew"
        )
        steps = ttk.Frame(notes)
        steps.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        steps.columnconfigure(1, weight=1)
        for row, step in enumerate(HOW_TO_STEPS):
            ttk.Label(steps, text="%d." % (row + 1)).grid(
                row=row, column=0, sticky="nw", padx=(0, 6)
            )
            WrappingLabel(steps, text=step, wraplength=NOTES_WRAP).grid(
                row=row, column=1, sticky="ew"
            )

        # Left column, form, summary, save
        left = ttk.Frame(self)
        left.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        left.columnconfigure(0, weight=1)

        form = ttk.LabelFrame(left, text="Barcode Parameters", padding=8)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)

        today = datetime.date.today()
        self.plant_var = tk.StringVar(value=list(backend.PLANT_CODES)[0])
        self.year_var = tk.StringVar(value=str(today.year))
        self.month_var = tk.StringVar()
        self.numbers_var = tk.StringVar()

        month_values = ["%02d - %s" % (i + 1, name) for i, name in enumerate(MONTHS)]
        self.month_var.set(month_values[today.month - 1])
        year_values = [str(year) for year in range(today.year - 1, today.year + 4)]

        def add_row(row, label, widget):
            ttk.Label(form, text=label).grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=3
            )
            widget.grid(row=row, column=1, sticky="ew", pady=3)

        self.plant_box = ttk.Combobox(
            form, textvariable=self.plant_var, state="readonly", width=18,
            values=list(backend.PLANT_CODES),
        )
        add_row(0, "Plant:", self.plant_box)
        self.year_box = ttk.Combobox(
            form, textvariable=self.year_var, state="readonly", width=18,
            values=year_values,
        )
        add_row(1, "Year:", self.year_box)
        self.month_box = ttk.Combobox(
            form, textvariable=self.month_var, state="readonly", width=18,
            values=month_values,
        )
        add_row(2, "Month:", self.month_box)
        self.numbers_entry = ttk.Entry(form, textvariable=self.numbers_var, width=20)
        add_row(3, "Barcode number(s):", self.numbers_entry)
        ttk.Label(form, text="Examples:   7      1-30      1-30, 35").grid(
            row=4, column=1, sticky="w"
        )

        # Room for two lines
        left.rowconfigure(1, minsize=2 * line_height + 10)
        self.summary_label = WrappingLabel(left, text="", width=1, wraplength=LEFT_WRAP)
        self.summary_label.grid(row=1, column=0, sticky="new", pady=(10, 0))
        self._normal_color = str(self.summary_label.cget("foreground"))

        self.save_bar = SaveBar(left, message_lines=2, wraplength=LEFT_WRAP)
        self.save_bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.save_button = ttk.Button(
            self.save_bar.buttons, text="Save barcodes...", command=self._on_save
        )
        self.save_button.pack(side="left")
        left.columnconfigure(0, minsize=self.save_bar.full_width())

        # Right column, the printed page
        preview = ttk.LabelFrame(self, text="Preview", padding=8)
        preview.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(8, 0))
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        min_height = PREVIEW_MIN_LINES * line_height
        min_width = round(min_height * backend.PAGE_WIDTH_IN / backend.PAGE_HEIGHT_IN)
        self.preview_canvas = tk.Canvas(
            preview, width=min_width, height=min_height,
            background="#dcdcdc", highlightthickness=0,
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda event: self._queue_redraw())
        self.preview_caption_var = tk.StringVar()
        ttk.Label(preview, textvariable=self.preview_caption_var).grid(
            row=1, column=0, pady=(4, 0)
        )

        for variable in (self.plant_var, self.year_var, self.month_var, self.numbers_var):
            variable.trace_add("write", self._on_input_changed)
        self.numbers_entry.bind("<Return>", lambda event: self.save_button.invoke())

    # Reacting to input

    def _on_input_changed(self, *_):
        """Re-check the form. update the summary, the button and the preview"""
        self.save_bar.clear()
        typed = self.numbers_var.get()
        try:
            numbers = parse_barcode_numbers(typed)
        except ValueError as error:
            self.barcode_texts = []
            is_hint = not typed.strip()
            self.summary_label.configure(
                text=str(error),
                foreground=self._normal_color if is_hint else ERROR_COLOR,
            )
        else:
            plant = self.plant_var.get()
            year = int(self.year_var.get())
            month = self.month_box.current() + 1
            self.barcode_texts = [
                backend.make_barcode_text(plant, year, month, number)
                for number in numbers
            ]
            pages = backend.split_into_pages(self.barcode_texts)
            pairs = [pair for page in pages for pair in page]
            singles = sum(1 for left, right in pairs if right is None)
            groups = []
            if len(pairs) > singles:
                groups.append(_plural(len(pairs) - singles, "pair"))
            if singles:  # an odd barcode left over at the end
                groups.append("1 single")
            summary = "%s, printed as %s on %s\n" % (
                _plural(len(numbers), "barcode"),
                " + ".join(groups),
                _plural(len(pages), "page"),
            )
            summary += self.barcode_texts[0]
            if len(numbers) > 1:
                summary += "   to   " + self.barcode_texts[-1]
            self.summary_label.configure(text=summary, foreground=self._normal_color)

        self.save_button.state(["!disabled"] if self.barcode_texts else ["disabled"])

        # Wait until typing pauses
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
        self._preview_job = self.after(150, self._refresh_preview)

    # Preview of the first printed page

    def _refresh_preview(self):
        """find out what page 1 holds, then draw it"""
        self._preview_job = None
        self._preview_image = None
        self._preview_error = ""
        pages = backend.split_into_pages(self.barcode_texts)
        self._preview_pairs = pages[0] if pages else []

        if pages:
            self.preview_caption_var.set("Page 1 of %d" % len(pages))
            try:
                self._preview_image = backend.render_page_preview(self.barcode_texts)
            except Exception as error:
                self._preview_error = "The preview could not be made.\n\n%s" % error
        else:
            per_page = backend.PAIRS_PER_ROW * backend.ROWS_PER_PAGE
            self.preview_caption_var.set("US Letter, %d pairs per page" % per_page)
        self._draw_preview()

    def show_preview_image(self, image):
        """Show a PIL image of the page instead of the drawn one"""
        self._preview_image = image
        self._preview_error = ""
        self._draw_preview()

    def _queue_redraw(self):
        """The preview box changed size, redraw once things settle"""
        if self._redraw_job is not None:
            self.after_cancel(self._redraw_job)
        self._redraw_job = self.after(40, self._draw_preview)

    def _draw_preview(self):
        if self._redraw_job is not None:
            self.after_cancel(self._redraw_job)
            self._redraw_job = None
        canvas = self.preview_canvas
        canvas.delete("all")
        self._preview_photo = None
        width = max(canvas.winfo_width(), int(canvas.cget("width")))
        height = max(canvas.winfo_height(), int(canvas.cget("height")))

        if self._preview_error:
            canvas.create_text(
                width / 2, height / 2, text=self._preview_error, fill=ERROR_COLOR,
                justify="center", width=width - 20,
            )
        elif self._preview_image is not None:
            from PIL import ImageTk  # pip install pillow

            fitted = self._preview_image.copy()
            fitted.thumbnail((width - 12, height - 12))
            self._preview_photo = ImageTk.PhotoImage(fitted, master=canvas)
            canvas.create_image(width / 2, height / 2, image=self._preview_photo)
        else:
            self._draw_page(canvas, width, height)

    def _draw_page(self, canvas, width, height):
        """Draw a simplified US Letter page from the layout in backend.py"""
        page_w, page_h = backend.PAGE_WIDTH_IN, backend.PAGE_HEIGHT_IN
        scale = min((width - 12) / page_w, (height - 12) / page_h)  # pixels per inch
        x0 = round((width - page_w * scale) / 2)
        y0 = round((height - page_h * scale) / 2)

        def px(x_in, y_in):
            return x0 + round(x_in * scale), y0 + round(y_in * scale)

        canvas.create_rectangle(*px(0, 0), *px(page_w, page_h), fill="white", outline="#808080")

        pairs = self._preview_pairs
        for index, (x, y, w, h) in enumerate(backend.pair_slots()):
            left, top = px(x, y)
            right, bottom = px(x + w, y + h)
            used = index < len(pairs)
            canvas.create_rectangle(
                left, top, right, bottom, outline="#b4b4b4" if used else "#e4e4e4"
            )
            if not used:
                continue
            middle = (left + right) // 2
            for text, (cell_left, cell_right) in zip(
                pairs[index], ((left, middle), (middle, right))
            ):
                if text is not None:
                    self._draw_barcode(canvas, text, cell_left, top, cell_right, bottom)

        # Printer safe margin
        margin = backend.PAGE_MARGIN_IN
        canvas.create_rectangle(
            *px(margin, margin), *px(page_w - margin, page_h - margin),
            outline="#5b8fd1", dash=(3, 3),
        )

    def _draw_barcode(self, canvas, text, left, top, right, bottom):
        """A stand-in barcode"""
        cell_w, cell_h = right - left, bottom - top
        bars_left = left + max(3, round(cell_w * 0.08))  # quiet zone
        bars_right = right - max(3, round(cell_w * 0.08))
        bars_top = top + max(2, round(cell_h * 0.14))
        bars_bottom = top + round(cell_h * 0.66)

        unit = max(1, (bars_right - bars_left) // 110)
        rng = random.Random(text)
        x = bars_left
        while x < bars_right:
            bar = min(unit * rng.choice((1, 1, 2, 3)), bars_right - x)
            canvas.create_rectangle(x, bars_top, x + bar, bars_bottom, fill="black", outline="")
            x += bar + unit * rng.choice((1, 1, 2))

        # The text under the bars, or a grey line when it would be too small
        label_y = (bars_bottom + bottom) / 2
        font = self._font_that_fits(text, cell_w * 0.9, (bottom - bars_bottom) * 0.8)
        if font is not None:
            canvas.create_text((left + right) / 2, label_y, text=text, font=font)
        else:
            canvas.create_line(
                left + cell_w * 0.3, label_y, right - cell_w * 0.3, label_y, fill="#909090"
            )

    def _font_that_fits(self, text, max_width, max_height):
        """Largest readable font for `text` in that space, or None"""
        for pixels in range(min(int(max_height), 14), 6, -1):
            font = self._fonts.get(pixels)
            if font is None:
                family = tkfont.nametofont("TkDefaultFont").actual("family")
                font = self._fonts[pixels] = tkfont.Font(family=family, size=-pixels)
            if font.measure(text) <= max_width:
                return font
        return None

    # Saving

    def _default_file_name(self):
        first, last = self.barcode_texts[0], self.barcode_texts[-1]
        name = "barcodes_" + first
        if last != first:
            name += "_to_" + last.rsplit("-", 1)[-1]
        return name + backend.BARCODE_FILE_EXTENSION

    def _on_save(self):
        if not self.barcode_texts:
            return
        extension = backend.BARCODE_FILE_EXTENSION
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save the barcodes",
            initialfile=self._default_file_name(),
            defaultextension=extension,
            filetypes=[(backend.BARCODE_FILE_DESCRIPTION, "*" + extension)],
        )
        if not path:
            return
        try:
            with busy_cursor(self):
                backend.export_barcodes(list(self.barcode_texts), path)
        except Exception as error:
            show_save_error(self, error, path, what="barcode file")
            return
        self.mark_saved(path)

    def mark_saved(self, path):
        self.save_bar.show(path)

    def reset(self):
        today = datetime.date.today()
        self.plant_box.current(0)
        self.year_var.set(str(today.year))
        self.month_box.current(today.month - 1)
        self.numbers_var.set("")
