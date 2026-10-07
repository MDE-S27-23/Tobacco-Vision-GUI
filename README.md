# tobacco vision GUI test

Tkinter front end for the seedling-tray project. Currently GUI only

## Run

    pip install -r requirements.txt
    python main.py

## Build the .exe

Run `build_exe.bat`. The output should be in
`dist\TobaccoVisionGUI.exe`.

## Files

| File | What it is |
|---|---|
| `main.py` | Entry point |
| `gui_app.py` | Main window, the two tabs, the Debug checkbox |
| `tab_process.py` | Tab 1: photo list (drag and drop), progress bar, save Excel |
| `tab_barcode.py` | Tab 2: notes, plant/year/month/number form, page preview, save |
| `debug_panel.py` | Debug window with a button for every GUI state |
| `ui_helpers.py` | Small shared widgets |
| `backend.py` | **Placeholders** |



## Barcode print layout

The layout numbers are at the top of `backend.py`: US Letter, 0.5 in margin,
barcodes in pairs. A pair is two different barcodes side by side with no gap;
it goes in the middle of a tray and each barcode tracks one side. 



## Debug

Toggle **Debug** in the bottom-right corner. A debug panel should show up that has various options to test the GUI
