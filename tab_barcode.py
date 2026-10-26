"""Tab 2. type lot number, choose year / month / barcode numbers and save barcodes

This tab decides WHICH barcodes to make. backend.py decides how they look and where they go
"""

import datetime
import io
import queue
import re
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, ttk

import backend
from ui_helpers import SaveBar, WrappingLabel, show_save_error

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

BARCODE_NUMBER_DIGITS = 4   # numbers are zero-padded
MAX_BARCODE_NUMBER = 10 ** BARCODE_NUMBER_DIGITS - 1  # 9999

WARNING_TEXT = (
    "This program does NOT keep track of the barcodes you have already made."
)
HOW_TO_STEPS = [
    "Type the lot number, then choose the year and the month.",
    "Type the barcode number, or a range such as 1-30 to make many at once.",
    'Click "Save barcodes...", then open the saved file and print it.',
    "Write down the numbers you printed, so you know where to continue next time.",
]


NOTES_WRAP = 660    # The notes span the whole tab
LEFT_WRAP = 370     # Texts under the form

ERROR_NO_NUMBERS = "Missing barcode number."
ERROR_FORMAT = "Barcode number: please type a number like 7, or a range like 1-20."
ERROR_RANGE = "Barcode numbers must be between 1 and %d." % MAX_BARCODE_NUMBER
ERROR_NO_LOT = "Missing lot number."
ERROR_LOT = "The lot number can only use letters, digits, '-', '_' and '.'."
ERROR_COLOR = "#b00020"
HINT_COLOR = "#606060"

PREVIEW_EMPTY = "The barcode pages will show up here."
PREVIEW_NONE = "No preview available."
PREVIEW_MIN_LINES = 12      # Smallest height of the page preview
PREVIEW_START_ASPECT = 8.5 / 11  # starting shape only, the real shape comes from the PNG
PREVIEW_DELAY_MS = 150      # wait until typing pauses
POLL_MS = 30

_SINGLE = re.compile(r"^\d+$")
_RANGE = re.compile(r"^(\d+)\s*(?:-|–|—|to)\s*(\d+)$", re.IGNORECASE)
_LOT = re.compile(r"^[A-Za-z0-9._-]+$")  # also ends up in the file name


def make_barcode_text(lot_number, year, month, number):
    """Return the text encoded in one barcode"""
    return "%s-%04d-%02d-%0*d" % (lot_number, year, month, BARCODE_NUMBER_DIGITS, number)


def build_request(barcode_texts):
    """The request handed to every Tab 2 backend function"""
    # One dict per barcode to leave room for more fields later
    return {"barcodes": [{"text": text} for text in barcode_texts]}


def check_lot_number(text):
    """Raise ValueError if `text` can't be used as a lot number"""

    if not text:
        raise ValueError(ERROR_NO_LOT)
    if not _LOT.match(text):
        raise ValueError(ERROR_LOT)


def parse_barcode_numbers(text):
    """Turn '7', '1-20' or '1-20, 25' into a sorted list of unique ints"""

    parts = [part.strip() for part in re.split(r"[,;]", text)]
    parts = [part for part in parts if part]
    if not parts:
        raise ValueError(ERROR_NO_NUMBERS)

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


def _error_text(error):
    return str(error) or error.__class__.__name__


class BarcodeTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.barcode_texts = []  # what "Save barcodes..." will write
        self.request = None      # build_request(barcode_texts), None while the form has errors
        self.page_count = 0
        self.page_index = 0      # page shown in the preview
        self.preview_fn = None   # None uses backend.render_preview, the debug panel swaps in fakes

        self._preview_image = None
        self._preview_message = ""
        self._preview_message_color = HINT_COLOR
        self._preview_photo = None  # keep a reference or Tk drops the image
        self._preview_gen = 0       # bumped on every change to drop outdated renders
        self._preview_busy = False
        self._preview_job = None
        self._redraw_job = None
        self._saving_path = None
        self._results = queue.Queue()  # (kind, gen, result, error) from the worker threads
        self._poll_job = None

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
        self.lot_var = tk.StringVar()
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

        self.lot_entry = ttk.Entry(form, textvariable=self.lot_var, width=20)
        add_row(0, "Lot number:", self.lot_entry)
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
        self.preview_canvas = tk.Canvas(
            preview, width=round(min_height * PREVIEW_START_ASPECT), height=min_height,
            background="#dcdcdc", highlightthickness=0,
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda event: self._queue_redraw())

        nav = ttk.Frame(preview)
        nav.grid(row=1, column=0, pady=(4, 0))
        self.prev_button = ttk.Button(nav, text="◀", width=3, command=lambda: self.flip_page(-1))
        self.prev_button.pack(side="left")
        self.page_label = ttk.Label(nav, width=16, anchor="center")
        self.page_label.pack(side="left", padx=6)
        self.next_button = ttk.Button(nav, text="▶", width=3, command=lambda: self.flip_page(1))
        self.next_button.pack(side="left")

        for variable in (self.lot_var, self.year_var, self.month_var, self.numbers_var):
            variable.trace_add("write", self._on_input_changed)
        for entry in (self.lot_entry, self.numbers_entry):
            entry.bind("<Return>", lambda event: self.save_button.invoke())

    # Reacting to input

    def _on_input_changed(self, *_):
        """Re-check the form. update the summary, the button and the preview"""
        if self._saving_path is None:
            self.save_bar.clear()
        lot_number = self.lot_var.get().strip()
        errors = []  # one line per problem, in form order
        try:
            check_lot_number(lot_number)
        except ValueError as error:
            errors.append(str(error))
        try:
            numbers = parse_barcode_numbers(self.numbers_var.get())
        except ValueError as error:
            errors.append(str(error))

        self.barcode_texts, self.request, self.page_count = [], None, 0
        if not errors:
            year = int(self.year_var.get())
            month = self.month_box.current() + 1
            texts = [make_barcode_text(lot_number, year, month, n) for n in numbers]
            request = build_request(texts)
            try:
                self.page_count = backend.plan_pages(request)["page_count"]
            except Exception as error:
                errors.append("The pages could not be planned. %s" % _error_text(error))
            else:
                self.barcode_texts, self.request = texts, request

        if errors:
            self.summary_label.configure(text="\n".join(errors), foreground=ERROR_COLOR)
        else:
            summary = "%s on %s\n%s" % (
                _plural(len(self.barcode_texts), "barcode"),
                _plural(self.page_count, "page"),
                self.barcode_texts[0],
            )
            if len(self.barcode_texts) > 1:
                summary += "   to   " + self.barcode_texts[-1]
            self.summary_label.configure(text=summary, foreground=self._normal_color)

        self._update_save_button()

        # Stay on the same page when the range changes, clamped to the new page count
        self.page_index = max(0, min(self.page_index, self.page_count - 1))
        self._update_page_nav()
        self._preview_gen += 1
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
            self._preview_job = None
        if self.request is None:
            self._show_preview_message(PREVIEW_EMPTY)
        else:
            self._preview_job = self.after(PREVIEW_DELAY_MS, self._start_preview)

    def _update_save_button(self):
        ready = self.request is not None and self._saving_path is None
        self.save_button.state(["!disabled"] if ready else ["disabled"])

    # Preview, one page at a time from backend.render_preview

    def flip_page(self, step):
        page = self.page_index + step
        if self.request is None or not 0 <= page < self.page_count:
            return
        self.page_index = page
        self._update_page_nav()
        self.refresh_preview()

    def _update_page_nav(self):
        if self.page_count:
            self.page_label.configure(text="Page %d of %d" % (self.page_index + 1, self.page_count))
        else:
            self.page_label.configure(text="")
        has_prev = self.page_index > 0
        has_next = self.page_index < self.page_count - 1
        self.prev_button.state(["!disabled"] if has_prev else ["disabled"])
        self.next_button.state(["!disabled"] if has_next else ["disabled"])

    def refresh_preview(self):
        """Render the preview now, skipping the typing delay"""
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
            self._preview_job = None
        self._preview_gen += 1
        self._start_preview()

    def _start_preview(self):
        self._preview_job = None
        # One render at a time, a busy render restarts itself once it sees it is outdated
        if self.request is None or self._preview_busy:
            return
        self._preview_busy = True
        render = self.preview_fn or backend.render_preview
        self._start_worker("preview", self._preview_gen, render, self.request, self.page_index)

    def _preview_done(self, gen, png, error):
        self._preview_busy = False
        if gen != self._preview_gen:
            if self.request is not None and self._preview_job is None:
                self._start_preview()
            return
        if error is not None:
            self._show_preview_message(
                "The preview could not be made.\n\n%s" % _error_text(error), ERROR_COLOR
            )
        elif png is None:
            self._show_preview_message(PREVIEW_NONE)
        else:
            try:
                from PIL import Image  # pip install pillow

                # Full colour to keep the scaled-down page smooth
                image = Image.open(io.BytesIO(png)).convert("RGB")
            except Exception as error:
                self._show_preview_message(
                    "The preview could not be shown.\n\n%s" % _error_text(error), ERROR_COLOR
                )
                return
            self._preview_image = image
            self._preview_message = ""
            self._draw_preview()

    def _show_preview_message(self, text, color=HINT_COLOR):
        self._preview_image = None
        self._preview_message = text
        self._preview_message_color = color
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

        if self._preview_image is not None:
            from PIL import ImageTk  # pip install pillow

            # Scale here instead of asking the backend again on every resize
            fitted = self._preview_image.copy()
            fitted.thumbnail((width - 12, height - 12))
            self._preview_photo = ImageTk.PhotoImage(fitted, master=canvas)
            canvas.create_image(width / 2, height / 2, image=self._preview_photo)
        elif self._preview_message:
            canvas.create_text(
                width / 2, height / 2, text=self._preview_message,
                fill=self._preview_message_color, justify="center", width=width - 20,
            )

    # Background work

    def _start_worker(self, kind, gen, fn, *args):
        """Run fn(*args) in a thread, the result comes back through _poll"""
        def work():
            try:
                result = fn(*args)
            except Exception as error:
                self._results.put((kind, gen, None, error))
            else:
                self._results.put((kind, gen, result, None))

        threading.Thread(target=work, daemon=True).start()
        if self._poll_job is None:
            self._poll_job = self.after(POLL_MS, self._poll)

    def _poll(self):
        """Runs in the GUI thread, Tk is only touched from here"""
        self._poll_job = None
        try:
            while True:
                kind, gen, result, error = self._results.get_nowait()
                if kind == "preview":
                    self._preview_done(gen, result, error)
                else:
                    self._save_done(error)
        except queue.Empty:
            pass
        if self._preview_busy or self._saving_path is not None:
            self._poll_job = self.after(POLL_MS, self._poll)

    # Saving

    def _default_file_name(self):
        first, last = self.barcode_texts[0], self.barcode_texts[-1]
        name = "barcodes_" + first
        if last != first:
            name += "_to_" + last.rsplit("-", 1)[-1]
        return name + backend.BARCODE_FILE_EXTENSION

    def _on_save(self):
        if self.request is None or self._saving_path is not None:
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
        # Background thread to keep the window responsive during a big export
        self._saving_path = path
        self._update_save_button()
        self.save_bar.show_busy("Saving...")
        self.winfo_toplevel().configure(cursor="watch")
        self._start_worker("save", None, backend.export_barcodes, self.request, path)

    def _save_done(self, error):
        path, self._saving_path = self._saving_path, None
        self.winfo_toplevel().configure(cursor="")
        self._update_save_button()
        if error is not None:
            self.save_bar.clear()
            show_save_error(self, error, path, what="barcode file")
        else:
            self.mark_saved(path)

    def mark_saved(self, path):
        self.save_bar.show(path)

    def is_saving(self):
        return self._saving_path is not None

    def reset(self):
        today = datetime.date.today()
        self.page_index = 0
        self.lot_var.set("")
        self.year_var.set(str(today.year))
        self.month_box.current(today.month - 1)
        self.numbers_var.set("")
