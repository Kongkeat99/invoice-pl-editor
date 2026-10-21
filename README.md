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

**Invoice with number starting with "C" (e.g. C262093, not SC...)** - already signed, header already has no "Shipment":
only the Actual Manufacturer address is replaced (no header edit, no signature block).

**Packing List**
1. Checks page 1 is a packing list
2. Replaces the Actual Manufacturer address

Edits are made inside the PDF content, so the old text is really removed (not just covered).
Originals are never changed; results are saved in the output folder with the **same file name** (set the output folder to a different folder than the originals).

## For users (no Python)
Download the zip for your system from the Releases page, unzip, double-click.
- **Windows:** `InvoicePLEditor.exe`. If SmartScreen warns: *More info -> Run anyway* (the app is not code-signed).
- **macOS:** `InvoicePLEditor.app`. First time: right-click -> *Open* -> *Open*.

The browser opens automatically. Drop PDFs, click **Process files**, then download each file, use **Download all (zip)** for everything at once, or **Open output folder**.
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

## Safety checks
Before editing, the tool checks that all pages belong to the same document (same invoice number, `Page x of N` matches the page count) and that the expected pages/fields exist. A file that fails is skipped with the reason; in the app a **Process anyway** button lets the user override after confirming.
If the invoice totals end on the second-to-last page and the last page is an empty overflow page, the signature block is placed at the top of that last page.

## Failed checks and how to fix them (v1.1.0)
- **Auto-fix (default):** known harmless deviations are accepted and listed as `[FIX]` in the file's log, e.g. the last-page footer `Page N of N` cannot be read (or shows the wrong number) but `Invoice Total` is present and the other pages say `of N`. Untick *Auto-fix* in Settings, or use `--strict`, to skip these files instead.
- **Diagnosis:** a file that still fails shows `[DIAG]` lines: footer read on every page, page(s) with `Invoice Total`, last lines of the last page.
- **Manual fix:** on a failed invoice, type the page number and click *Fix: put signature on this page* (CLI: `--sign-page N`). *Process anyway* still ignores the checks (CLI: `--force`).

## Limits
- Made for this specific system-generated layout. A file that fails the page checks is skipped with a reason, never edited blindly.
- The "digitally signed and authorized by" line is plain text, not a cryptographic signature. Use it only where authorized.
