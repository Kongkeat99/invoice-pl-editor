#!/usr/bin/env python3
"""
Invoice PDF editor (pypdf + pdfplumber only, no network needed)

Process
  1. Check first page is an Invoice (Shipment Invoice header + Actual Manufacturer box)
  2. Remove the word "Shipment" from "Shipment Invoice as of ..."
  3. Replace the Actual Manufacturer address with the new one
  4. Check last page of the Invoice (Invoice Total + "Page N of N")
  5. Add the "For and on behalf of" signature block to the last page

Packing List (PL_*.pdf) - detected automatically from page 1
  1. Check first page is a Packing List (Packing List header + Actual Manufacturer box)
  2. Replace the Actual Manufacturer address with the same new address as the Invoice

Edits are made inside the page content stream, so the old text is really
removed (not just covered by a white box) and cannot be copied/searched.

Usage
  python inv_editor.py INV_SC260372.pdf -o out/   -> out/INV_SC260372.pdf (same name; without -o: *_edited.pdf)
  python inv_editor.py a.pdf b.pdf -o out_dir/          -> batch
  python inv_editor.py a.pdf --left-align              -> header starts at original left x
  python inv_editor.py a.pdf --sign-page 10            -> manual fix: signature block on page 10
  python inv_editor.py a.pdf --strict                  -> no automatic fixes of known cases
"""
import argparse
import re
import sys
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject
from reportlab.pdfbase.pdfmetrics import stringWidth

# ----------------------------------------------------------------------------
# CONFIG - new manufacturer address (from 2nd image)
# first line is bold (font /R2), the rest regular (font /R3)
# ----------------------------------------------------------------------------
NEW_MANUFACTURER = [
    "Trax Apparel (Cambodia) Co., Ltd.",
    "Phum Chong Thnal Khang Kert",
    "Sangkat Teuk Thla Khan Sen Sok",
    "Phnom Penh CAMBODIA",
    "Phone: 023-880442-3",
    "Fax:023-880534",
]
OLD_NAME = "TRAX APPAREL"  # text that must be gone from page 1 after the edit
WORD_TO_REMOVE = "Shipment"
LINE_GAP = 7.05  # same leading as the original block

# "For and on behalf of" block (last page) - layout follows the packing list sample
ON_BEHALF_LINE1 = "For and on behalf of"
ON_BEHALF_COMPANY = "WELLCORP HOLDINGS TRADING HK LTD"
SIGN_LABEL = "Authorized Signature"
SIGNED_BY_1 = "This document has been digitally signed and authorized by"
SIGNED_BY_2 = "Trax Apparel (Cambodia) Co., Ltd(29H001)"
BLOCK_TOP = 262        # minimum pt from top where "For and on behalf of" sits
BLOCK_GAP = 53         # gap between the last content line and the block
BLOCK_HEIGHT = 98      # height of the whole block (first line to last line)
OVERFLOW_TOP = 48      # top of the block when the last page is an empty overflow page
BLOCK_LEFT = 36        # left margin
SIGN_LINE_RIGHT = 247  # right end of the signature line
SIGNED_RIGHT = 690     # right edge of the "digitally signed" text
FONT_SIZE = 7
AUTO_FIX = True        # accept known harmless check deviations (reported as [FIX]); --strict turns it off


def new_address_ok(text):
    """After the edit: old name gone (unless the new address uses it) and new address present."""
    old_gone = OLD_NAME not in text or OLD_NAME in NEW_MANUFACTURER[0]
    return old_gone and NEW_MANUFACTURER[0] in text and NEW_MANUFACTURER[-1] in text


# ----------------------------------------------------------------------------
# Step 1 - check first page
# ----------------------------------------------------------------------------
def check_first_page(path):
    with pdfplumber.open(path) as pdf:
        p = pdf.pages[0]
        text = p.extract_text() or ""
        words = p.extract_words()
    problems = []
    if "Invoice Number" not in text:
        problems.append("'Invoice Number' not found")
    if "Actual Manufacturer" not in text:
        problems.append("'Actual Manufacturer' box not found")
    head = [w for w in words if w["top"] < 50 and w["text"] == WORD_TO_REMOVE]
    if not head:
        problems.append(f"header word '{WORD_TO_REMOVE}' not found (already removed?)")
    return problems


def _footer_top(words, height):
    f = [w["top"] for w in words if w["text"] == "Page" and w["top"] > height * 0.6]
    return min(f) if f else height - 60


# --- tolerant text helpers ---------------------------------------------------
# Some system-generated PDFs use kerning that makes pdfplumber split or merge
# words ("Page 1 1 of 1 1", "Page11 of 11"). These helpers retry with looser
# settings and compare with all whitespace removed.
_FOOT_RE = re.compile(r"Page\s*(\d+)\s*of\s*(\d+)")
_TOLERANCES = ({}, {"x_tolerance": 6}, {"x_tolerance": 1.5})


def _compact(t):
    return re.sub(r"\s+", "", t).lower()


def read_footer(page, text=None):
    """'Page x of y' printed on the page -> (x, y), or None. Uses looser text extraction
    if the normal one does not show it."""
    for i, kw in enumerate(_TOLERANCES):
        t = text if (i == 0 and text is not None) else (page.extract_text(**kw) or "")
        m = _FOOT_RE.findall(t)
        if m:
            return int(m[-1][0]), int(m[-1][1])
        m = re.findall(r"Page(\d+)of(\d+)", re.sub(r"\s+", "", t))   # digits split by spaces
        if m:
            return int(m[-1][0]), int(m[-1][1])
    return None


def has_text(page, needle, text=None):
    """needle present on the page, ignoring spaces/case, retrying with looser extraction."""
    n = _compact(needle)
    for i, kw in enumerate(_TOLERANCES):
        t = text if (i == 0 and text is not None) else (page.extract_text(**kw) or "")
        if n in _compact(t):
            return True
    return False


def analyse_invoice(path):
    """Facts about every page that the last-page check and the diagnosis need."""
    with pdfplumber.open(path) as pdf:
        n = len(pdf.pages)
        footers, total_pages, blanks = [], [], []
        for i, p in enumerate(pdf.pages):
            t = p.extract_text() or ""
            footers.append(read_footer(p, t))
            if has_text(p, "Invoice Total", t):
                total_pages.append(i)
            words = p.extract_words()
            ft = _footer_top(words, float(p.height))
            blanks.append(not [w for w in words if w["top"] < ft - 1])
        last = pdf.pages[-1]
        tail = [ln for ln in (last.extract_text() or "").splitlines() if ln.strip()][-4:]
        behalf = {i: has_text(pdf.pages[i], ON_BEHALF_LINE1) for i in {n - 1, *total_pages[-1:]}}
    return {"n": n, "footers": footers, "total_pages": total_pages, "blanks": blanks,
            "tail": tail, "behalf": behalf}


def diagnose_invoice(a):
    """Human-readable lines that explain what the checker saw (shown when a file fails)."""
    foot = ", ".join(
        f"p{i}: " + (f"'Page {f[0]} of {f[1]}'" if f else "none") for i, f in enumerate(a["footers"], 1)
    )
    tp = ", ".join(str(i + 1) for i in a["total_pages"]) or "none"
    lines = [
        f"[DIAG ] {a['n']} pages; 'Invoice Total' on page(s): {tp}",
        f"[DIAG ] footers read: {foot}",
        "[DIAG ] last page ends with: " + (" | ".join(a["tail"]) or "(no text)"),
    ]
    return lines


def check_last_page(path, sign_page=None, auto_fix=None):
    """Step 4 - find where the signature block belongs and check that page.

    Returns (problems, fixes, target_index, diag_lines)
      problems : reasons the file is NOT safe to edit (file is skipped unless forced)
      fixes    : known harmless deviations that were accepted automatically (AUTO_FIX)
      target   : 0-based index of the page that gets the block
      sign_page: 1-based page chosen by the user (overrides the automatic choice)
    """
    auto = AUTO_FIX if auto_fix is None else auto_fix
    a = analyse_invoice(path)
    n, last = a["n"], a["n"] - 1
    problems, fixes = [], []
    tp = a["total_pages"][-1] if a["total_pages"] else None
    target = last

    if tp is None:
        problems.append("'Invoice Total' not found on any page")
    if sign_page is not None:
        if 1 <= sign_page <= n:
            target = sign_page - 1
            fixes.append(f"signature block goes on page {sign_page} (chosen manually)")
        else:
            problems.append(f"signature page {sign_page} is outside 1..{n}")
    elif tp is not None and tp != last:
        if tp == last - 1 and a["blanks"][last]:
            pass                                   # totals on page N-1, page N is an empty overflow page
        else:
            problems.append(f"'Invoice Total' is on page {tp + 1} but the file has {n} pages "
                            f"(page {last + 1} has other content)")
            target = tp                            # only used when forced

    f = a["footers"][last]
    if f != (n, n):
        msg = f"'Page {n} of {n}' not found on last page" + (f" (page shows 'Page {f[0]} of {f[1]}')" if f else "")
        others = [x for i, x in enumerate(a["footers"]) if i != last and x and x[1] == n]
        # Known harmless case: the last-page footer cannot be read (or has a wrong number) but the
        # Invoice Total is there and the other pages prove the document is complete ("of N").
        if auto and tp is not None and (others or n == 1) and (f is None or f[1] == n):
            fixes.append(f"{msg} -> accepted: Invoice Total found and {len(others)} other page(s) show 'of {n}'")
        else:
            problems.append(msg)

    if a["behalf"].get(target):
        problems.append("'For and on behalf of' already present")
    return problems, fixes, target, diagnose_invoice(a)


def _invoice_number(page):
    """Invoice number printed under the 'Invoice Number' label in the page header."""
    ws = page.extract_words()
    for i, w in enumerate(ws[:-1]):
        if w["text"] == "Invoice" and ws[i + 1]["text"] == "Number" and abs(ws[i + 1]["top"] - w["top"]) < 1:
            for c in ws:
                if abs(c["x0"] - w["x0"]) < 3 and 4 < c["top"] - w["top"] < 20:
                    return c["text"]
    return None


def check_consistency(path):
    """All pages must belong to the same document: same invoice number, 'Page x of N' with N = page count."""
    problems = []
    with pdfplumber.open(path) as pdf:
        n = len(pdf.pages)
        nums = {}
        for i, p in enumerate(pdf.pages, 1):
            v = _invoice_number(p)
            if v:
                nums.setdefault(v, []).append(i)
            f = read_footer(p)
            if f and f[1] != n:
                problems.append(f"page {i} says 'of {f[1]}' but the file has {n} pages")
    if len(nums) > 1:
        detail = ", ".join(f"{k} (page {','.join(map(str, v[:3]))}{'...' if len(v) > 3 else ''})" for k, v in nums.items())
        problems.insert(0, f"pages belong to different documents: {detail}")
    return problems


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def pdf_escape(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def get_stream(page):
    c = page.get_contents()
    return c.get_data().decode("latin1")


def set_stream(writer, page, data):
    obj = DecodedStreamObject()
    obj.set_data(data.encode("latin1"))
    page[NameObject("/Contents")] = writer._add_object(obj)


# ----------------------------------------------------------------------------
# Step 2 - remove word "Shipment" in header
# ----------------------------------------------------------------------------
def remove_header_word(data, keep_position=False):
    # header is a TJ array that starts with "(Shipment In)20(v)25(oice as of ..."
    pat = re.compile(r"(\[\()" + re.escape(WORD_TO_REMOVE) + r" (In\))")
    if not pat.search(data):
        raise ValueError("Header text 'Shipment Invoice' not found in content stream")
    data = pat.sub(r"\1\2", data, count=1)

    if not keep_position:
        return data
    # keep the remaining text where it was: shift start right by width of "Shipment "
    # (Helvetica 9pt: S667 h556 i222 p556 m833 e556 n556 t278 space278 = 4502/1000*9)
    m = re.search(r"(\d+(?:\.\d+)?) (\d+(?:\.\d+)?) Td\n\[\(In\)", data)
    if m:
        shift = 4.502 * 9
        new_x = float(m.group(1)) + shift
        data = data[: m.start()] + f"{new_x:.3f} {m.group(2)} Td\n[(In)" + data[m.end():]
    return data


# ----------------------------------------------------------------------------
# Step 3 - replace manufacturer address
# ----------------------------------------------------------------------------
def replace_manufacturer(data, lines):
    # block: "<x> <y> Td\n[(TRAX APP ...)]TJ ... [(CAMBODIA)]TJ\nET" right after the
    # 'Actual Manufacturer' label
    start_marker = data.find("(Actual Man")
    if start_marker < 0:
        raise ValueError("'Actual Manufacturer' label not found in content stream")
    m = re.compile(
        r"/R2 7 Tf\nBT\n(\S+ \S+) Td\n\[\(TRAX.*?\]TJ\n(?:/R3 7 Tf\n(?:0 -7\.05 Td\n\[.*?\]TJ\n)+)ET",
        re.S,
    ).search(data, start_marker)
    if not m:
        raise ValueError("Manufacturer text block not found in content stream")

    pos = m.group(1)
    out = [f"/R2 7 Tf\nBT\n{pos} Td\n[({pdf_escape(lines[0])})]TJ\n/R3 7 Tf"]
    for ln in lines[1:]:
        out.append(f"0 -{LINE_GAP} Td\n[({pdf_escape(ln)})]TJ")
    out.append("ET")
    return data[: m.start()] + "\n".join(out) + data[m.end():]


# ----------------------------------------------------------------------------
# Step 5 - add "For and on behalf of" block to last page
# ----------------------------------------------------------------------------
def find_font(page, base):
    fonts = page["/Resources"]["/Font"]
    for name in fonts:
        if str(fonts[name].get_object().get("/BaseFont")) == base:
            return str(name)
    raise ValueError(f"font {base} not in page resources")


def find_block_top(path, idx=-1):
    """Top (pt from page top) for the block: below the lowest content on page idx (default:
    the last page), above the footer ('Page N of N'). Returns (top, fits)."""
    with pdfplumber.open(path) as pdf:
        p = pdf.pages[idx]
        words = p.extract_words()
        height = float(p.height)
    footers = [w["top"] for w in words if w["text"] == "Page" and w["top"] > height * 0.6]
    footer_top = min(footers) if footers else height - 60
    body = [w["bottom"] for w in words if w["top"] < footer_top - 1]
    content_bottom = max(body) if body else 0
    if not body:                       # empty overflow page: start at the top of the page
        return OVERFLOW_TOP, True
    top = max(BLOCK_TOP, content_bottom + BLOCK_GAP)
    fits = top + BLOCK_HEIGHT <= footer_top - 4
    return top, fits


def add_on_behalf_block(page, data, block_top=None):
    H = float(page.mediabox.height)
    reg = find_font(page, "/Helvetica")
    y = lambda top: H - top - FONT_SIZE * 0.8  # top of text -> baseline

    def text(font, x, top, s):
        return f"BT\n{font} {FONT_SIZE} Tf\n{x:.2f} {y(top):.2f} Td\n({pdf_escape(s)})Tj\nET"

    def right(font, rx, top, s):
        w = stringWidth(s, "Helvetica", FONT_SIZE)
        return text(font, rx - w, top, s)

    t = BLOCK_TOP if block_top is None else block_top
    parts = [
        "q", "0 0 0 rg", "0 0 0 RG",
        text(reg, BLOCK_LEFT, t, ON_BEHALF_LINE1),
        text(reg, BLOCK_LEFT, t + 11, ON_BEHALF_COMPANY),
        f"0.75 w {BLOCK_LEFT} {H - (t + 56):.2f} m {SIGN_LINE_RIGHT} {H - (t + 56):.2f} l S",
        text(reg, BLOCK_LEFT, t + 62, SIGN_LABEL),
        right(reg, SIGNED_RIGHT, t + 79, SIGNED_BY_1),
        right(reg, SIGNED_RIGHT, t + 90, SIGNED_BY_2),
        "Q",
    ]
    return data + "\n" + "\n".join(parts) + "\n"


# ----------------------------------------------------------------------------
# Packing List (PL) - check first page + replace manufacturer address
# ----------------------------------------------------------------------------
def detect_type(path):
    with pdfplumber.open(path) as pdf:
        t = pdf.pages[0].extract_text() or ""
    if "Packing List as of" in t:
        return "PL"
    if "Shipment Invoice as of" in t or "Invoice as of" in t:
        return "INV"
    return None


def check_pl_first_page(path):
    with pdfplumber.open(path) as pdf:
        t = pdf.pages[0].extract_text() or ""
    problems = []
    if "Packing List as of" not in t:
        problems.append("'Packing List' header not found")
    if "Actual Manufacturer" not in t:
        problems.append("'Actual Manufacturer' box not found")
    if "Invoice Number" not in t:
        problems.append("'Invoice Number' not found")
    if "TRAX" not in t:
        problems.append("old manufacturer text not found (already changed?)")
    return problems


def replace_manufacturer_pl(data, lines):
    """PL page 1: the 'Consignee' label is positioned with a Td relative to the last
    manufacturer line, so when the number of lines changes that Td must be recalculated."""
    m = re.compile(
        r"/R2 7 Tf\nBT\n(\S+) (\S+) Td\n\[\(TRAX[^\n]*\]TJ\n"
        r"/R3 7 Tf\n((?:0 -7\.05 Td\n\[[^\n]*\]TJ\n)+)"
        r"/R3 5 Tf\n(\S+) (\S+) Td\n\[\(Consignee"
    ).search(data)
    if not m:
        raise ValueError("PL manufacturer text block not found in content stream")

    x, y0 = m.group(1), float(m.group(2))
    old_gaps = m.group(3).count("0 -7.05 Td")
    dx, old_dy = m.group(4), float(m.group(5))
    consignee_y = y0 - LINE_GAP * old_gaps + old_dy      # absolute y of 'Consignee' label
    new_last_y = y0 - LINE_GAP * (len(lines) - 1)
    new_dy = consignee_y - new_last_y

    out = [f"/R2 7 Tf\nBT\n{x} {m.group(2)} Td\n[({pdf_escape(lines[0])})]TJ\n/R3 7 Tf"]
    for ln in lines[1:]:
        out.append(f"0 -{LINE_GAP} Td\n[({pdf_escape(ln)})]TJ")
    out.append(f"/R3 5 Tf\n{dx} {new_dy:.4f} Td\n[(Consignee")
    return data[: m.start()] + "\n".join(out) + data[m.end():]


# ----------------------------------------------------------------------------
# main pipeline
# ----------------------------------------------------------------------------
def process_inv(src, dst, keep_position=False, force=False, sign_page=None):
    lp, fixes, target, diag = check_last_page(src, sign_page)
    problems = check_consistency(src) + check_first_page(src) + lp
    for fx in fixes:
        print(f"[FIX  ] {fx}")
    if problems:
        print(f"[CHECK] {src.name}: " + "; ".join(problems))
        for d in diag:
            print(d)
        if not force:
            print("        skipped (use --force to try anyway)")
            return False
    print(f"[CHECK] {src.name}: first page + last page OK" + (" (with fixes above)" if fixes else ""))

    reader = PdfReader(str(src))
    writer = PdfWriter()
    writer.append(reader)  # keep all pages / metadata

    page = writer.pages[0]
    data = get_stream(page)
    data = remove_header_word(data, keep_position)
    print(f"[EDIT ] removed word '{WORD_TO_REMOVE}'")
    data = replace_manufacturer(data, NEW_MANUFACTURER)
    print("[EDIT ] manufacturer address replaced")
    set_stream(writer, page, data)

    sig = writer.pages[target]
    top, fits = find_block_top(src, target)
    set_stream(writer, sig, add_on_behalf_block(sig, get_stream(sig), top))
    print(f"[EDIT ] 'For and on behalf of' block added to page {target + 1} of {len(reader.pages)} (top = {top:.0f}pt)")
    if not fits:
        print("[WARN ] not enough free space on that page - block may touch the footer, please check")

    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as f:
        writer.write(f)

    # verify
    with pdfplumber.open(dst) as pdf:
        t = pdf.pages[0].extract_text()
        tl = pdf.pages[target].extract_text()
    ok = (
        "Shipment Invoice" not in t
        and new_address_ok(t)
        and ON_BEHALF_LINE1 in tl
        and SIGNED_BY_2 in tl
    )
    print(f"[VERIFY] {'OK' if ok else 'FAILED'} -> {dst}")
    return ok


def process_pl(src, dst, force=False):
    problems = check_consistency(src) + check_pl_first_page(src)
    if problems:
        print(f"[CHECK] {src.name}: " + "; ".join(problems))
        if not force:
            print("        skipped (use --force to try anyway)")
            return False
    print(f"[CHECK] {src.name}: Packing List first page OK")

    reader = PdfReader(str(src))
    writer = PdfWriter()
    writer.append(reader)
    page = writer.pages[0]
    data = replace_manufacturer_pl(get_stream(page), NEW_MANUFACTURER)
    print("[EDIT ] manufacturer address replaced")
    set_stream(writer, page, data)

    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "wb") as f:
        writer.write(f)

    with pdfplumber.open(dst) as pdf:
        t = pdf.pages[0].extract_text()
        pages_ok = len(pdf.pages) == len(reader.pages)
    ok = (
        new_address_ok(t) and "85578666971" not in t
        and "Consignee" in t
        and pages_ok
    )
    print(f"[VERIFY] {'OK' if ok else 'FAILED'} -> {dst}")
    return ok


def process(src, dst, keep_position=False, force=False, sign_page=None):
    kind = detect_type(src)
    if kind == "PL":
        return process_pl(src, dst, force)
    if kind == "INV":
        return process_inv(src, dst, keep_position, force, sign_page)
    print(f"[CHECK] {src.name}: not recognised as Invoice or Packing List - skipped")
    return False


def main():
    ap = argparse.ArgumentParser(description="Invoice / Packing List PDF editor")
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="output dir (default: next to input)")
    ap.add_argument("--left-align", action="store_true",
                    help="start 'Invoice as of ...' at the original left x instead of keeping "
                         "the original right edge (default: right edge kept)")
    ap.add_argument("--force", action="store_true", help="edit even if the check fails")
    ap.add_argument("--strict", action="store_true",
                    help="no automatic fixes: skip every file whose check does not pass exactly")
    ap.add_argument("--sign-page", type=int, metavar="N",
                    help="invoice only: put the 'For and on behalf of' block on page N "
                         "(manual fix when the last page is not where it belongs)")
    a = ap.parse_args()
    global AUTO_FIX
    AUTO_FIX = not a.strict

    ok_all = True
    for f in a.files:
        dst = (a.out or f.parent) / f.name          # same file name as the original
        if dst.resolve() == f.resolve():             # never overwrite the original
            dst = f.with_name(f"{f.stem}_edited.pdf")
            print(f"[NOTE ] output folder = input folder, saving as {dst.name}")
        try:
            ok_all &= process(f, dst, not a.left_align, a.force, a.sign_page)
        except Exception as e:
            print(f"[ERROR] {f.name}: {e}")
            ok_all = False
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
