#!/usr/bin/env bash
# Build the app on macOS (dist/InvoicePLEditor.app) or Linux (dist/InvoicePLEditor/)
set -e
cd "$(dirname "$0")"
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements-build.txt
EXTRA=""
[ "$(uname)" = "Darwin" ] && EXTRA="--windowed"
python3 -m PyInstaller --noconfirm --clean --onedir $EXTRA \
  --name InvoicePLEditor \
  --add-data "ui.html:." \
  --collect-all pdfminer --collect-all pdfplumber --collect-all pypdfium2 \
  app.py
echo "Done: see dist/"
