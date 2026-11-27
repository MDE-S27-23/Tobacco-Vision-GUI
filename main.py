"""Entry point for the tobacco vision GUI prototype

To run:   python main.py

    main.py --self-test RESULT.txt
        Checks that everything the program needs is inside it, without showing the window,
        and writes the result to RESULT.txt. Exit code 0 means OK. The build runs this
        on the finished .exe, so a missing library fails the build instead of the customer.
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


def self_test(result_path):
    """Import every module, draw labels, write a PDF, open and close the window"""
    import os
    import tempfile
    import traceback

    lines = []
    try:
        import openpyxl  # noqa: F401  Tab 1 Excel export
        import gui_app
        import label_backend
        import zebra_printer

        label_backend.self_test()
        lines.append("labels: OK")

        with tempfile.TemporaryDirectory() as folder:
            request = {"barcodes": [
                {"bay_number": "1", "type": "NC960", "lot_number": str(lot)} for lot in (1, 2)
            ]}
            path = os.path.join(folder, "test.pdf")
            label_backend.export_barcodes(request, path)
            if os.path.getsize(path) < 500:
                raise AssertionError("The test PDF is too small")
        lines.append("pdf: OK")

        lines.append("printers: %r" % (zebra_printer.list_printers(),))

        app = gui_app.App()
        app.root.update()
        lines.append("drag and drop: %s" % ("OK" if app.dnd_available else app.dnd_problem))
        app.root.destroy()
        lines.append("window: OK")
        code = 0
    except BaseException:
        lines.append(traceback.format_exc())
        code = 1
    lines.append("RESULT: %s" % ("PASS" if code == 0 else "FAIL"))
    with open(result_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")
    return code


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        sys.exit(self_test(sys.argv[2]))
    _enable_high_dpi()
    from gui_app import App

    App().run()


if __name__ == "__main__":
    main()
