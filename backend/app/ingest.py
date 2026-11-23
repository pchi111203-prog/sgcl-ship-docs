"""Read the content of uploaded documents.

Returns a list of pages: {page_no, text, method, confidence, tables}
  * method: text (PDF text layer) | ocr | docx | xlsx | csv
  * confidence: 0..1 (1.0 for digital text; tesseract mean word confidence for OCR)
  * tables: list of tables, each a list of rows (list of cell strings)
"""
import io
import re
import os
import shutil
import threading

MIN_TEXT_CHARS = 40  # below this a PDF page is considered scanned and is OCR'd

try:
    import pymupdf as fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

try:
    import pytesseract
    from PIL import Image, ImageOps
    # Windows: the UB Mannheim installer does not add Tesseract to PATH
    for _p in (os.environ.get("TESSERACT_CMD"), r"C:\Program Files\Tesseract-OCR\tesseract.exe",
               r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if _p and os.path.isfile(_p) and not shutil.which("tesseract"):
            pytesseract.pytesseract.tesseract_cmd = _p
            break
    HAS_TESSERACT = shutil.which("tesseract") is not None or os.path.isfile(pytesseract.pytesseract.tesseract_cmd)
except Exception:  # pragma: no cover
    HAS_TESSERACT = False

SUPPORTED = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".docx", ".xlsx", ".xlsm", ".xls", ".csv", ".txt"}


class IngestError(Exception):
    pass


def ocr_status():
    langs = []
    if HAS_TESSERACT:
        try:
            langs = pytesseract.get_languages(config="")
        except Exception:
            pass
    return {"available": HAS_TESSERACT, "engine": "Tesseract OCR" if HAS_TESSERACT else None,
            "languages": langs, "pdf_engine": "PyMuPDF" if fitz else None}


MAX_OCR_SIDE = 5300  # enough for small print in scanner-app pages, bounded memory
OCR_LOCK = threading.Lock()
OCR_LANG = os.environ.get("SGCL_OCR_LANG")  # e.g. "eng" for speed, default eng+vie when available
os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # tesseract multi-threading is slower with parallel workers


def _ocr_image(img):
    """One tesseract pass (image_to_data); text lines are rebuilt from word boxes and wide gaps
    become 3 spaces so table columns can be split later. Returns (text, mean_conf, word_conf)."""
    if not HAS_TESSERACT:
        raise IngestError("Chưa cài đặt OCR (Tesseract) - không thể đọc chứng từ scan/ảnh.")
    img = ImageOps.exif_transpose(img).convert("L")
    if max(img.size) > MAX_OCR_SIDE * 1.2:
        f = MAX_OCR_SIDE / max(img.size)
        img = img.resize((int(img.width * f), int(img.height * f)))
    if img.width < 1600:
        f = 1600 / img.width
        img = img.resize((int(img.width * f), int(img.height * f)))
    lang = OCR_LANG or ("eng+vie" if "vie" in (pytesseract.get_languages(config="") or []) else "eng")
    res = _ocr_best(img, lang)
    if res[1] < 0.72:
        # Poor reading: the scan may be sideways/upside down (e.g. a landscape crew list scanned
        # in portrait). Ask tesseract for the page orientation and read again if it is rotated.
        try:
            osd = pytesseract.image_to_osd(img, config="--psm 0 -c min_characters_to_try=10")
            angle = int(re.search(r"Rotate:\s*(\d+)", osd).group(1))
        except Exception:
            angle = 0
        if angle:
            rot = _ocr_best(img.rotate(-angle, expand=True), lang)
            if rot[1] > res[1]:
                res = rot
    return res  # (text, conf, words, alternative texts)


def _otsu(img):
    """Black/white version of a grey scan (Otsu threshold): phone scans with grey background read better."""
    hist = img.histogram()[:256]
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    w_b = sum_b = 0
    best_t, best_v = 128, -1
    for t in range(256):
        w_b += hist[t]
        if not w_b or w_b == total:
            continue
        sum_b += t * hist[t]
        m_b, m_f = sum_b / w_b, (sum_all - sum_b) / (total - w_b)
        v = w_b * (total - w_b) * (m_b - m_f) ** 2
        if v > best_v:
            best_t, best_v = t, v
    return img.point(lambda x: 255 if x > best_t else 0)


def _line_runs(mask, L, axis):
    import numpy as np
    a = mask if axis == 1 else mask.T
    h, w = a.shape
    if w <= L:
        return np.zeros(mask.shape, bool)
    cs = np.zeros((h, w + 1), np.int32)
    np.cumsum(a, axis=1, out=cs[:, 1:])
    full = (cs[:, L:] - cs[:, :-L]) == L  # window [i, i+L) entirely dark
    st = np.zeros((h, w + 1), np.int32)
    st[:, :w - L + 1] += full
    st[:, L:w + 1] -= full
    cov = np.cumsum(st, axis=1)[:, :w] > 0
    return cov if axis == 1 else cov.T


def _remove_table_lines(bw):
    """White out the ruling of a scanned table (short words next to cell borders - CAPT, C/O, 2/E ... - are
    otherwise dropped by the OCR). Returns the cleaned image and the y of the horizontal rules (row borders).
    Worked in stripes to keep memory low."""
    import numpy as np
    a = np.array(bw)
    dark = a < 128
    h, w = dark.shape
    hm = np.zeros((h, w), bool)
    vm = np.zeros((h, w), bool)
    for y0 in range(0, h, 256):
        hm[y0:y0 + 256] = _line_runs(dark[y0:y0 + 256], max(40, w // 30), 1)
    for x0 in range(0, w, 256):
        vm[:, x0:x0 + 256] = _line_runs(dark[:, x0:x0 + 256], max(40, h // 30), 0)
    rows = np.nonzero(hm.sum(axis=1) > w * 0.25)[0]
    rules = []
    for y in rows:
        if rules and y - rules[-1][1] <= 3:
            rules[-1][1] = y
        else:
            rules.append([y, y])
    m = hm | vm
    del hm, vm, dark
    m2 = m.copy()
    m2[1:] |= m[:-1]; m2[:-1] |= m[1:]; m2[:, 1:] |= m[:, :-1]; m2[:, :-1] |= m[:, 1:]
    a[m2] = 255
    return Image.fromarray(a), [(r0 + r1) / 2 for r0, r1 in rules]


def _sparse_text(img, lang, rules=()):
    """Every word found anywhere (psm 11) on the page without table lines, rebuilt into lines: words between
    the same two row borders of a table are one line (cells of a row are often not on the same height)."""
    data = pytesseract.image_to_data(img, lang=lang, config="--psm 11", output_type=pytesseract.Output.DICT)
    ws = [(data["top"][i] + data["height"][i] / 2, data["left"][i], data["width"][i], data["height"][i], (data["text"][i] or "").strip())
          for i in range(len(data["text"])) if (data["text"][i] or "").strip() and float(data["conf"][i]) >= 0]
    if not ws:
        return ""
    hs = sorted(w[3] for w in ws)
    med = hs[len(hs) // 2]
    tol = max(6, med * 0.6)
    rules = sorted(rules)

    def band(y):
        for i in range(len(rules) - 1):
            if rules[i] < y < rules[i + 1] and rules[i + 1] - rules[i] < med * 4:
                return i  # inside one table row
        return None
    lines = []
    for w in sorted(ws):
        b = band(w[0])
        if lines and ((b is not None and b == lines[-1][2]) or (b is None and lines[-1][2] is None and abs(w[0] - lines[-1][0]) <= tol)):
            lines[-1][1].append(w)
        else:
            lines.append([w[0], [w], b])
    out = []
    for _, line, _b in lines:
        s, prev = "", None
        for _, left, width, height, t in sorted(line, key=lambda x: x[1]):
            s = t if prev is None else s + ("   " if left - prev > max(height, 12) * 1.2 else " ") + t
            prev = left + width
        out.append(s)
    return "\n".join(out)


def _ocr_best(img, lang):
    """Best reading + the texts of the other readings (alternatives): a table row missed in one reading of a
    weak scan is often present in another, extraction can pick the reading that yields the most rows."""
    res = _ocr_pass(img, lang)
    alts = []
    if res[1] < 0.85:  # weak reading: try the black/white version and keep the better one
        bw = _ocr_pass(_otsu(img), lang)
        if bw[1] > res[1]:
            res, bw = bw, res
        alts.append(bw[0])
        w, h = img.size  # a slightly different scale gives tesseract another chance on small print
        sc = _ocr_pass(_otsu(img.resize((int(w * 0.8), int(h * 0.8)))), lang)
        alts.append(sc[0])
    if True:  # every scan: one more reading without the ruling lines (tables, boxed forms)
        try:
            clean, rules = _remove_table_lines(_otsu(img))
            alts.append(_sparse_text(clean, lang, rules))
        except Exception:
            pass
    return (*res, alts)


def _ocr_pass(img, lang):
    data = pytesseract.image_to_data(img, lang=lang, config="--psm 6", output_type=pytesseract.Output.DICT)
    lines, confs, words = {}, [], {}
    for i, w in enumerate(data["text"]):
        w = (w or "").strip()
        c = float(data["conf"][i])
        if not w or c < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append((data["left"][i], data["width"][i], data["height"][i], w))
        confs.append(c)
        words.setdefault(w, []).append(c / 100)
    out = []
    for key in sorted(lines):
        ws = sorted(lines[key])
        s, prev_end = "", None
        for left, width, height, w in ws:
            if prev_end is None:
                s = w
            else:
                gap = left - prev_end
                s += ("   " if gap > max(height, 12) * 1.2 else " ") + w
            prev_end = left + width
        out.append(s)
    conf = (sum(confs) / len(confs) / 100) if confs else 0.0
    return "\n".join(out), conf, {k: min(v) for k, v in words.items()}


def _pdf_pages(path):
    if not fitz:
        raise IngestError("Thiếu thư viện đọc PDF (PyMuPDF).")
    doc = fitz.open(path)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text") or ""
        if len(text.strip()) >= MIN_TEXT_CHARS:
            tables = _plumber_tables(path, i)
            # Keep visual line layout so label/value pairs on one line stay together
            layout = _layout_text(page) or text
            pages.append({"page_no": i + 1, "text": layout, "method": "text", "confidence": 1.0, "tables": tables})
        else:
            # 300 dpi for normal pages, but never more than ~3500 px on the long side: scanner apps (CamScanner...)
            # make pages 3x A4 size, which at 300 dpi gives 8000x11000 px images and exhausts the server memory.
            zoom = min(300 / 72, MAX_OCR_SIDE / max(page.rect.width, page.rect.height))
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY)
            img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
            del pix
            with OCR_LOCK:  # one OCR at a time: bounded memory on small servers
                t, conf, words, alts = _ocr_image(img)
            del img
            pages.append({"page_no": i + 1, "text": t, "method": "ocr", "confidence": conf, "tables": [], "words": words, "alt_texts": alts})
    return pages


def _plumber_tables(path, index):
    """Ruled tables via pdfplumber (keeps spaces/punctuation reliably)."""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            out = []
            for t in pdf.pages[index].extract_tables():
                out.append([[(c or "").replace("\n", " ").strip() for c in r] for r in t])
            return out
    except Exception:
        return []


def _layout_text(page):
    """Rebuild lines from words, joining words on the same visual line and
    marking large horizontal gaps with 3 spaces (column separators)."""
    try:
        words = page.get_text("words")
    except Exception:
        return None
    if not words:
        return None
    words.sort(key=lambda w: (round((w[1] + w[3]) / 2 / 3), w[0]))
    lines, cur, cur_y = [], [], None
    for w in words:
        y = (w[1] + w[3]) / 2
        if cur_y is None or abs(y - cur_y) <= 3:
            cur.append(w)
            cur_y = y if cur_y is None else cur_y
        else:
            lines.append(cur)
            cur, cur_y = [w], y
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        ln.sort(key=lambda w: w[0])
        s, last_x1 = "", None
        for w in ln:
            if last_x1 is None:
                s = w[4]
            else:
                gap = w[0] - last_x1
                s += ("   " if gap > 12 else " ") + w[4]
            last_x1 = w[2]
        out.append(s)
    return "\n".join(out)


def _image_pages(path):
    img = Image.open(path)
    pages = []
    n = getattr(img, "n_frames", 1)
    for i in range(n):  # multi-page TIFF
        img.seek(i)
        with OCR_LOCK:
            t, conf, words, alts = _ocr_image(img.copy())
        pages.append({"page_no": i + 1, "text": t, "method": "ocr", "confidence": conf, "tables": [], "words": words, "alt_texts": alts})
    return pages


def _docx_pages(path):
    """Read paragraphs and tables in document order. 'blocks' keeps that order (used to split combined files)."""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    d = docx.Document(path)
    lines, tables, blocks = [], [], []
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(el, d)
            text = p.text
            styled = (p.style is not None and (p.style.name or "").lower().startswith(("heading", "title"))) or \
                     (any(r.bold for r in p.runs if r.text.strip()) and all(r.bold for r in p.runs if r.text.strip()))
            lines.append(text)
            blocks.append({"kind": "p", "text": text, "styled": bool(styled)})
            W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            if el.findall(f".//{W}br[@{W}type='page']") or el.findall(f".//{W}sectPr"):
                blocks.append({"kind": "break"})  # explicit page / section break: documents usually start on a new page
            elif el.findall(f".//{W}pageBreakBefore") and len(blocks) > 1:
                blocks.insert(len(blocks) - 1, {"kind": "break"})
        elif tag == "tbl":
            t = Table(el, d)
            rws = []
            for r in t.rows:
                cells, prev = [], None
                for c in r.cells:  # merged cells repeat the same object
                    if c._tc is prev:
                        continue
                    prev = c._tc
                    cells.append(c.text.replace("\n", " ").strip())
                rws.append(cells)
            tables.append(rws)
            lines.extend("   ".join(r) for r in rws)
            blocks.append({"kind": "t", "rows": rws})
    # DOCX has no fixed pagination; everything is reported as page 1
    return [{"page_no": 1, "text": "\n".join(lines), "method": "docx", "confidence": 1.0, "tables": tables, "blocks": blocks}]


def _xlsx_pages(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    pages = []
    for i, ws in enumerate(wb.worksheets):
        rws = []
        for r in ws.iter_rows(values_only=True):
            cells = ["" if v is None else _cell_str(v) for v in r]
            while cells and cells[-1] == "":
                cells.pop()
            rws.append(cells)
        text = "\n".join("   ".join(c for c in r if c) for r in rws)
        pages.append({"page_no": i + 1, "text": f"[Sheet: {ws.title}]\n" + text, "method": "xlsx",
                      "confidence": 1.0, "tables": [rws]})
    return pages


def _xls_pages(path):
    try:
        import xlrd  # optional
    except ImportError:
        raise IngestError("File .xls (Excel 97-2003) cần thư viện xlrd. Vui lòng lưu lại dưới dạng .xlsx.")
    wb = xlrd.open_workbook(path)
    pages = []
    for i, sh in enumerate(wb.sheets()):
        rws = [[_cell_str(sh.cell_value(r, c)) for c in range(sh.ncols)] for r in range(sh.nrows)]
        pages.append({"page_no": i + 1, "text": "\n".join("   ".join(c for c in r if c) for r in rws),
                      "method": "xlsx", "confidence": 1.0, "tables": [rws]})
    return pages


def _cell_str(v):
    from datetime import date, datetime
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y %H:%M") if (v.hour or v.minute) else v.strftime("%d/%m/%Y")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _csv_pages(path):
    import csv
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        rws = list(csv.reader(f))
    return [{"page_no": 1, "text": "\n".join("   ".join(r) for r in rws), "method": "csv", "confidence": 1.0, "tables": [rws]}]


def read_document(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED:
        raise IngestError(f"Định dạng {ext} chưa được hỗ trợ.")
    if ext == ".pdf":
        return _pdf_pages(path)
    if ext in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"):
        return _image_pages(path)
    if ext == ".docx":
        return _docx_pages(path)
    if ext in (".xlsx", ".xlsm"):
        return _xlsx_pages(path)
    if ext == ".xls":
        return _xls_pages(path)
    if ext == ".csv":
        return _csv_pages(path)
    with open(path, encoding="utf-8", errors="replace") as f:
        return [{"page_no": 1, "text": f.read(), "method": "text", "confidence": 1.0, "tables": []}]
