# Invoice & PL Editor

Local app that edits adidas-style **Invoice (INV_*.pdf)** and **Packing List (PL_*.pdf)** PDFs.
Runs 100% on your computer (small local server on 127.0.0.1 + your browser as the window). No internet needed.

## What it does
**Invoice**
1. Checks page 1 is an invoice
2. Removes the word "Shipment" from "Shipment Invoice as of ..."
3. Replaces the Actual Manufacturer address
4. Checks the last page (Invoice Total, Page N of N)
5. Adds the "For and on behalf of" signature block to the last page

**Packing List**
1. Checks page 1 is a packing list
2. Replaces the Actual Manufacturer address

Edits are made inside the PDF content, so the old text is really removed (not just covered).
Originals are never changed; results are saved as `<name>_edited.pdf`.

## For users (no Python)
Download the zip for your system from the Releases page, unzip, double-click.
- **Windows:** `InvoicePLEditor.exe`. If SmartScreen warns: *More info -> Run anyway* (the app is not code-signed).
- **macOS:** `InvoicePLEditor.app`. First time: right-click -> *Open* -> *Open*.

The browser opens automatically. Drop PDFs, click **Process files**, download or **Open output folder**.
Close the tab or press **Quit app** to stop.

Default output folder: `Documents/Invoice_PL_Edited` (changeable in Settings).
Settings are stored in `~/.invoice_pl_editor/settings.json`.

## Run from source
Python 3.10+:
```
pip install -r requirements.txt
python app.py
```
(or `run_from_source.bat` / `run_from_source.sh`)

Command line (no UI): `python inv_editor.py INV_x.pdf PL_x.pdf -o out/`

## Build the app yourself
- Windows: double-click `build_windows.bat` -> `dist\InvoicePLEditor.exe`
- macOS/Linux: `./build_mac_linux.sh` -> `dist/`
(PyInstaller builds only for the OS it runs on.)

## Release to users with GitHub (builds Windows + macOS automatically)
1. Push this folder to a GitHub repo
2. `git tag v1.0.0 && git push origin v1.0.0`
3. GitHub Actions builds both apps and attaches `InvoicePLEditor-windows.zip` and
   `InvoicePLEditor-macos.zip` to the release. Share that link.

## Limits
- Made for this specific system-generated layout. A file that fails the page checks is skipped with a reason, never edited blindly.
- The "digitally signed and authorized by" line is plain text, not a cryptographic signature. Use it only where authorized.
