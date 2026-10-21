#!/usr/bin/env python3
"""
Invoice & PL Editor - local desktop app

Starts a small web server that listens on 127.0.0.1 only (this computer),
opens the UI in the default browser and processes PDFs locally.
Nothing is sent over the internet.

Run:   python app.py
Build: see build_windows.bat / build_mac_linux.sh
"""
import contextlib
import io
import zipfile
from datetime import datetime
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import inv_editor as core

APP_NAME = "Invoice & PL Editor"
VERSION = "1.0.4"
MAX_UPLOAD = 200 * 1024 * 1024  # 200 MB
HEARTBEAT_TIMEOUT = 180         # seconds without a browser ping -> app exits
CSRF_HEADER = ("X-Requested-With", "InvoiceEditor")

SETTINGS_DIR = Path.home() / ".invoice_pl_editor"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"

DEFAULTS = {
    "manufacturer": "\n".join(core.NEW_MANUFACTURER),
    "company": core.ON_BEHALF_COMPANY,
    "signed_by": core.SIGNED_BY_2,
    "left_align": False,
    "output_dir": str(Path.home() / "Documents" / "Invoice_PL_Edited"),
}

_lock = threading.Lock()
_last_ping = None


def resource(name):
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    return Path(base) / name


# ----------------------------------------------------------------------------
# settings
# ----------------------------------------------------------------------------
def load_settings():
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    return s


def clean_settings(data):
    s = dict(DEFAULTS)
    for k in DEFAULTS:
        if k in data:
            s[k] = data[k]
    s["left_align"] = bool(s["left_align"])
    lines = [x.strip() for x in str(s["manufacturer"]).splitlines() if x.strip()]
    if not 1 <= len(lines) <= 7:
        raise ValueError("Manufacturer address must have 1 to 7 lines")
    s["manufacturer"] = "\n".join(lines)
    for k in ("company", "signed_by", "output_dir"):
        s[k] = str(s[k]).strip()
        if not s[k]:
            raise ValueError(f"'{k}' must not be empty")
    return s


def save_settings(s):
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")


def apply_settings(s):
    core.NEW_MANUFACTURER = s["manufacturer"].splitlines()
    core.ON_BEHALF_COMPANY = s["company"]
    core.SIGNED_BY_2 = s["signed_by"]


# ----------------------------------------------------------------------------
# processing
# ----------------------------------------------------------------------------
def process_pdf(name, data, force=False):
    """Edit one uploaded PDF. Returns dict for the UI."""
    name = Path(name).name
    if not name.lower().endswith(".pdf"):
        return {"ok": False, "log": "Not a PDF file", "name": name}

    with _lock:
        s = load_settings()
        apply_settings(clean_settings(s))
        outdir = Path(s["output_dir"]).expanduser()
        outdir.mkdir(parents=True, exist_ok=True)
        dst = outdir / name   # same file name as the original

        buf = io.StringIO()
        ok = False
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / name
            src.write_bytes(data)
            with contextlib.redirect_stdout(buf):
                try:
                    ok = core.process(src, dst, not s["left_align"], force)
                except Exception as e:  # shown to the user
                    print(f"[ERROR] {e}")
    log = buf.getvalue().strip()
    return {
        "ok": bool(ok),
        "name": name,
        "can_force": (not ok) and "--force" in log,
        "log": log,
        "file": dst.name if ok else None,
        "path": str(dst) if ok else None,
    }


def open_folder(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ----------------------------------------------------------------------------
# http
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "InvoiceEditor/" + VERSION

    def log_message(self, *a):  # quiet
        pass

    # --- helpers
    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            raise ValueError("File too large")
        return self.rfile.read(n)

    # --- GET
    def do_GET(self):
        global _last_ping
        if not self._host_ok():
            return self._json({"error": "forbidden"}, 403)
        u = urlparse(self.path)
        qs = parse_qs(u.query)

        if u.path in ("/", "/index.html"):
            body = resource("ui.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/info":
            _last_ping = time.time()
            self._json({"app": APP_NAME, "version": VERSION, "settings": load_settings()})
        elif u.path == "/api/ping":
            _last_ping = time.time()
            self._json({"ok": True})
        elif u.path == "/api/download":
            fname = Path(unquote(qs.get("file", [""])[0])).name
            f = Path(load_settings()["output_dir"]).expanduser() / fname
            if not fname.lower().endswith(".pdf") or not f.is_file():
                return self._json({"error": "not found"}, 404)
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json({"error": "not found"}, 404)

    # --- POST
    def do_POST(self):
        if not self._host_ok() or self.headers.get(CSRF_HEADER[0]) != CSRF_HEADER[1]:
            return self._json({"error": "forbidden"}, 403)
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        try:
            if u.path == "/api/settings":
                s = clean_settings(json.loads(self._body().decode("utf-8")))
                save_settings(s)
                self._json({"ok": True, "settings": s})
            elif u.path == "/api/process":
                name = unquote(qs.get("name", ["file.pdf"])[0])
                force = qs.get("force", ["0"])[0] == "1"
                self._json(process_pdf(name, self._body(), force))
            elif u.path == "/api/download-all":
                names = json.loads(self._body().decode("utf-8")).get("files", [])
                outdir = Path(load_settings()["output_dir"]).expanduser()
                buf = io.BytesIO()
                added = 0
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for n in dict.fromkeys(Path(str(x)).name for x in names):
                        f = outdir / n
                        if n.lower().endswith(".pdf") and f.is_file():
                            z.write(f, arcname=n)
                            added += 1
                if not added:
                    return self._json({"ok": False, "error": "No processed files found"}, 404)
                body = buf.getvalue()
                zname = datetime.now().strftime("Invoice_PL_%Y%m%d_%H%M%S.zip")
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{zname}"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/api/open-folder":
                open_folder(Path(load_settings()["output_dir"]).expanduser())
                self._json({"ok": True})
            elif u.path == "/api/quit":
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 400)


# ----------------------------------------------------------------------------
# launcher
# ----------------------------------------------------------------------------
def make_server(start=8765, tries=40):
    """Bind the real server to the first free port (no probing race)."""
    last = None
    for p in range(start, start + tries):
        try:
            return ThreadingHTTPServer(("127.0.0.1", p), Handler)
        except OSError as e:
            last = e
    raise last


def watchdog(server):
    while True:
        time.sleep(5)
        if _last_ping and time.time() - _last_ping > HEARTBEAT_TIMEOUT:
            server.shutdown()
            return


def main():
    server = make_server()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"{APP_NAME} {VERSION} running at {url}  (close the browser tab or press Quit to stop)")
    threading.Thread(target=watchdog, args=(server,), daemon=True).start()
    if not os.environ.get("NO_BROWSER"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
