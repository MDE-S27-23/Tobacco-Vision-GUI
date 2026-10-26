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
| `tab_barcode.py` | Tab 2: notes, lot number/year/month/number form, page preview with ◀ ▶, save |
| `debug_panel.py` | Debug window with a button for every GUI state |
| `ui_helpers.py` | Small shared widgets |
| `backend.py` | **Placeholders** |



## Barcodes: frontend vs backend

`tab_barcode.py` decides **which** barcodes to make and sends the backend a request:

    {"barcodes": [{"text": "L1042-2026-10-0001"}, ...]}

`backend.py` decides **how** they look and where they go on the page:

- `plan_pages(request)` returns `{"page_count": n}` for the summary
- `render_preview(request, page_index)` returns PNG bytes of one page
- `export_barcodes(request, path)` writes the PDF

The preview and the export run in a background thread. The current layout is a
placeholder: US Letter, 0.5 in margin, barcodes in pairs. A pair is two different
barcodes side by side with no gap; it goes in the middle of a tray and each
barcode tracks one side. See the `TODO(backend)` notes in `backend.py`.



## Debug

Toggle **Debug** in the bottom-right corner. A debug panel should show up that has various options to test the GUI
