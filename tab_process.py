"""Tab 1 add tray photos, process them one by one, save an Excel file"""

import datetime
import os
import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import backend
from ui_helpers import (
    SaveBar,
    WrappingLabel,
    busy_cursor,
    faint_box,
    open_file,
    show_save_error,
)

ALLOWED_EXTENSIONS = (".jpg", ".jpeg")

WAITING = "Waiting"
WORKING = "Processing..."
DONE = "Done"
SKIPPED = "Skipped"
FAILED = "Failed"


class ProcessTab(ttk.Frame):
    EMPTY = "empty"  # no photos in the list
    READY = "ready"  # photos listed, not processed yet
    RUNNING = "running"  # processing in progress
    FINISHED = "finished"  # processing done, results can be saved

    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app

        self.items = []  # one dict per photo: {"path", "status", "detail"}
        self.results = []  # filled while processing
        self.results_saved = False
        self.state = self.EMPTY

        self._queue = queue.Queue()
        self._run_id = 0
        self._worker = None
        self._cancel = threading.Event()

        self._build()
        self._set_state(self.EMPTY)

    # Layout

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # list
        step1 = faint_box(self)
        step1.grid(row=0, column=0, sticky="nsew")
        step1.columnconfigure(0, weight=1)
        step1.rowconfigure(1, weight=1)
        default_font = tkfont.nametofont("TkDefaultFont")
        line_height = default_font.metrics("linespace")
        char_width = default_font.measure("0")  # column widths follow the text size

        buttons = ttk.Frame(step1)
        buttons.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.add_button = ttk.Button(
            buttons, text="Add photos...", command=self._on_browse
        )
        self.add_button.pack(side="left")
        self.remove_button = ttk.Button(
            buttons, text="Remove selected", command=self._on_remove_selected
        )
        self.remove_button.pack(side="left", padx=(6, 0))
        self.remove_all_button = ttk.Button(
            buttons, text="Remove all", command=self._on_remove_all
        )
        self.remove_all_button.pack(side="left", padx=(6, 0))
        self.count_var = tk.StringVar()
        ttk.Label(buttons, textvariable=self.count_var).pack(side="right")

        list_frame = ttk.Frame(step1)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            list_frame,
            columns=("number", "filename", "status"),
            show="headings",
            height=5,
            selectmode="extended",
        )
        self.tree.heading("number", text="#")
        self.tree.heading("filename", text="Filename", anchor="w")
        self.tree.heading("status", text="Status", anchor="w")
        self.tree.column("number", width=5 * char_width, stretch=False, anchor="e")
        self.tree.column("filename", width=24 * char_width, anchor="w")
        self.tree.column("status", width=46 * char_width, anchor="w")
        self.tree.tag_configure("failed", foreground="#b00020")
        self.tree.tag_configure("skipped", foreground="#8a5a00")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.tree.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", lambda event: self._update_buttons())
        self.tree.bind("<Double-1>", self._on_double_click)

        # Processing
        step2 = faint_box(self)
        step2.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        step2.columnconfigure(2, weight=1)

        self.start_button = ttk.Button(
            step2, text="Start processing", command=self.start_processing
        )
        self.start_button.grid(row=0, column=0)
        self.stop_button = ttk.Button(step2, text="Stop", command=self._on_stop)
        self.stop_button.grid(row=0, column=1, padx=(6, 12))
        self.progress = ttk.Progressbar(step2, mode="determinate")
        self.progress.grid(row=0, column=2, sticky="ew")

        # Room for two lines of text, so the layout never jumps.
        step2.rowconfigure(1, minsize=2 * line_height + 6)
        self.status_var = tk.StringVar()
        WrappingLabel(step2, textvariable=self.status_var).grid(
            row=1, column=0, columnspan=3, sticky="new", pady=(6, 0)
        )

        # Saving
        step3 = faint_box(self)
        step3.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        step3.columnconfigure(0, weight=1)

        self.save_bar = SaveBar(step3)
        self.save_bar.grid(row=0, column=0, sticky="ew")
        self.save_button = ttk.Button(
            self.save_bar.buttons, text="Save Excel file...", command=self._on_save_excel
        )
        self.save_button.pack(side="left")
        self.new_batch_button = ttk.Button(
            self.save_bar.buttons, text="Start a new batch", command=self._on_new_batch
        )
        self.new_batch_button.pack(side="left", padx=(6, 0))

        # Photos can be dropped on the list
        if self.app.dnd_available:
            for widget in (self, step1, self.tree, step2, step3):
                self.app.register_file_drop(widget, self._on_drop)

    # State handling

    def _set_state(self, state, status=None):
        """Switch state and enable the buttons that are appropriate for the current state"""
        self.state = state
        self._update_buttons()

        count = len(self.items)
        if count == 0:
            self.count_var.set("No photos added")
        else:
            self.count_var.set("%d photo%s added" % (count, "" if count == 1 else "s"))

        if state in (self.EMPTY, self.READY):
            self.progress.configure(value=0, maximum=1)
        if status is None and state == self.EMPTY and self.app.dnd_available:
            status = (
                "Drag your tray photos (.jpg) into the list above, "
                'or click "Add photos...".'
            )
        elif status is None and state == self.EMPTY:
            status = 'Click "Add photos..." to choose your tray photos (.jpg).'
        elif status is None and state == self.READY:
            status = 'Ready. Click "Start processing".'
        if status is not None:
            self.status_var.set(status)

    def _update_buttons(self):
        def enable(widget, on):
            widget.state(["!disabled"] if on else ["disabled"])

        state = self.state
        succeeded = sum(1 for result in self.results if result["ok"])
        enable(self.add_button, state != self.RUNNING)
        enable(self.remove_button, state == self.READY and bool(self.tree.selection()))
        enable(self.remove_all_button, state == self.READY)
        enable(self.start_button, state == self.READY)
        enable(self.stop_button, state == self.RUNNING)
        enable(self.save_button, state == self.FINISHED and succeeded > 0)
        enable(self.new_batch_button, state == self.FINISHED)

    def is_running(self):
        return self.state == self.RUNNING

    def has_unsaved_results(self):
        return (
            self.state == self.FINISHED
            and not self.results_saved
            and any(result["ok"] for result in self.results)
        )

    # Step 1, the photo list

    def _refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.items):
            self.tree.insert("", "end", iid=str(index), values=self._row(index))
            self._apply_row_tag(index)

    def _row(self, index):
        item = self.items[index]
        status = item["status"]
        if item["detail"]:
            status += ": " + item["detail"]
        return (index + 1, os.path.basename(item["path"]), status)

    def _apply_row_tag(self, index):
        tag = {FAILED: "failed", SKIPPED: "skipped"}.get(self.items[index]["status"])
        self.tree.item(str(index), tags=(tag,) if tag else ())

    def _set_item_status(self, index, status, detail=""):
        self.items[index]["status"] = status
        self.items[index]["detail"] = detail
        self.tree.item(str(index), values=self._row(index))
        self._apply_row_tag(index)
        self.tree.see(str(index))

    def add_paths(self, paths, check_exists=True):
        """Add photos (or folders of photos) to the list
        Files that are not .jpg are refused with a message
        """
        if self.state == self.RUNNING:
            return
        if self.state == self.FINISHED and not self._confirm_new_batch(adding=True):
            return

        candidates = []
        empty_folders = 0
        for path in paths:
            if check_exists and os.path.isdir(path):
                inside = [
                    os.path.join(path, name)
                    for name in os.listdir(path)
                    if name.lower().endswith(ALLOWED_EXTENSIONS)
                    and os.path.isfile(os.path.join(path, name))
                ]
                if not inside:
                    empty_folders += 1
                candidates.extend(inside)
            else:
                candidates.append(path)
        candidates.sort(key=lambda p: os.path.basename(p).lower())

        def key(path):
            return os.path.normcase(os.path.abspath(path))

        already_listed = {key(item["path"]) for item in self.items}
        added = 0
        duplicates = 0
        missing = 0
        wrong_type = []
        for path in candidates:
            if not path.lower().endswith(ALLOWED_EXTENSIONS):
                wrong_type.append(os.path.basename(path))
            elif check_exists and not os.path.isfile(path):
                missing += 1
            elif key(path) in already_listed:
                duplicates += 1
            else:
                already_listed.add(key(path))
                self.items.append({"path": path, "status": WAITING, "detail": ""})
                added += 1

        self._refresh_list()
        if self.items:
            self.tree.see(str(len(self.items) - 1))

        self._set_state(self.READY if self.items else self.EMPTY)

        # Tell the user about anything that was left out
        problems = []
        if wrong_type:
            shown = wrong_type[:8]
            names = "\n".join("    " + name for name in shown)
            if len(wrong_type) > len(shown):
                names += "\n    ...and %d more" % (len(wrong_type) - len(shown))
            problems.append(
                "%d file%s not added because only .jpg photos can be used:\n\n%s"
                % (len(wrong_type), " was" if len(wrong_type) == 1 else "s were", names)
            )
        if empty_folders:
            problems.append("No .jpg photos were found in the folder.")
        if missing:
            problems.append(
                "%d photo%s could not be found." % (missing, "" if missing == 1 else "s")
            )
        if problems:
            messagebox.showwarning(
                "Some files were not added", "\n\n".join(problems), parent=self
            )
        elif duplicates and not added:
            messagebox.showinfo(
                "Already in the list",
                "These photos are already in the list, so nothing was added.",
                parent=self,
            )

    def _on_browse(self):
        if self.state == self.RUNNING:
            return
        patterns = ["*.jpg", "*.jpeg"]
        if sys.platform != "win32":
            patterns += ["*.JPG", "*.JPEG"]
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Choose tray photos",
            filetypes=[("JPG photos", " ".join(patterns))],
        )
        if paths:
            self.add_paths(list(paths))

    def _on_drop(self, event):
        paths = list(self.tk.splitlist(event.data))
        self.after(10, lambda: self.add_paths(paths))   # Let the drag finish before any message box opens
        return event.action

    def _on_double_click(self, event):
        """Open the double-clicked photo in the user's own image viewer."""
        row = self.tree.identify_row(event.y)
        if not row:
            return  # the header or the empty space below the last row
        path = self.items[int(row)]["path"]
        if not os.path.isfile(path):
            messagebox.showwarning(
                "Photo not found",
                "The photo could not be found. It may have been moved, renamed "
                "or deleted.\n\n%s" % path,
                parent=self,
            )
            return
        open_file(path)

    def _on_remove_selected(self):
        selected = {int(iid) for iid in self.tree.selection()}
        self.items = [
            item for index, item in enumerate(self.items) if index not in selected
        ]
        self._refresh_list()
        self._set_state(self.READY if self.items else self.EMPTY)

    def _on_remove_all(self):
        self.reset()

    def reset(self):
        """Back to the empty starting state."""
        self._cancel.set()  # stop a run that is still going
        self._cancel = threading.Event()
        self._run_id += 1  # ignore anything that run still reports
        self._worker = None
        self.items = []
        self.results = []
        self.results_saved = False
        self._refresh_list()
        self.save_bar.clear()
        self._set_state(self.EMPTY)

    # Step 2, processing

    def start_processing(self, process_fn=None):
        """Process every photo in the list, one by one"""
        if self.state != self.READY:
            return
        if process_fn is None:
            process_fn = backend.process_image
            try:
                backend.start_batch()
            except Exception as error:
                messagebox.showerror(
                    "Could not start",
                    "Processing could not be started.\n\nDetails: %s"
                    % (str(error) or error.__class__.__name__),
                    parent=self,
                )
                return

        self.results = []
        self.results_saved = False
        self.save_bar.clear()
        for index in range(len(self.items)):
            self.items[index]["status"] = WAITING
            self.items[index]["detail"] = ""
        self._refresh_list()

        self._run_id += 1
        self._cancel = threading.Event()
        self._set_state(self.RUNNING)
        self.show_progress(0, len(self.items), None)

        paths = [item["path"] for item in self.items]
        self._worker = threading.Thread(
            target=self._work,
            args=(self._run_id, paths, process_fn, self._cancel),
            daemon=True,
        )
        self._worker.start()
        self.after(50, self._poll)

    def _work(self, run_id, paths, process_fn, cancel):
        """Runs in the background thread, talks to the GUI via the queue"""
        for index, path in enumerate(paths):
            if cancel.is_set():
                self._queue.put((run_id, "cancelled", None, None))
                return
            self._queue.put((run_id, "started", index, None))
            try:
                data = process_fn(path)
            except backend.SkipPhoto as skip:
                self._queue.put((run_id, "skipped", index, str(skip) or "skipped"))
            except Exception as error:  # one bad photo does not stop the batch
                message = str(error) or error.__class__.__name__
                self._queue.put((run_id, "failed", index, message))
            else:
                self._queue.put((run_id, "done", index, data))
        self._queue.put((run_id, "finished", None, None))

    def _poll(self):
        """Runs in the GUI thread: apply what the worker reported."""
        try:
            while True:
                run_id, kind, index, payload = self._queue.get_nowait()
                if run_id != self._run_id:
                    continue  # left over from an earlier run
                if kind == "started":
                    self._set_item_status(index, WORKING)
                    self.show_progress(
                        len(self.results), len(self.items), self.items[index]["path"]
                    )
                elif kind == "done":
                    self.record_result(index, DONE, data=payload)
                elif kind == "skipped":
                    self.record_result(index, SKIPPED, message=payload)
                elif kind == "failed":
                    self.record_result(index, FAILED, message=payload)
                elif kind == "finished":
                    self.finish()
                    return
                elif kind == "cancelled":
                    self._cancelled()
                    return
        except queue.Empty:
            pass
        if self.state == self.RUNNING:
            self.after(50, self._poll)

    def record_result(self, index, status, data=None, message=None):
        """Store the outcome of one photo"""
        self.results.append(
            {
                "image_path": self.items[index]["path"],
                "ok": status == DONE,
                "skipped": status == SKIPPED,
                "data": data,
                "error": message,
            }
        )
        self._set_item_status(index, status, message or "")
        self.progress.configure(value=len(self.results))

    def show_progress(self, done, total, current_path):
        self.progress.configure(maximum=max(total, 1), value=done)
        if self._cancel.is_set():
            return  # keep the "Stopping..." text
        if current_path is None:
            self.status_var.set("Starting...")
        else:
            self.status_var.set(
                "Processing photo %d of %d:  %s"
                % (done + 1, total, os.path.basename(current_path))
            )

    def finish(self):
        total = len(self.items)
        succeeded = sum(1 for result in self.results if result["ok"])
        skipped = sum(1 for result in self.results if result["skipped"])
        failed = len(self.results) - succeeded - skipped
        self.progress.configure(maximum=max(total, 1), value=total)

        check_hint = "Double-click a file in the list to open the photo and check it."
        if succeeded == total:
            text = 'Finished. All %d photos were processed. Now click "Save Excel file...".' % total
            if total == 1:
                text = 'Finished. The photo was processed. Now click "Save Excel file...".'
        else:
            problems = []
            if skipped:
                problems.append("%d skipped" % skipped)
            if failed:
                problems.append("%d failed" % failed)
            if succeeded:
                text = "Finished. %d of %d photos were processed (%s). %s" % (
                    succeeded, total, ", ".join(problems), check_hint,
                )
            else:
                text = "Finished, but none of the photos were processed (%s). %s" % (
                    ", ".join(problems), check_hint,
                )
        self.status_var.set(text)
        self._worker = None
        self._set_state(self.FINISHED)

    def _on_stop(self):
        self._cancel.set()
        self.stop_button.state(["disabled"])
        self.status_var.set("Stopping after the current photo...")
        if self._worker is None or not self._worker.is_alive():
            self._cancelled()

    def _cancelled(self):
        self._run_id += 1
        self._worker = None
        self._cancel = threading.Event()
        self.results = []
        for item in self.items:
            item["status"] = WAITING
            item["detail"] = ""
        self._refresh_list()
        self._set_state(
            self.READY,
            'Stopped. Nothing was saved. Click "Start processing" to run again.',
        )

    # Step 3, saving

    def _on_save_excel(self):
        default_name = "tray_results_%s.xlsx" % datetime.datetime.now().strftime(
            "%Y-%m-%d_%H%M"
        )
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save the results as an Excel file",
            initialfile=default_name,
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
        )
        if not path:
            return
        try:
            with busy_cursor(self):
                backend.export_results_to_excel(self.results, path)
        except Exception as error:
            show_save_error(self, error, path, what="Excel file")
            return
        self.mark_saved(path)

    def mark_saved(self, path):
        self.results_saved = True
        self.save_bar.show(path)

    def _confirm_new_batch(self, adding=False):
        """Ask before throwing away finished results"""
        if self.has_unsaved_results():
            go_ahead = messagebox.askyesno(
                "Results not saved",
                "The results of this batch have NOT been saved to Excel yet.\n\n"
                "Start a new batch and throw these results away?",
                icon="warning",
                default="no",
                parent=self,
            )
        elif adding:
            go_ahead = messagebox.askyesno(
                "Start a new batch?",
                "This batch is finished.\n\n"
                "Start a new batch with the photos you just added?",
                parent=self,
            )
        else:
            go_ahead = True
        if go_ahead:
            self.reset()
        return go_ahead

    def _on_new_batch(self):
        self._confirm_new_batch()
