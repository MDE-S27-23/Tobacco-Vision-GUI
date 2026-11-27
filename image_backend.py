"""Backend for Tab 1 (Image Processing). PLACEHOLDERS for now

The GUI calls exactly these:

    start_batch()                           -> once before a run
    process_image(image_path)               -> once per photo, returns a dict
    export_results_to_excel(results, path)  -> "Save Excel file"

If a function fails, raise an exception with a short, plain message.
Raise SkipPhoto to skip a photo without calling it a failure.

TODO(backend): hook these up to the vision code (see the Prototype-Bounding-Boxes repo)
"""

import os
import time


class SkipPhoto(Exception):
    """Raise from process_image to skip a photo without calling it a failure"""


def start_batch():
    """Forget anything remembered from the previous run"""


def process_image(image_path):
    """Analyse ONE tray photo and return its result

    Currently it waits half a second and returns a dummy result
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError("The photo could not be found.")
    time.sleep(0.5)
    return {"note": "placeholder result"}


def export_results_to_excel(results, output_path):
    """Write the results of a finished batch to an Excel file

    Currently it writes one row per photo with the file name and status
    """
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Results"
    sheet.append(["Filename", "Status", "Result (placeholder)"])
    for result in results:
        if result["ok"]:
            status, detail = "OK", str(result["data"])
        elif result["skipped"]:
            status, detail = "Skipped", result["error"]
        else:
            status, detail = "Failed", result["error"]
        sheet.append([os.path.basename(result["image_path"]), status, detail])
    workbook.save(output_path)
