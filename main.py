"""Entry point for the tobacco vision GUI prototype

To run:   python main.py
"""

import sys


def _enable_high_dpi():
    """Ask Windows for sharp text """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main():
    _enable_high_dpi()
    from gui_app import App

    App().run()


if __name__ == "__main__":
    main()
