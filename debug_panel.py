"""Debug panel
Opened with the "Debug" checkbox in the bottom-right corner of the main window"""

import os
import random
import time
import tkinter as tk
from tkinter import messagebox, ttk

import backend
from tab_process import DONE, FAILED, SKIPPED, WORKING
from ui_helpers import show_save_error

FAKE_FOLDER = os.path.join("C:\\", "Users", "Customer", "Documents")
FAKE_FAILURE = "No tray was found in the photo."
FAKE_DUPLICATE = "duplicate barcode (same as %s)"


class DebugPanel(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Debug panel")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", app.close_debug_panel)

        body = ttk.Frame(self, padding=10)
        body.pack(fill="both", expand=True)

        # Tab 1
        tab1 = ttk.LabelFrame(body, text='Tab 1 - "Process tray photos"', padding=8)
        tab1.pack(fill="x")
        self._buttons(
            tab1,
            [
                ("Empty (start)", self.t1_empty),
                ("5 photos ready", lambda: self.t1_ready(5)),
                ("60 photos ready (scrolling)", lambda: self.t1_ready(60)),
                ("Processing, frozen at 40%", self.t1_frozen),
                ("Finished, all OK", self.t1_finished),
                ("Finished, some failed", lambda: self.t1_finished((2, 6), (4, 8))),
                ("Finished, all failed", lambda: self.t1_finished(range(10), (3, 7))),
                ("Stopped by the user", self.t1_stopped),
                ("After Excel file saved", self.t1_saved),
                ("Message: wrong file type", self.t1_wrong_type),
                ("Message: results not saved", self.t1_unsaved_prompt),
                ("Message: Excel save failed", self.t1_save_error),
            ],
        )

        simulate = ttk.Frame(tab1)
        simulate.pack(fill="x", pady=(8, 0))
        self.photo_count = tk.IntVar(value=12)
        self.seconds_per_photo = tk.DoubleVar(value=0.5)
        self.fail_every = tk.IntVar(value=0)
        ttk.Label(simulate, text="Photos:").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(
            simulate, from_=1, to=500, width=5, textvariable=self.photo_count
        ).grid(row=0, column=1, padx=(4, 12))
        ttk.Label(simulate, text="Seconds each:").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(
            simulate, from_=0.0, to=10.0, increment=0.1, width=5,
            textvariable=self.seconds_per_photo,
        ).grid(row=0, column=3, padx=(4, 12))
        ttk.Label(simulate, text="Fail every Nth (0 = never):").grid(
            row=0, column=4, sticky="w"
        )
        ttk.Spinbox(
            simulate, from_=0, to=100, width=5, textvariable=self.fail_every
        ).grid(row=0, column=5, padx=(4, 0))
        self.duplicate_every = tk.IntVar(value=0)
        ttk.Label(simulate, text="Skip as duplicate every Nth (0 = never):").grid(
            row=1, column=0, columnspan=5, sticky="e", pady=(4, 0)
        )
        ttk.Spinbox(
            simulate, from_=0, to=100, width=5, textvariable=self.duplicate_every
        ).grid(row=1, column=5, padx=(4, 0), pady=(4, 0))
        ttk.Button(
            tab1, text="Run a simulated batch (animated)", command=self.t1_simulate
        ).pack(fill="x", pady=(6, 0))

        # Tab 2
        tab2 = ttk.LabelFrame(body, text='Tab 2 - "Make barcodes"', padding=8)
        tab2.pack(fill="x", pady=(10, 0))
        self._buttons(
            tab2,
            [
                ("Empty form (start)", self.t2_reset),
                ("One number: 7", lambda: self.t2_fill("7")),
                ("Range: 1-20", lambda: self.t2_fill("1-20")),
                ("List with gaps: 1-5, 9, 12-14", lambda: self.t2_fill("1-5, 9, 12-14")),
                ("Invalid input: abc", lambda: self.t2_fill("abc")),
                ("Out of range: 0-20000", lambda: self.t2_fill("0-20000")),
                ("Sample preview picture", self.t2_sample_preview),
                ("After barcodes saved", self.t2_saved),
                ("Message: save failed", self.t2_save_error),
            ],
        )

        # General
        general = ttk.LabelFrame(body, text="General", padding=8)
        general.pack(fill="x", pady=(10, 0))
        self._buttons(general, [("Message: unexpected error", self.unexpected_error)])
        if app.dnd_available:
            dnd_text = "Drag and drop: available"
        else:
            dnd_text = "Drag and drop: NOT available (%s)" % app.dnd_problem
        ttk.Label(general, text=dnd_text, wraplength=460, justify="left").pack(
            anchor="w", pady=(6, 0)
        )

        self._place_beside_main_window()


    def _buttons(self, parent, entries, columns=2):
        grid = ttk.Frame(parent)
        grid.pack(fill="x")
        for column in range(columns):
            grid.columnconfigure(column, weight=1, uniform="debug")
        for index, (text, command) in enumerate(entries):
            ttk.Button(grid, text=text, command=command).grid(
                row=index // columns, column=index % columns, sticky="ew", padx=2, pady=2
            )

    def _place_beside_main_window(self):
        root = self.app.root
        self.update_idletasks()
        x = root.winfo_rootx() + root.winfo_width() + 12
        x = max(0, min(x, self.winfo_screenwidth() - self.winfo_reqwidth() - 12))
        self.geometry("+%d+%d" % (x, max(0, root.winfo_rooty() - 30)))

    # Tab 1 states

    def _tab1(self):
        self.app.notebook.select(self.app.process_tab)
        return self.app.process_tab

    def _load_fake_photos(self, count):
        tab = self._tab1()
        tab.reset()
        tab.add_paths(
            [os.path.join(FAKE_FOLDER, "tray_%03d.jpg" % (n + 1)) for n in range(count)],
            check_exists=False,
        )
        return tab

    def _start_fake_run(self, count=10):
        """Photos loaded and 'running', but with no worker behind it."""
        tab = self._load_fake_photos(count)
        tab._set_state(tab.RUNNING)
        tab.show_progress(0, count, None)
        return tab

    def t1_empty(self):
        self._tab1().reset()

    def t1_ready(self, count):
        self._load_fake_photos(count)

    def t1_frozen(self):
        tab = self._start_fake_run()
        for index in range(4):
            tab.record_result(index, DONE, data={"note": "debug"})
        tab._set_item_status(4, WORKING)
        tab.show_progress(4, len(tab.items), tab.items[4]["path"])
        return tab

    def t1_finished(self, failed_indexes=(), skipped_indexes=()):
        """A finished run of 10 photos. Skipped wins where both are given."""
        tab = self._start_fake_run()
        failed_indexes, skipped_indexes = set(failed_indexes), set(skipped_indexes)
        for index in range(len(tab.items)):
            if index in skipped_indexes:
                earlier = os.path.basename(tab.items[index - 3]["path"])
                tab.record_result(index, SKIPPED, message=FAKE_DUPLICATE % earlier)
            elif index in failed_indexes:
                tab.record_result(index, FAILED, message=FAKE_FAILURE)
            else:
                tab.record_result(index, DONE, data={"note": "debug"})
        tab.finish()
        return tab

    def t1_stopped(self):
        self.t1_frozen()._on_stop()

    def t1_saved(self):
        tab = self.t1_finished()
        tab.mark_saved(os.path.join(FAKE_FOLDER, "tray_results_2026-10-07_0800.xlsx"))

    def t1_wrong_type(self):
        tab = self._tab1()
        tab.reset()
        tab.add_paths(
            [
                os.path.join(FAKE_FOLDER, name)
                for name in ("tray_001.jpg", "tray_002.jpg", "IMG_0412.HEIC", "notes.docx")
            ],
            check_exists=False,
        )

    def t1_unsaved_prompt(self):
        self.t1_finished()._on_new_batch()

    def t1_save_error(self):
        tab = self.t1_finished()
        show_save_error(
            tab,
            PermissionError(13, "Permission denied"),
            os.path.join(FAKE_FOLDER, "tray_results.xlsx"),
            what="Excel file",
        )

    def t1_simulate(self):
        try:
            count = max(1, int(self.photo_count.get()))
            seconds = max(0.0, float(self.seconds_per_photo.get()))
            fail_every = max(0, int(self.fail_every.get()))
            duplicate_every = max(0, int(self.duplicate_every.get()))
        except (tk.TclError, ValueError):
            messagebox.showwarning(
                "Debug", "The simulation settings must be numbers.", parent=self
            )
            return
        tab = self._load_fake_photos(count)
        counter = {"n": 0}

        def fake_process_image(path):
            counter["n"] += 1
            time.sleep(seconds)
            if duplicate_every and counter["n"] % duplicate_every == 0:
                raise backend.SkipPhoto(FAKE_DUPLICATE % "tray_001.jpg")
            if fail_every and counter["n"] % fail_every == 0:
                raise RuntimeError(FAKE_FAILURE)
            return {"note": "simulated"}

        tab.start_processing(process_fn=fake_process_image)

    # Tab 2 states

    def _tab2(self):
        self.app.notebook.select(self.app.barcode_tab)
        return self.app.barcode_tab

    def t2_reset(self):
        self._tab2().reset()

    def t2_fill(self, text):
        tab = self._tab2()
        tab.numbers_var.set(text)
        return tab

    def t2_sample_preview(self):
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            messagebox.showwarning(
                "Debug",
                "The sample picture needs Pillow.\n\nInstall it with:  pip install pillow",
                parent=self,
            )
            return
        # A page-shaped picture, as backend.render_page_preview would
        dpi = 100
        image = Image.new(
            "RGB",
            (round(backend.PAGE_WIDTH_IN * dpi), round(backend.PAGE_HEIGHT_IN * dpi)),
            "white",
        )
        draw = ImageDraw.Draw(image)
        rng = random.Random(128)
        for x, y, width, height in backend.pair_slots()[:6]:
            left, right = x * dpi + 30, (x + width) * dpi - 30
            top, bottom = y * dpi + 8, (y + height) * dpi - 8
            bar_x = left
            while bar_x < right:
                bar = rng.choice((2, 2, 4, 6))
                draw.rectangle([bar_x, top, bar_x + bar - 1, bottom], fill="black")
                bar_x += bar + rng.choice((2, 4, 6))
        try:
            font = ImageFont.load_default(size=40)
        except TypeError:  # older Pillow: small built-in font only
            font = ImageFont.load_default()
        draw.text((120, 700), "SAMPLE PICTURE\nfrom the backend", fill="black", font=font)

        tab = self._tab2()
        if not tab.barcode_texts:
            tab.numbers_var.set("1-20")
        if tab._preview_job is not None:  # skip the typing delay
            tab.after_cancel(tab._preview_job)
        tab._refresh_preview()
        tab.show_preview_image(image)

    def t2_saved(self):
        tab = self.t2_fill("1-20")
        tab.mark_saved(os.path.join(FAKE_FOLDER, tab._default_file_name()))

    def t2_save_error(self):
        tab = self.t2_fill("1-20")
        show_save_error(
            tab,
            OSError("There is not enough space on the disk."),
            os.path.join(FAKE_FOLDER, tab._default_file_name()),
            what="barcode file",
        )


    def unexpected_error(self):
        raise RuntimeError("Simulated bug from the debug panel")
