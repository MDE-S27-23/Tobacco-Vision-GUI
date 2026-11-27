# tobacco vision GUI test

Tkinter front end for the seedling-tray project. Runs on a Windows PC as a single
`.exe` that needs no Python or setup.

## Run

    pip install -r requirements.txt
    python main.py

## Build the .exe

Run `build_exe.bat`. The output should be in `dist\TobaccoVisionGUI.exe`.

The build then runs the finished exe with `--self-test`, which imports everything,
draws labels, writes a test PDF and opens the window. GitHub Actions does the same
with Python hidden from the exe, so a package missing from `requirements.txt` fails
the build instead of the customer's PC.

**Every package the code imports must be in `requirements.txt`.** The exe only
contains what was installed when it was built.

## Files

| File | What it is |
|---|---|
| `main.py` | Entry point, and `--self-test` |
| `gui_app.py` | Main window, the two tabs, the Debug checkbox |
| `tab_process.py` | Tab 1 "Image Processing": photo list (drag and drop), progress bar, save Excel |
| `image_backend.py` | Tab 1 backend: runs one photo through the steps below, status text, retakes, check pictures |
| `qr_reader.py` | Reads the QR labels in a full-size photo (zxing-cpp) |
| `tray_grid.py` | Finds the tray's cells and straightens the tray to 128 pixels per cell |
| `vision/` | Seedling detection, the Prototype-Bounding-Boxes repo's Version3 code (commit 411b9d8), unchanged |
| `tray_report.py` | The combined Excel report of a batch |
| `tray_testing.py` | A drawn tray photo for the self-test |
| `test_photos/` | Tray photos with labels, the results they should give, and a checker (see its README) |
| `tab_labels.py` | Tab 2 "Label Printing": bay / variant / lot form, printer choice, label preview, print, save PDF |
| `label_backend.py` | Tab 2 backend, `backend.py` from the Barcode-Generation repo: draws the 3 x 1 inch QR labels, makes the PDF and the Zebra ZPL |
| `zebra_printer.py` | Sends ZPL to the printer (Windows print queue or network IP) |
| `app_settings.py` | Remembers the printer and its resolution in `%APPDATA%\TobaccoVisionGUI` |
| `debug_panel.py` | Debug window with a button for every GUI state |
| `ui_helpers.py` | Small shared widgets |
| `theme.py` | Light and dark mode, following the Windows setting |

## Image processing

The customer's trays are 288-cell float trays, 12 x 24 cells, holding two lots of 12 x 12
side by side. Each lot has a QR label (from the Label Printing tab) lying on its half,
covering 3 cells. For each photo:

1. **QR labels** are read on the full-size photo. A label's squares are only 6-7 pixels
   wide there, too small to read once the photo is shrunk. zxing-cpp read all 20 labels
   in the test photos in about 0.07 s per photo. OpenCV's QR readers read 14-17 and took
   about 0.5 s, so OpenCV only gets a second try when fewer than 2 labels are found.
2. **The tray's cells** are found as dark squares of soil inside bright walls
   (`tray_grid.py`). This also corrects a tilted camera and the lens bending lines near the
   photo's edges, and adds edge rows/columns until the tray is 12 x 24. Version3's own grid
   detector often dropped an edge row or column on these trays, because the outer walls run
   into the tray's white rim. Of 86 customer photos, every one that shows the whole tray
   comes out 12 x 24; the others are close-ups or cut off at the photo's edge, and say so.
3. **The tray is straightened** to exactly 128 pixels per cell (about a 3200 px wide
   photo), taken from the full-size photo. Version3's seedling detection runs on that, with
   its own settings unchanged. Compared with 256 pixels per cell (full-size detail), it
   finds the same seedlings in 99.8% of cells, sizes within 0.5%, in a third of the time.
4. **Cells under a label** are marked "covered" and left out of the statistics. Each half
   gets the label lying on it.

About 1 second per photo. Reading the labels on the full-size photo and the seedlings on the
128 px/cell tray, instead of everything at full size, saves about 1.35 s per photo (57%).

Seedling sizes are leaf areas seen from above, in mm², and **assume the cells are 1.0 inch
apart** (`CELL_PITCH_IN` in `image_backend.py`). The Excel file also shows the spacing the
QR codes' printed size implies; once that looks steady across photos, use it there.

If the same label shows up in two photos (a retake, usually of a blurry photo), only the
newest photo is used, by the camera's clock. The older photo shows "Skipped" and is left
out of the Excel file.

Photos with something to check (no label, two labels on one half, tray partly outside the
photo) are orange, failed photos are red; double-click them to open a marked-up copy. The
marked-up copies live in a temporary folder that is deleted when the batch is reset or
the program closes (or, after a crash, the next time it starts).

## Labels

Each label is identified as `Bay<bay>-<variant>-<lot>`, like `Bay1-NC960-29`.
The bay and the lot take 1-999 and ranges (`1-5`, `1-5, 8`). The variant is letters and
digits only. Lots are inside bays: bays `1-2` with lots `1-5` make Bay1 lots 1-5, then
Bay2 lots 1-5.

Layout: the QR code (high error correction) on the left; to its right "Bay 1" (left) and
"Lot 29" (right) on the top row and the variant centred below, the same order as in the
QR code's text. The layout constants are at the top of `label_backend.py`.
`label_backend.py` is a copy of `backend.py` in the Barcode-Generation repo, so keep the two the same.

- No ink within 0.08" of any edge, since the printer may shift the label slightly. The self-test checks this.
- The QR code keeps its 4-module white border on the label, so it scans even on a dark stake.
  With those two rules it is as large as a 1" label allows: about 0.74" at 203 dpi and 0.75" at
  300/600 dpi. Modules must be whole printer dots, so at 203 dpi the next size up would not fit.

The customer's printer is a Zebra ZM400 (2008 firmware V53.16.5Z), so the ZPL sticks to
long-standing commands (`^PW ^LL ^LH ^FO ^GF ^PQ`, no `^CI28`). Its Windows driver is named
like `ZDesigner ZM400 200 dpi (ZPL)`; "200 dpi" means 203 and is picked up automatically.

The label is drawn once as a 1-bit picture at the printer's resolution (203, 300 or 600
dpi). The preview, the PDF (one 3 x 1 inch page per label) and the print job all use that
same picture, so what you see is what prints. For printing, the picture is sent as a ZPL
`^GF` graphic, one `^XA...^XZ` per label.

Printing goes either through the Windows print queue as a RAW job (the Zebra
"ZDesigner" driver must be installed, which it is when the printer was set up in Windows),
or straight to a network printer's port 9100 by IP address.

## Light and dark mode

The program follows Windows' "Choose your app mode" setting (Settings > Personalization >
Colors), also when it is changed while the program is open. Windows' own message boxes and
file dialogs stay light. Colors are in `theme.py`.

## Debug

Toggle **Debug** in the bottom-right corner. A debug panel should show up that has various
options to test the GUI, including a fake print that sends nothing.
