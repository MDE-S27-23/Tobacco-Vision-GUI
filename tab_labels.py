"""Tab 2 (Label Printing). Type the bays, the variant and the lots, then print QR labels

This tab decides WHICH labels to make. label_backend.py (a copy of backend.py in the
Barcode-Generation repo) decides how they look and makes the print job, and
zebra_printer.py gets it to the printer.

Lots are inside bays: bays 1-2 with lots 1-5 make Bay1 lots 1-5, then Bay2 lots 1-5.
"""

import io
import queue
import re
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import app_settings
import label_backend
import zebra_printer
from ui_helpers import SaveBar, WrappingLabel, show_save_error

MIN_NUMBER = 1
MAX_NUMBER = 999
MAX_DESIGNATOR_LENGTH = 16
MAX_LABELS = 5000   # per print or PDF, keeps a typo like 1-999 x 1-999 from running away

NETWORK_CHOICE = "Network printer (by IP address)"

WARNING_TEXT = (
    "This program does NOT keep track of the labels you have already printed."
)
HOW_TO_STEPS = [
    "Type the bay number, the variant and the lot number. "
    "Use a range such as 1-5 to make many labels at once.",
    "Check the labels in the preview.",
    'Click "Print labels" to print on the Zebra printer, or "Save PDF..." to keep a copy.',
    "Write down what you printed, so you know where to continue next time.",
]

NOTES_WRAP = 660    # The notes span the whole tab
LEFT_WRAP = 370     # Texts under the form

ERROR_NO_DESIGNATOR = "Missing variant."
ERROR_DESIGNATOR = "The variant can only use letters and digits (no spaces or '-')."
ERROR_DESIGNATOR_LONG = "The variant can be at most %d characters long." % MAX_DESIGNATOR_LENGTH
ERROR_TOO_MANY = "That is %d labels. Please make at most " + "%d at a time." % MAX_LABELS
ERROR_COLOR = "#b00020"
HINT_COLOR = "#606060"

PREVIEW_EMPTY = "The labels will show up here."
PREVIEW_NONE = "No preview available."
PREVIEW_HEIGHT_LINES = 7    # Smallest height of the label preview
LABELS_PER_PAGE = 5         # labels shown at once in the preview, one under another
LABEL_GAP = 8               # pixels between them
PREVIEW_DELAY_MS = 150      # wait until typing pauses
POLL_MS = 30

_SINGLE = re.compile(r"^\d+$")
_RANGE = re.compile(r"^(\d+)\s*(?:-|–|—|to)\s*(\d+)$", re.IGNORECASE)
_DESIGNATOR = re.compile(r"^[A-Za-z0-9]+$")


def make_label(bay, designator, lot):
    """One stake record, in label_backend.py's request format"""
    return {"bay_number": str(bay), "type": designator, "lot_number": str(lot)}


def label_text(label):
    """What the label's QR code holds, like Bay1-NC960-29"""
    return label_backend.stake_text(label)


def make_request(labels):
    """label_backend.py takes the labels wrapped in a request"""
    return {"barcodes": labels}


def build_labels(bays, designator, lots):
    """Every lot of the first bay, then every lot of the next bay, and so on"""
    return [make_label(bay, designator, lot) for bay in bays for lot in lots]


def parse_numbers(text, what):
    """Turn '7', '1-20' or '1-20, 25' into a sorted list of unique ints. `what` is 'Bay' or 'Lot'"""
    parts = [part.strip() for part in re.split(r"[,;]", text)]
    parts = [part for part in parts if part]
    if not parts:
        raise ValueError("Missing %s number." % what.lower())

    numbers = set()
    for part in parts:
        match = _RANGE.match(part)
        if _SINGLE.match(part):
            first = last = int(part)
        elif match:
            first, last = sorted((int(match.group(1)), int(match.group(2))))
        else:
            raise ValueError(
                "%s number: please type a number like 3, or a range like 1-5." % what
            )
        if first < MIN_NUMBER or last > MAX_NUMBER:
            raise ValueError(
                "%s numbers must be between %d and %d." % (what, MIN_NUMBER, MAX_NUMBER)
            )
        numbers.update(range(first, last + 1))
    return sorted(numbers)


def check_designator(text):
    """Raise ValueError if `text` can't be used as the variant"""
    if not text:
        raise ValueError(ERROR_NO_DESIGNATOR)
    if not _DESIGNATOR.match(text):
        raise ValueError(ERROR_DESIGNATOR)
    if len(text) > MAX_DESIGNATOR_LENGTH:
        raise ValueError(ERROR_DESIGNATOR_LONG)


def _plural(count, word):
    return "%d %s%s" % (count, word, "" if count == 1 else "s")


def _error_text(error):
    return str(error) or error.__class__.__name__


def _dpi_text(dpi):
    return "%d dpi" % dpi


class LabelTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.labels = []         # what Print / Save PDF will use, empty while the form has errors
        self.page_index = 0      # preview page shown, LABELS_PER_PAGE labels each
        self.preview_fn = None   # None uses label_backend.render_preview, the debug panel swaps in fakes
        self.send_fn = None      # None really prints, the debug panel swaps in fakes

        self._preview_images = []   # PIL images of the labels on the shown page
        self._preview_message = ""
        self._preview_message_color = HINT_COLOR
        self._preview_photos = []   # keep references or Tk drops the images
        self._preview_gen = 0       # bumped on every change to drop outdated renders
        self._preview_busy = False
        self._preview_job = None
        self._redraw_job = None
        self._busy = None           # None, "pdf" or "print"
        self._busy_path = None
        self._busy_where = None
        self._busy_count = 0
        self._results = queue.Queue()  # (kind, gen, result, error) from the worker threads
        self._poll_job = None

        self._settings = app_settings.load()
        self._build()
        self.refresh_printers()
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

        # Left column: form, printer, summary, buttons
        left = ttk.Frame(self)
        left.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        left.columnconfigure(0, weight=1)

        form = ttk.LabelFrame(left, text="Label Parameters", padding=8)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)

        self.bay_var = tk.StringVar()
        self.designator_var = tk.StringVar()
        self.lot_var = tk.StringVar()

        def add_row(row, label, variable, hint):
            ttk.Label(form, text=label).grid(
                row=row, column=0, sticky="w", padx=(0, 10), pady=(3, 0)
            )
            entry = ttk.Entry(form, textvariable=variable, width=20)
            entry.grid(row=row, column=1, sticky="ew", pady=(3, 0))
            ttk.Label(form, text=hint, foreground=HINT_COLOR).grid(
                row=row + 1, column=1, sticky="w", pady=(0, 3)
            )
            return entry

        self.bay_entry = add_row(0, "Bay number(s):", self.bay_var,
                                 "Examples:   3      1-5      1-5, 8")
        self.designator_entry = add_row(2, "Variant:", self.designator_var,
                                        "Letters and digits, like NC960")
        self.lot_entry = add_row(4, "Lot number(s):", self.lot_var,
                                 "Examples:   29      1-30      1-30, 35")

        # Room for two lines
        left.rowconfigure(1, minsize=2 * line_height + 10)
        self.summary_label = WrappingLabel(left, text="", width=1, wraplength=LEFT_WRAP)
        self.summary_label.grid(row=1, column=0, sticky="new", pady=(8, 0))
        self._normal_color = str(self.summary_label.cget("foreground"))

        printer = ttk.LabelFrame(left, text="Printer", padding=8)
        printer.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        printer.columnconfigure(1, weight=1)

        self.printer_var = tk.StringVar()
        self.address_var = tk.StringVar(value=self._settings.get("network_address", ""))
        saved_dpi = self._settings.get("dpi")
        if saved_dpi not in label_backend.DPI_CHOICES:
            saved_dpi = label_backend.DEFAULT_DPI
        self.dpi_var = tk.StringVar(value=_dpi_text(saved_dpi))

        ttk.Label(printer, text="Printer:").grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.printer_box = ttk.Combobox(
            printer, textvariable=self.printer_var, state="readonly", width=28
        )
        self.printer_box.grid(row=0, column=1, sticky="ew")
        ttk.Button(printer, text="Refresh", command=self.refresh_printers).grid(
            row=0, column=2, padx=(6, 0)
        )
        self.address_label = ttk.Label(printer, text="IP address:")
        self.address_label.grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(6, 0))
        self.address_entry = ttk.Entry(printer, textvariable=self.address_var, width=20)
        self.address_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(printer, text="Resolution:").grid(
            row=2, column=0, sticky="w", padx=(0, 10), pady=(6, 0)
        )
        self.dpi_box = ttk.Combobox(
            printer, textvariable=self.dpi_var, state="readonly", width=10,
            values=[_dpi_text(dpi) for dpi in label_backend.DPI_CHOICES],
        )
        self.dpi_box.grid(row=2, column=1, sticky="w", pady=(6, 0))
        WrappingLabel(
            printer,
            text="If unsure, check the sticker on the bottom of the printer.",
            foreground=HINT_COLOR, width=1, wraplength=LEFT_WRAP,
        ).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(2, 0))

        self.action_bar = SaveBar(left, message_lines=3, wraplength=LEFT_WRAP)
        self.action_bar.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.print_button = ttk.Button(
            self.action_bar.buttons, text="Print labels", command=self._on_print
        )
        self.print_button.pack(side="left")
        self.pdf_button = ttk.Button(
            self.action_bar.buttons, text="Save PDF...", command=self._on_save_pdf
        )
        self.pdf_button.pack(side="left", padx=(6, 0))
        left.columnconfigure(0, minsize=self.action_bar.full_width())

        # Right column, the label preview
        preview = ttk.LabelFrame(self, text="Preview", padding=8)
        preview.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(8, 0))
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        min_height = PREVIEW_HEIGHT_LINES * line_height
        aspect = label_backend.LABEL_WIDTH_IN / label_backend.LABEL_HEIGHT_IN
        self.preview_canvas = tk.Canvas(
            preview, width=round(min_height * aspect), height=min_height,
            background="#dcdcdc", highlightthickness=0,
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda event: self._queue_redraw())

        nav = ttk.Frame(preview)
        nav.grid(row=1, column=0, pady=(4, 0))
        self.prev_button = ttk.Button(nav, text="◀", width=3, command=lambda: self.flip_page(-1))
        self.prev_button.pack(side="left")
        self.position_label = ttk.Label(nav, width=18, anchor="center")
        self.position_label.pack(side="left", padx=6)
        self.next_button = ttk.Button(nav, text="▶", width=3, command=lambda: self.flip_page(1))
        self.next_button.pack(side="left")

        for variable in (self.bay_var, self.designator_var, self.lot_var, self.dpi_var):
            variable.trace_add("write", self._on_input_changed)
        self.printer_box.bind("<<ComboboxSelected>>", lambda event: self._on_printer_chosen())
        self.dpi_box.bind("<<ComboboxSelected>>", lambda event: self._remember_printer())
        self.address_entry.bind("<FocusOut>", lambda event: self._remember_printer())

    # Printer choice

    def refresh_printers(self):
        """Re-read the printers installed in Windows"""
        try:
            names = zebra_printer.list_printers()
        except Exception:
            names = []
        self.printer_box.configure(values=names + [NETWORK_CHOICE])
        current = self.printer_var.get() or self._settings.get("printer", "")
        if current not in names and current != NETWORK_CHOICE:
            # Never pick an office printer by itself, leave it to the user
            zebras = [name for name in names if zebra_printer.is_zebra(name)]
            current = zebras[0] if zebras else ""
        self.printer_var.set(current)
        self._on_printer_chosen(remember=False)

    def _on_printer_chosen(self, remember=True):
        if self.printer_var.get() == NETWORK_CHOICE:
            self.address_label.grid()
            self.address_entry.grid()
        else:
            self.address_label.grid_remove()
            self.address_entry.grid_remove()
            dpi = zebra_printer.dpi_from_name(self.printer_var.get())
            if dpi in label_backend.DPI_CHOICES:
                self.dpi_var.set(_dpi_text(dpi))
        if remember:
            self._remember_printer()

    def _remember_printer(self):
        app_settings.save(
            printer=self.printer_var.get(),
            network_address=self.address_var.get().strip(),
            dpi=self.dpi(),
        )

    def dpi(self):
        return int(self.dpi_var.get().split()[0])

    # Reacting to input

    def _on_input_changed(self, *_):
        """Re-check the form. update the summary, the buttons and the preview"""
        if self._busy is None:
            self.action_bar.clear()
        errors = []  # one line per problem, in form order
        bays = lots = None
        try:
            bays = parse_numbers(self.bay_var.get(), "Bay")
        except ValueError as error:
            errors.append(str(error))
        designator = self.designator_var.get().strip()
        try:
            check_designator(designator)
        except ValueError as error:
            errors.append(str(error))
        try:
            lots = parse_numbers(self.lot_var.get(), "Lot")
        except ValueError as error:
            errors.append(str(error))
        if not errors and len(bays) * len(lots) > MAX_LABELS:
            errors.append(ERROR_TOO_MANY % (len(bays) * len(lots)))

        self.labels = [] if errors else build_labels(bays, designator, lots)

        if errors:
            self.summary_label.configure(text="\n".join(errors), foreground=ERROR_COLOR)
        else:
            summary = _plural(len(self.labels), "label")
            if len(bays) > 1:
                summary += "   (%s x %s each)" % (_plural(len(bays), "bay"), _plural(len(lots), "lot"))
            summary += "\n" + label_text(self.labels[0])
            if len(self.labels) > 1:
                summary += "   to   " + label_text(self.labels[-1])
            self.summary_label.configure(text=summary, foreground=self._normal_color)

        self._update_buttons()

        # Stay on the same page when the range changes, clamped to the new count
        self.page_index = max(0, min(self.page_index, self.page_count() - 1))
        self._update_nav()
        self._preview_gen += 1
        if self._preview_job is not None:
            self.after_cancel(self._preview_job)
            self._preview_job = None
        if not self.labels:
            self._show_preview_message(PREVIEW_EMPTY)
        else:
            self._preview_job = self.after(PREVIEW_DELAY_MS, self._start_preview)

    def _update_buttons(self):
        ready = bool(self.labels) and self._busy is None
        for button in (self.print_button, self.pdf_button):
            button.state(["!disabled"] if ready else ["disabled"])

    # Preview, LABELS_PER_PAGE labels at a time

    def page_count(self):
        return max(1, -(-len(self.labels) // LABELS_PER_PAGE))

    def page_labels(self):
        """The labels on the preview page shown"""
        start = self.page_index * LABELS_PER_PAGE
        return self.labels[start:start + LABELS_PER_PAGE]

    def flip_page(self, step):
        index = self.page_index + step
        if not self.labels or not 0 <= index < self.page_count():
            return
        self.page_index = index
        self._update_nav()
        self.refresh_preview()

    def _update_nav(self):
        if self.labels:
            self.position_label.configure(
                text="Page %d of %d" % (self.page_index + 1, self.page_count())
            )
        else:
            self.position_label.configure(text="")
        has_prev = bool(self.labels) and self.page_index > 0
        has_next = bool(self.labels) and self.page_index < self.page_count() - 1
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
        if not self.labels or self._preview_busy:
            return
        self._preview_busy = True
        render = self.preview_fn or label_backend.render_preview
        self._start_worker(
            "preview", self._preview_gen, render_page, render, self.page_labels(), self.dpi()
        )

    def _preview_done(self, gen, pngs, error):
        self._preview_busy = False
        if gen != self._preview_gen:
            if self.labels and self._preview_job is None:
                self._start_preview()
            return
        if error is not None:
            self._show_preview_message(
                "The preview could not be made.\n\n%s" % _error_text(error), ERROR_COLOR
            )
        elif not pngs or None in pngs:
            self._show_preview_message(PREVIEW_NONE)
        else:
            try:
                from PIL import Image

                images = [Image.open(io.BytesIO(png)).convert("L") for png in pngs]
            except Exception as error:
                self._show_preview_message(
                    "The preview could not be shown.\n\n%s" % _error_text(error), ERROR_COLOR
                )
                return
            self._preview_images = images
            self._preview_message = ""
            self._draw_preview()

    def _show_preview_message(self, text, color=HINT_COLOR):
        self._preview_images = []
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
        self._preview_photos = []
        width = max(canvas.winfo_width(), int(canvas.cget("width")))
        height = max(canvas.winfo_height(), int(canvas.cget("height")))

        if self._preview_images:
            from PIL import Image, ImageTk

            # Sized for a full page, so a short last page has the same label size
            first = self._preview_images[0]
            gaps = LABEL_GAP * (LABELS_PER_PAGE - 1)
            scale = min((width - 16) / first.width,
                        (height - 16 - gaps) / (LABELS_PER_PAGE * first.height))
            size = (max(1, round(first.width * scale)), max(1, round(first.height * scale)))
            # Blocky when enlarged, to show the printer's real dots
            method = Image.Resampling.NEAREST if scale >= 1 else Image.Resampling.LANCZOS
            block = LABELS_PER_PAGE * size[1] + gaps
            top = (height - block) / 2
            for row, image in enumerate(self._preview_images):
                photo = ImageTk.PhotoImage(image.resize(size, method), master=canvas)
                self._preview_photos.append(photo)  # keep a reference or Tk drops the image
                canvas.create_image(
                    width / 2, top + row * (size[1] + LABEL_GAP), image=photo, anchor="n"
                )
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
                elif kind == "pdf":
                    self._pdf_done(error)
                else:
                    self._print_done(error)
        except queue.Empty:
            pass
        if self._preview_busy or self._busy is not None:
            self._poll_job = self.after(POLL_MS, self._poll)

    def _start_busy(self, kind, text, fn, *args):
        self._busy = kind
        self._update_buttons()
        self.action_bar.show_busy(text)
        self.winfo_toplevel().configure(cursor="watch")
        self._start_worker(kind, None, fn, *args)

    def _end_busy(self):
        self._busy = None
        self.winfo_toplevel().configure(cursor="")
        self._update_buttons()

    # Printing

    def _print_target(self):
        """("windows", name) or ("network", address), or None after telling the user why not"""
        name = self.printer_var.get()
        if name == NETWORK_CHOICE:
            address = self.address_var.get().strip()
            try:
                zebra_printer.parse_address(address)
            except ValueError as error:
                messagebox.showwarning("Printer address", str(error), parent=self)
                self.address_entry.focus_set()
                return None
            return "network", address
        if not name:
            messagebox.showwarning(
                "No printer",
                "Choose the Zebra printer first.\n\nIf it is not in the list, check that "
                "it is plugged in and switched on, then click Refresh.",
                parent=self,
            )
            return None
        if not zebra_printer.is_zebra(name) and not messagebox.askyesno(
            "Not a label printer?",
            '"%s" does not look like a Zebra label printer.\n\n'
            "A normal printer would print pages of code instead of labels.\n\n"
            "Print anyway?" % name,
            icon="warning", default="no", parent=self,
        ):
            return None
        return "windows", name

    def _on_print(self):
        if not self.labels or self._busy is not None:
            return
        target = self._print_target()
        if target is None:
            return
        where = target[1]
        labels = list(self.labels)
        what = label_text(labels[0])
        if len(labels) > 1:
            what += "   to   " + label_text(labels[-1])
        if not messagebox.askyesno(
            "Print labels",
            "Print %s on:\n%s\n\n%s" % (_plural(len(labels), "label"), where, what),
            parent=self,
        ):
            return
        self._remember_printer()
        self._busy_where = where
        self._busy_count = len(labels)  # the form may change while printing
        send = self.send_fn or send_labels
        self._start_busy(
            "print", "Sending %s to the printer..." % _plural(len(labels), "label"),
            send, labels, self.dpi(), target,
        )

    def _print_done(self, error):
        count = self._busy_count
        self._end_busy()
        if error is not None:
            self.action_bar.clear()
            if isinstance(error, zebra_printer.PrinterError):
                text = str(error)
            else:
                text = "The labels could not be printed.\n\nDetails: %s" % _error_text(error)
            messagebox.showerror("Could not print", text, parent=self)
        else:
            self.mark_printed(count, self._busy_where)

    def mark_printed(self, count, where):
        self.action_bar.show_busy(
            "Sent %s to %s.\nIf nothing comes out, check that the printer is on "
            "and has labels loaded." % (_plural(count, "label"), where)
        )

    # Saving a PDF

    def _default_file_name(self):
        name = "labels_" + label_text(self.labels[0])
        if len(self.labels) > 1:
            name += "_to_" + label_text(self.labels[-1])
        return name + label_backend.BARCODE_FILE_EXTENSION

    def _on_save_pdf(self):
        if not self.labels or self._busy is not None:
            return
        extension = label_backend.BARCODE_FILE_EXTENSION
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save the labels as a PDF",
            initialfile=self._default_file_name(),
            defaultextension=extension,
            filetypes=[(label_backend.BARCODE_FILE_DESCRIPTION, "*" + extension)],
        )
        if not path:
            return
        self._busy_path = path
        self._start_busy(
            "pdf", "Saving...", label_backend.export_barcodes,
            make_request(list(self.labels)), path, self.dpi(),
        )

    def _pdf_done(self, error):
        path = self._busy_path
        self._end_busy()
        if error is not None:
            self.action_bar.clear()
            show_save_error(self, error, path, what="PDF file")
        else:
            self.mark_saved(path)

    def mark_saved(self, path):
        self.action_bar.show(path)

    def is_busy(self):
        """'print', 'pdf' or None"""
        return self._busy

    def reset(self):
        self.page_index = 0
        self.bay_var.set("")
        self.designator_var.set("")
        self.lot_var.set("")


def render_page(render, labels, dpi):
    """PNG bytes of each label on a preview page. Runs in a worker thread"""
    request = make_request(labels)
    return [render(request, index, dpi) for index in range(len(labels))]


def send_labels(labels, dpi, target):
    """Turn labels into ZPL and send them. Runs in a worker thread"""
    data = label_backend.make_zpl(make_request(labels), dpi)
    kind, where = target
    if kind == "network":
        zebra_printer.send_to_network_printer(where, data)
    else:
        job = "Labels %s" % label_text(labels[0])
        if len(labels) > 1:
            job += " to %s" % label_text(labels[-1])
        zebra_printer.send_to_windows_printer(where, data, job_name=job)
