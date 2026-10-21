@echo off
REM Build a single-file Windows app: dist\InvoicePLEditor.exe
REM Needs Python 3.10+ from python.org (tick "Add Python to PATH")
py -m pip install --upgrade pip
py -m pip install -r requirements-build.txt || goto :err
py -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name InvoicePLEditor ^
  --add-data "ui.html;." ^
  --collect-all pdfminer --collect-all pdfplumber --collect-all pypdfium2 ^
  app.py || goto :err
echo.
echo Done: dist\InvoicePLEditor.exe
pause
exit /b 0
:err
echo Build failed.
pause
exit /b 1
