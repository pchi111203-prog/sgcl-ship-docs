"""Split a combined file (several shipping documents in one PDF / scan / DOCX / XLSX) into separate documents.

A new document starts where a document *title* appears:
  * PDF / images  - title in the top lines of a page (pages without a new title continue the previous document,
                    so a 3-page Crew List stays one document);
  * DOCX          - a short heading paragraph (heading style, bold or upper-case) that is a document title;
  * XLSX          - each sheet is checked like a page.
Consecutive pages titled "BILL OF LADING" are split when the B/L number changes (several B/Ls in one file).
Nothing is split when fewer than two documents are found.
"""
import re

from . import extract
from . import normalize as N

TITLE_MIN_WEIGHT = 8  # only the main-title patterns of the classifier (e.g. "CREW LIST", "BILL OF LADING")


def _title_rules():
    return {t: [re.compile(p) for p, w in rules if w >= TITLE_MIN_WEIGHT] for t, rules in extract.CLASSIFY_RULES.items()}


TITLES = _title_rules()


def title_type(text, top_lines=6):
    """Document type whose main title appears in the first non-empty lines of `text`, else None."""
    lines = [N.strip_accents(l).upper().strip() for l in (text or "").splitlines() if l.strip()][:top_lines]
    head = "\n".join(lines)
    best, best_pos = None, None
    for t, rxs in TITLES.items():
        for rx in rxs:
            m = rx.search(head)
            if m and (best_pos is None or m.start() < best_pos):
                best, best_pos = t, m.start()
    return best


def _heading_type(block):
    """DOCX paragraph that is a document title: short, styled (heading/bold) or upper-case, mostly the title itself."""
    text = (block.get("text") or "").strip()
    if not text or len(text) > 90:
        return None
    up = N.strip_accents(text).upper()
    if not (block.get("styled") or up == N.strip_accents(text)):
        return None
    for t, rxs in TITLES.items():
        for rx in rxs:
            m = rx.search(up)
            if m and (m.end() - m.start()) >= 0.35 * len(up.replace(" ", "")):
                return t
    return None


# list tables that identify a document on their own (column headers), by specificity
SECTION_DOC = [("effects", "CREW_EFFECTS"), ("dg", "DG_MANIFEST"), ("empty_container", "EMPTY_CONTAINER_LIST"),
               ("port_calls", "SHIP_SECURITY"), ("passenger", "PASSENGER_LIST"), ("crew", "CREW_LIST"),
               ("store", "SHIP_STORES"), ("cargo", "CARGO_MANIFEST")]
# a table of this kind inside a document of that type belongs to it (e.g. the goods table of a B/L)
_COMPATIBLE = {("BILL_OF_LADING", "CARGO_MANIFEST"), ("GENERAL_DECLARATION", "CARGO_MANIFEST"), ("NOTICE_OF_ARRIVAL", "CARGO_MANIFEST"),
               ("CREW_EFFECTS", "CREW_LIST"), ("HEALTH_DECLARATION", "CREW_LIST"), ("HEALTH_DECLARATION", "PASSENGER_LIST")}


def table_type(rows):
    """Document type identified by a table's column headers (strong match only), else None."""
    best, best_n = None, 0
    for r in (rows or [])[:3]:
        for section, doc in SECTION_DOC:
            m = extract._match_header(r, section)
            if extract._header_ok(m, section) and len(m) >= 4 and len(m) > best_n:
                best, best_n = doc, len(m)
    return best


def _table_title(rows):
    """Document title written inside the first row of a layout table (common in Word FAL forms)."""
    if not rows or not rows[0]:
        return None
    cells = [c for c in rows[0] if c and c.strip()]
    if not cells:
        return None
    return _heading_type({"text": cells[0], "styled": True}) or (len(cells) == 1 and title_type(cells[0], top_lines=2))


def _starts_new(cur_type, new_type):
    return bool(new_type) and new_type != cur_type and (cur_type, new_type) not in _COMPATIBLE


def _bl_number(page):
    got = extract.extract_header([page], ["bl_no"])
    return N.norm_id(got["bl_no"]["value"]) if "bl_no" in got else None


def split_pages(pages):
    """Return a list of segments [{"type": hint, "pages": [...]}]. One segment means: not a combined file."""
    if len(pages) == 1 and pages[0].get("blocks"):
        return _split_docx(pages[0])
    segs = []
    for p in pages:
        t = title_type(p["text"])
        cur = segs[-1] if segs else None
        if cur is None:
            segs.append({"type": t, "pages": [p]})
        elif t and t != cur["type"]:
            segs.append({"type": t, "pages": [p]})
        elif not t and _starts_new(cur["type"], next((tt for tt in map(table_type, p.get("tables") or []) if tt), None)):
            segs.append({"type": next(tt for tt in map(table_type, p.get("tables") or []) if tt), "pages": [p]})
        elif t == "BILL_OF_LADING" and cur["type"] == "BILL_OF_LADING":
            a, b = _bl_number(cur["pages"][0]), _bl_number(p)
            if a and b and a != b:
                segs.append({"type": t, "pages": [p]})
            else:
                cur["pages"].append(p)
        else:
            cur["pages"].append(p)
    return segs


def _split_docx(page):
    segs = []
    for b in page["blocks"]:
        if b["kind"] == "p":
            t = _heading_type(b)
        else:
            t = _table_title(b["rows"])
            if not t:
                tt = table_type(b["rows"])
                if tt and segs and _starts_new(segs[-1]["type"], tt):
                    # the list table starts a new document; take its caption paragraph(s) along
                    caption = []
                    while segs[-1]["blocks"] and segs[-1]["blocks"][-1]["kind"] == "p" and len(caption) < 3 \
                            and len((segs[-1]["blocks"][-1].get("text") or "").strip()) <= 120:
                        caption.insert(0, segs[-1]["blocks"].pop())
                    segs.append({"type": tt, "blocks": caption + [b]})
                    continue
        new = t and (not segs or t != segs[-1]["type"] or (t == "BILL_OF_LADING" and segs[-1]["blocks"]))
        if new and t == "BILL_OF_LADING" and segs and segs[-1]["type"] == t:
            # same title repeated: new B/L only if the previous one already has a B/L number
            prev_text = "\n".join(x.get("text") or "   ".join("   ".join(r) for r in x.get("rows", [])) for x in segs[-1]["blocks"])
            new = bool(_bl_number({**page, "text": prev_text, "tables": []}))
        if new or not segs:
            segs.append({"type": t, "blocks": [b]})
        else:
            segs[-1]["blocks"].append(b)
    out = []
    for s in segs:
        lines, tables = [], []
        for b in s["blocks"]:
            if b["kind"] == "p":
                lines.append(b["text"])
            else:
                tables.append(b["rows"])
                lines.extend("   ".join(r) for r in b["rows"])
        out.append({"type": s["type"], "pages": [{"page_no": 1, "text": "\n".join(lines), "method": page["method"],
                                                  "confidence": page["confidence"], "tables": tables}]})
    # text before the first title (cover letter, index...) stays with the first document
    if len(out) > 1 and out[0]["type"] is None:
        first = out.pop(0)
        out[0]["pages"][0]["text"] = first["pages"][0]["text"] + "\n" + out[0]["pages"][0]["text"]
    return out


def is_combined(segments):
    return len(segments) >= 2 and sum(1 for s in segments if s["type"]) >= 2
