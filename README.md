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
| `image_backend.py` | Tab 1 backend. **Placeholders**, the vision code is not hooked up yet |
| `tab_labels.py` | Tab 2 "Label Printing": bay / variant / lot form, printer choice, label preview, print, save PDF |
| `label_backend.py` | Tab 2 backend, `backend.py` from the Barcode-Generation repo: draws the 3 x 1 inch QR labels, makes the PDF and the Zebra ZPL |
| `zebra_printer.py` | Sends ZPL to the printer (Windows print queue or network IP) |
| `app_settings.py` | Remembers the printer and its resolution in `%APPDATA%\TobaccoVisionGUI` |
| `debug_panel.py` | Debug window with a button for every GUI state |
| `ui_helpers.py` | Small shared widgets |

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

## Debug

Toggle **Debug** in the bottom-right corner. A debug panel should show up that has various
options to test the GUI, including a fake print that sends nothing.
