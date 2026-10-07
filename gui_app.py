"""Main window. The two tabs, plus the Debug toggle in the bottom-right corner"""

import sys
import tkinter as tk
import tkinter.font as tkfont
import traceback
from tkinter import messagebox, ttk

from debug_panel import DebugPanel
from tab_barcode import BarcodeTab
from tab_process import ProcessTab

WINDOW_TITLE = "tobacco vision GUI test"

# Set to False to hide the Debug checkbox
SHOW_DEBUG_TOGGLE = True

BASE_FONT_SIZE = 11


def _load_drag_and_drop(root):
    """Try to switch on file drag-and-drop. Returns (available, problem)."""
    try:
        from tkinterdnd2 import TkinterDnD
    except ImportError:
        return False, "the tkinterdnd2 package is not installed"
    try:
        TkinterDnD._require(root)  # loads the tkdnd library into this window
    except Exception as error:
        return False, str(error) or error.__class__.__name__
    return True, ""


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(WINDOW_TITLE)
        self.root.report_callback_exception = self._on_unexpected_error
        self.dnd_available, self.dnd_problem = _load_drag_and_drop(self.root)
        self._setup_fonts()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.process_tab = ProcessTab(self.notebook, self)
        self.barcode_tab = BarcodeTab(self.notebook, self)
        self.notebook.add(self.process_tab, text="  Process tray photos  ")
        self.notebook.add(self.barcode_tab, text="  Make barcodes  ")

        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=8, pady=4)
        self.debug_panel = None
        self.debug_var = tk.BooleanVar(value=False)
        if SHOW_DEBUG_TOGGLE:
            ttk.Checkbutton(
                bottom,
                text="Debug",
                variable=self.debug_var,
                command=self._on_debug_toggled,
            ).pack(side="right")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._set_window_size()

    def run(self):
        self.root.mainloop()

    def _set_window_size(self):
        """Smallest size that shows everything plus a longer photo list if the screen is tall enough """
        root = self.root
        root.update_idletasks()
        width, height = root.winfo_reqwidth(), root.winfo_reqheight()
        root.minsize(width, height)
        row_height = tkfont.nametofont("TkDefaultFont").metrics("linespace") + 6
        room = root.winfo_screenheight() - height - 8 * row_height  # taskbar etc
        extra_rows = max(0, min(6, room // row_height))
        root.geometry("%dx%d" % (width, height + extra_rows * row_height))


    def _setup_fonts(self):
        default_font = tkfont.nametofont("TkDefaultFont")
        if BASE_FONT_SIZE:
            for name in ("TkDefaultFont", "TkTextFont", "TkHeadingFont"):
                tkfont.nametofont(name).configure(size=BASE_FONT_SIZE)
            self.root.option_add("*TCombobox*Listbox.font", default_font)
        # List rows do not grow with the font by themselves
        ttk.Style(self.root).configure(
            "Treeview", rowheight=default_font.metrics("linespace") + 6
        )

    def register_file_drop(self, widget, on_drop, on_enter=None, on_leave=None):
        """Let files from Windows Explorer be dropped onto `widget`"""
        from tkinterdnd2 import DND_FILES

        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", on_drop)
        if on_enter:
            widget.dnd_bind("<<DropEnter>>", on_enter)
        if on_leave:
            widget.dnd_bind("<<DropLeave>>", on_leave)

    # Debug panel

    def _on_debug_toggled(self):
        if self.debug_var.get():
            self.debug_panel = DebugPanel(self)
        else:
            self.close_debug_panel()

    def close_debug_panel(self):
        if self.debug_panel is not None:
            self.debug_panel.destroy()
            self.debug_panel = None
        self.debug_var.set(False)

    # Closing and unexpected errors

    def _on_close(self):
        question = None
        if self.process_tab.is_running():
            question = (
                "Still working",
                "Photos are still being processed.\n\nClose the program anyway?",
            )
        elif self.process_tab.has_unsaved_results():
            question = (
                "Results not saved",
                "The results have NOT been saved to Excel yet.\n\n"
                "Close the program anyway?",
            )
        if question and not messagebox.askyesno(
            question[0], question[1], icon="warning", default="no", parent=self.root
        ):
            return
        self.root.destroy()

    def _on_unexpected_error(self, error_type, error, trace):
        """Any bug in a button handler ends up here instead of vanishing."""
        details = "".join(traceback.format_exception(error_type, error, trace))
        if sys.stderr is not None:  # None in the windowed .exe
            sys.stderr.write(details)
        messagebox.showerror(
            "Something went wrong",
            "Something unexpected went wrong.\n\n"
            "You can keep using the program. If it happens again, close the "
            "program and open it again.\n\n"
            "Details: %s: %s" % (error_type.__name__, error),
            parent=self.root,
        )
