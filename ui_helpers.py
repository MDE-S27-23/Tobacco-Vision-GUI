"""Small widgets and helpers shared by both tabs"""

import contextlib
import os
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk


class WrappingLabel(ttk.Label):
    """A label whose text re-wraps to fit when the window is resized. `wraplength` is the starting value"""

    def __init__(self, parent, **kwargs):
        kwargs.setdefault("wraplength", 560)
        kwargs.setdefault("justify", "left")
        super().__init__(parent, **kwargs)
        self.bind("<Configure>", self._rewrap)
        self.bind("<Expose>", self._rewrap)  # first time it is shown

    def _rewrap(self, event):
        if not self.winfo_viewable():
            return  # sizes are not final until the label is on screen
        width = max(self.winfo_width() - 4, 100)
        if abs(width - int(str(self.cget("wraplength")))) > 2:
            self.configure(wraplength=width)


def faint_box(parent, padding=8):
    """A group box without a title"""
    red, green, blue = (value // 256 for value in parent.winfo_rgb(
        ttk.Style(parent).lookup("TFrame", "background") or "SystemButtonFace"
    ))
    outline = "#%02x%02x%02x" % (int(red * 0.84), int(green * 0.84), int(blue * 0.84))
    return tk.Frame(
        parent,
        padx=padding,
        pady=padding,
        background="#%02x%02x%02x" % (red, green, blue),
        highlightthickness=1,
        highlightbackground=outline,
        highlightcolor=outline,
    )


@contextlib.contextmanager
def busy_cursor(widget):
    """Show the 'busy' mouse pointer while a short task runs"""
    top = widget.winfo_toplevel()
    top.configure(cursor="watch")
    top.update_idletasks()
    try:
        yield
    finally:
        top.configure(cursor="")


def open_file(path):
    """Open a file with whatever program Windows uses for it"""
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def show_in_folder(path):
    """Open the folder containing `path` """
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])


def show_save_error(parent, error, path, what="file"):
    """Tell the user a save failed"""
    if isinstance(error, PermissionError):
        reason = (
            "The %s could not be saved.\n\n"
            "If a file with this name is already open in another program, "
            "close it and try again, or save under a different name." % what
        )
    else:
        reason = "The %s could not be saved.\n\nDetails: %s" % (
            what,
            str(error) or error.__class__.__name__,
        )
    messagebox.showerror("Could not save", reason + "\n\n" + path, parent=parent)


class SaveBar(ttk.Frame):
    """The row of buttons around saving, plus what appears after a save"""

    def __init__(self, parent, message_lines=1, wraplength=560):
        super().__init__(parent)
        self._path = None
        self.columnconfigure(1, weight=1)

        self.buttons = ttk.Frame(self)
        self.buttons.grid(row=0, column=0, sticky="w")
        self._after_save = ttk.Frame(self)
        self._after_save.grid(row=0, column=1, sticky="w", padx=(18, 0))
        ttk.Button(self._after_save, text="Open file", command=self._open).pack(
            side="left"
        )
        ttk.Button(
            self._after_save, text="Show in folder", command=self._show_folder
        ).pack(side="left", padx=(6, 0))
        self._after_save.grid_remove()

        line_height = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        self.rowconfigure(1, minsize=message_lines * line_height + 6)
        self._label = WrappingLabel(self, text="", width=1, wraplength=wraplength)
        self._label.grid(row=1, column=0, columnspan=2, sticky="new", pady=(6, 0))

    def full_width(self):
        """Width in pixels once all the buttons are showing"""
        self.update_idletasks()
        return self.buttons.winfo_reqwidth() + 18 + self._after_save.winfo_reqwidth()

    def show(self, path):
        self._path = path
        self._label.configure(text="Saved to:  %s" % path)
        self._after_save.grid()

    def clear(self):
        self._path = None
        self._label.configure(text="")
        self._after_save.grid_remove()

    def _exists(self):
        if self._path and os.path.exists(self._path):
            return True
        messagebox.showwarning(
            "File not found",
            "The file could not be found. It may have been moved or deleted."
            "\n\n%s" % self._path,
            parent=self,
        )
        return False

    def _open(self):
        if self._exists():
            open_file(self._path)

    def _show_folder(self):
        if self._exists():
            show_in_folder(self._path)
