"""Light and dark mode

Follows the Windows setting "Choose your app mode" (Settings > Personalization > Colors),
also when it is changed while the program is open. Light mode is the normal Windows look
(ttk's "vista" theme). Dark mode is ttk's "clam" theme with dark colors, plus a dark title
bar. Windows' own message boxes and file dialogs stay light, those are drawn by Windows.

Widgets with their own colors (plain tk widgets, list colors, hint texts) register a
function with on_change(), which runs now and again after every switch. Hint and error
texts use the "Hint.TLabel" and "Error.TLabel" styles instead.
"""

import sys
import tkinter as tk
from tkinter import ttk

CHECK_EVERY_MS = 2000   # how often the Windows setting is looked at

LIGHT = {
    "window": "SystemButtonFace",
    "text": "SystemButtonText",
    "hint": "#606060",
    "error": "#b00020",
    "failed": "#b00020",
    "warning": "#c05000",
    "skipped": "#7a7a7a",
    "preview": "#dcdcdc",      # behind the label preview
    "list": "SystemWindow",
    "list_text": "SystemWindowText",
    "selected": "SystemHighlight",
    "selected_text": "SystemHighlightText",
}

DARK = {
    "window": "#202020",
    "text": "#e6e6e6",
    "hint": "#a8a8a8",
    "error": "#ff7b7b",
    "failed": "#ff7b7b",
    "warning": "#ffad5c",
    "skipped": "#8c8c8c",
    "preview": "#3a3a3a",
    "list": "#2b2b2b",
    "list_text": "#e6e6e6",
    "selected": "#2f5f9a",
    "selected_text": "#ffffff",
    # only used for the ttk styles below
    "button": "#333333",
    "button_hover": "#3d3d3d",
    "button_pressed": "#484848",
    "border": "#505050",
    "disabled": "#7a7a7a",
    "trough": "#2b2b2b",
    "progress": "#4c9be8",
}

_root = None
_light_theme = None
_dark = None
_forced = None      # None follows Windows, True / False set by set_mode()
_callbacks = []
_style_extras = []


def system_uses_dark():
    """True when Windows is set to dark mode for apps"""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except OSError:  # older Windows without the setting
        return False


def is_dark():
    return bool(_dark)


def color(name):
    return (DARK if _dark else LIGHT)[name]


def start(root, style_extras=None):
    """Use the Windows setting now and keep following it. Call once, before the widgets
    are made. style_extras(style) runs after every switch, for style settings that belong
    to every theme (like the list row height)."""
    global _root, _light_theme
    _root = root
    _light_theme = ttk.Style(root).theme_use()
    if style_extras:
        _style_extras.append(style_extras)
    _apply(_wanted())
    style_window(root)
    root.after(CHECK_EVERY_MS, _check)


def on_change(callback):
    """Run callback() now and after every switch between light and dark"""
    _callbacks.append(callback)
    callback()


def style_window(window):
    """Background and title bar of a window (the main one or a tk.Toplevel)"""
    def paint():
        window.configure(background=color("window"))
        if window.winfo_ismapped():  # before that it would undo the window's position
            _title_bar(window, _dark)
    on_change(paint)
    # When it opens: no frame redraw, that would make Windows ignore its set position
    window.bind("<Map>", lambda event: _title_bar(window, _dark, redraw=False)
                if event.widget is window else None, add="+")


def outline_for(background):
    """A faint outline that goes with `background`, a little toward the text color"""
    back = _root.winfo_rgb(background)
    text = _root.winfo_rgb(color("text"))
    mix = [int((b + (t - b) * 0.16) / 256) for b, t in zip(back, text)]
    return "#%02x%02x%02x" % tuple(mix)


def mode():
    """"system", "light" or "dark" """
    return "system" if _forced is None else ("dark" if _forced else "light")


def set_mode(new_mode):
    """"system" follows Windows, "light" or "dark" stay so (the debug panel's switch)"""
    global _forced
    _forced = {"system": None, "light": False, "dark": True}[new_mode]
    if _wanted() != _dark:
        _apply(_wanted())


def _wanted():
    return system_uses_dark() if _forced is None else _forced


def _check():
    try:
        dark = _wanted()
        if dark != _dark:
            _apply(dark)
    finally:
        _root.after(CHECK_EVERY_MS, _check)


def _apply(dark):
    global _dark
    _dark = dark
    style = ttk.Style(_root)
    if dark:
        style.theme_use("clam")
        _dark_styles(style)
    else:
        style.theme_use(_light_theme)
    style.configure("Hint.TLabel", foreground=color("hint"))
    style.configure("Error.TLabel", foreground=color("error"))
    for extra in _style_extras:
        extra(style)
    _list_colors()
    for callback in list(_callbacks):
        try:
            callback()
        except tk.TclError:  # its widget was closed
            _callbacks.remove(callback)


def _dark_styles(style):
    c = DARK
    style.configure(
        ".",
        background=c["window"], foreground=c["text"], fieldbackground=c["list"],
        bordercolor=c["border"], lightcolor=c["window"], darkcolor=c["window"],
        troughcolor=c["trough"], selectbackground=c["selected"],
        selectforeground=c["selected_text"], insertcolor=c["text"],
        arrowcolor=c["text"], focuscolor=c["border"],
    )
    style.map(".", foreground=[("disabled", c["disabled"])])
    style.configure("TButton", background=c["button"], lightcolor=c["button"],
                    darkcolor=c["button"])
    style.map(
        "TButton",
        background=[("disabled", c["window"]), ("pressed", c["button_pressed"]),
                    ("active", c["button_hover"])],
        lightcolor=[("pressed", c["button_pressed"]), ("active", c["button_hover"])],
        darkcolor=[("pressed", c["button_pressed"]), ("active", c["button_hover"])],
        bordercolor=[("focus", c["progress"])],
    )
    for name in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(name, fieldbackground=c["list"], background=c["button"],
                        lightcolor=c["list"], darkcolor=c["list"])
        style.map(
            name,
            fieldbackground=[("disabled", c["window"]), ("readonly", c["list"])],
            foreground=[("disabled", c["disabled"])],
            background=[("pressed", c["button_pressed"]), ("active", c["button_hover"])],
            bordercolor=[("focus", c["progress"])],
            lightcolor=[("focus", c["list"])],
            selectbackground=[("readonly", "!focus", c["list"]),
                              ("readonly", "focus", c["selected"])],
            selectforeground=[("readonly", "!focus", c["text"])],
        )
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, indicatorbackground=c["list"], indicatorforeground=c["text"])
        style.map(name,
                  background=[("active", c["window"])],
                  indicatorbackground=[("pressed", c["button_pressed"]),
                                       ("active", c["button_hover"])])
    style.configure("Treeview", background=c["list"], fieldbackground=c["list"],
                    foreground=c["list_text"], lightcolor=c["list"], darkcolor=c["list"])
    style.map("Treeview", background=[("selected", c["selected"])],
              foreground=[("selected", c["selected_text"])])
    style.configure("Treeview.Heading", background=c["button"], lightcolor=c["button"],
                    darkcolor=c["button"])
    style.map("Treeview.Heading", background=[("active", c["button_hover"])])
    style.configure("TNotebook", background=c["window"], lightcolor=c["window"],
                    darkcolor=c["window"])
    style.configure("TNotebook.Tab", background=c["trough"], lightcolor=c["trough"],
                    darkcolor=c["trough"], padding=(8, 3))
    style.map("TNotebook.Tab",
              background=[("selected", c["window"]), ("active", c["button_hover"])],
              lightcolor=[("selected", c["window"])],
              expand=[("selected", (1, 2, 1, 0))])
    style.configure("TLabelframe", lightcolor=c["window"], darkcolor=c["window"])
    style.configure("TProgressbar", background=c["progress"], lightcolor=c["progress"],
                    darkcolor=c["progress"], bordercolor=c["border"])
    style.configure("TScrollbar", background=c["button"], lightcolor=c["button"],
                    darkcolor=c["button"], bordercolor=c["border"])
    style.map("TScrollbar", background=[("pressed", c["button_pressed"]),
                                        ("active", c["button_hover"])])


def _list_colors():
    """The drop-down lists of the comboboxes are plain tk listboxes"""
    values = {
        "background": color("list"), "foreground": color("list_text"),
        "selectBackground": color("selected"), "selectForeground": color("selected_text"),
    }
    for option, value in values.items():
        _root.option_add("*TCombobox*Listbox." + option, value)

    def walk(widget):
        for child in widget.winfo_children():
            if child.winfo_class() == "TCombobox":
                try:
                    popdown = child.tk.call("ttk::combobox::PopdownWindow", child)
                    child.tk.call(
                        "%s.f.l" % popdown, "configure",
                        "-background", values["background"],
                        "-foreground", values["foreground"],
                        "-selectbackground", values["selectBackground"],
                        "-selectforeground", values["selectForeground"],
                    )
                except tk.TclError:
                    pass
            walk(child)

    walk(_root)


def _title_bar(window, dark, redraw=True):
    """Dark or light title bar (Windows 10 2004 and later, Windows 11)"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE, and before 20H1
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                break
        if redraw:  # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x1 | 0x2 | 0x4 | 0x20)
    except Exception:
        pass  # only looks
