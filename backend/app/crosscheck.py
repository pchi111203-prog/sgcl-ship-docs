"""Cross-check engine.

Statuses:
  PASSED            compared in >=2 sources and consistent
  MISMATCH          values differ between documents              (blocking)
  MISSING_INFO      required information missing                 (blocking only where noted)
  NEEDS_REVIEW      something staff must look at (format, check digit, wording differs)
  DUPLICATE         duplicated record                            (blocking)
  LOW_CONFIDENCE    extraction confidence below threshold
  WRONG_VOYAGE      document seems to belong to another vessel/voyage (blocking)
  NOT_AVAILABLE     "Not Available in Source" - no document contains the field
  SINGLE_SOURCE     the value exists in ONE document only: it is taken (and exported) but could not be cross-checked
  NOT_ENOUGH_DATA   "Not Enough Data" - a whole document type needed for the comparison is missing
The engine never decides which value is right; it reports both values with their sources.
"""
import re
from datetime import datetime
from collections import defaultdict

from . import db
from . import normalize as N
from .extract import DOC_TYPES, FIELD_LABELS, LOW_CONF

GROUP_VESSEL = "1. Thông tin tàu & chuyến"
GROUP_CARGO = "2. Hàng hóa (Manifest ↔ B/L)"
GROUP_CREW = "3. Thuyền viên"
GROUP_DG = "4. Hàng nguy hiểm"
GROUP_DOC = "0. Chứng từ / chuyến tàu"
GROUP_QUALITY = "7. Chất lượng trích xuất"
GROUP_CONT = "5. Container"

BLOCKING = {"MISMATCH", "DUPLICATE", "WRONG_VOYAGE"}


def _cmp_text(a, b):
    return N.norm_text(a) == N.norm_text(b)


def _company_key(s):
    k = N.norm_text(s)
    k = re.sub(r"\b(CO|COMPANY|LTD|LIMITED|CORP|CORPORATION|INC|JSC|PTE|LLC)\b", "", k)
    return re.sub(r"\s+", " ", k).strip()


_ADDRESS_START = re.compile(r",|\b(JL|JLN|JALAN|NO|LOT|STREET|ST|ROAD|RD|AVENUE|AVE|BUILDING|BLDG|FLOOR|DIA CHI|ADDRESS|ADD|TEL|FAX|MST|"
                            r"SO|DUONG|PHUONG|QUAN|HUYEN|KCN|TOA NHA)\b")


def _company_name(s):
    """Company name without its address: 'PT. NUSANTARA AGRO GRAINS Jl. Perak Timur No. 112' -> 'PT NUSANTARA AGRO GRAINS'."""
    t = N.strip_accents(str(s or "")).upper()
    t = re.sub(r"\.", " ", t)
    return re.sub(r"\s+", " ", _ADDRESS_START.split(t, maxsplit=1)[0]).strip()


def _is_vietnamese(s):
    return bool(re.search(r"[ăâđêôơưĂÂĐÊÔƠƯàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ]", s or ""))


def _locode(s):
    m = re.search(r"\b([A-Z]{2}[A-Z2-9]{3})\b(?=\)|$)", (s or "").upper())
    return m.group(1) if m else None


_PORT_GENERIC = {"PORT", "CANG", "INTERNATIONAL", "QUOC", "TE", "TERMINAL", "BEN", "CAU", "OF", "THE", "AND", "CITY", "THANH", "PHO", "TP",
                 "PROVINCE", "TINH", "HARBOUR", "HARBOR", "WHARF", "VIETNAM", "VIET", "NAM", "VN", "INTL", "LAIP"}


def _port_words(s):
    return {w for w in N.norm_text(re.sub(r"\(.*?\)", " ", s or "")).split() if w not in _PORT_GENERIC and not w.isdigit()}


def _cmp_port(a, b):
    la, lb = _locode(a), _locode(b)
    if la and lb:
        return la == lb
    ka, kb = N.norm_text(a), N.norm_text(b)
    if ka == kb or (len(min(ka, kb, key=len)) >= 4 and (ka in kb or kb in ka)):
        return True
    # 'Cảng Quốc tế Long An' = 'LONG AN INTERNATIONAL PORT, VIETNAM': compare the proper-name words only
    wa, wb = _port_words(a), _port_words(b)
    return bool(wa and wb) and (wa <= wb or wb <= wa)


def _cmp_number(a, b):
    ka, kb = N.number_key(a), N.number_key(b)
    if ka is None or kb is None:
        return N.norm_text(a) == N.norm_text(b)
    if ka[1] and kb[1] and ka[1] != kb[1]:
        return False
    return abs(ka[0] - kb[0]) < 0.0005 * max(1, abs(ka[0]))


def _cmp_vessel(a, b):
    return N.vessel_key(a) == N.vessel_key(b)


def _cmp_flag(a, b):
    sa, sb = N.suggest_state(a), N.suggest_state(b)
    if sa and sb:
        return sa == sb
    return _cmp_text(a, b)


def _cmp_date(a, b):
    da, oka = N.parse_date(a)
    dbb, okb = N.parse_date(b)
    if oka and okb:
        if len(da) != len(dbb):  # one has a time, the other only a date: compare the date part
            return da[:10] == dbb[:10]
        return da == dbb
    return _cmp_text(a, b)


def _cmp_id(a, b):
    return N.norm_id(a) == N.norm_id(b)


def _cmp_set(a, b):
    sa = {N.norm_id(x) for x in re.split(r"[,;/\s]+", a or "") if x.strip()}
    sb = {N.norm_id(x) for x in re.split(r"[,;/\s]+", b or "") if x.strip()}
    return sa == sb


VESSEL_CHECKS = [
    # field, comparator, document types compared
    ("vessel_name", _cmp_vessel, ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "TONNAGE_CERTIFICATE"]),
    ("imo", _cmp_id, ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "TONNAGE_CERTIFICATE"]),
    ("call_sign", _cmp_id, ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "TONNAGE_CERTIFICATE"]),
    ("flag", _cmp_flag, ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "TONNAGE_CERTIFICATE"]),
    ("voyage_no", _cmp_id, ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "CARGO_MANIFEST", "BILL_OF_LADING", "CREW_LIST", "DG_MANIFEST",
                            "CREW_EFFECTS", "SHIP_STORES", "PASSENGER_LIST", "HEALTH_DECLARATION", "SHIP_SECURITY"]),
    ("gross_tonnage", _cmp_number, ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "TONNAGE_CERTIFICATE"]),
    ("net_tonnage", _cmp_number, ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "TONNAGE_CERTIFICATE"]),
    ("eta", _cmp_date, ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL"]),
    ("port_of_arrival", _cmp_port, ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL"]),
    ("last_port", _cmp_port, ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL"]),
    ("next_port", _cmp_port, ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL"]),
]

COMPARATORS = {k: cmp for k, cmp, _ in VESSEL_CHECKS}
COMPARATORS.update({"master_name": lambda a, b: N.norm_text(re.sub(r"^(CAPT\.?|CAPTAIN)\s+", "", a or "", flags=re.I)) ==
                    N.norm_text(re.sub(r"^(CAPT\.?|CAPTAIN)\s+", "", b or "", flags=re.I)),
                    "crew_count": _cmp_number, "etd": _cmp_date})

CARGO_CHECKS = [
    ("shipper", "company"), ("consignee", "company"), ("notify", "company"), ("description", "text"),
    ("packages", "number"), ("gross_weight", "weight"), ("measurement", "number"),
    ("container_no", "set"), ("container_type", "set"), ("seal_no", "set"), ("pol", "port"), ("pod", "port"),
]


_DATE_LABEL = re.compile(r"(date|ng[aà]y|th[oờ]i\s+gian)", re.I)


def _doc_date(text):
    """Latest date written next to a date label (not dates of birth / passport expiry in table rows)."""
    best = None
    for line in (text or "").splitlines():
        if not _DATE_LABEL.search(N.strip_accents(line)) or re.search(r"[A-Z]\d{7}", line):
            continue
        for m in re.finditer(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4}|\d{1,2}\s+th[aá]ng\s+\d{1,2}\s+n[aă]m\s+\d{4}", line):
            s = re.sub(r"\s+th[aá]ng\s+", "/", re.sub(r"\s+n[aă]m\s+", "/", m.group(0)))
            d, ok = N.parse_date(s)
            if ok:
                try:
                    dd = datetime.strptime(d[:10], "%d/%m/%Y")
                except ValueError:
                    continue
                if 2000 <= dd.year <= datetime.now().year + 1 and (best is None or dd > best):
                    best = dd
    return best


def superseded_crew_lists(conn, docs, fields, voyage):
    """{doc_id: (kept_doc_id, reason)} for crew lists repeating the crew of another crew list (>= half the passports).
    The list kept is the one naming the port of arrival of this voyage, else the most recent one. Documents the staff
    confirmed for this voyage are never set aside."""
    crew_docs = [d for d in docs.values() if d["doc_type"] == "CREW_LIST" and d["status"] == "EXTRACTED"]
    if len(crew_docs) < 2:
        return {}
    pp = defaultdict(set)
    for f in fields:
        if f["section"] == "crew" and f["field_key"] == "passport_no" and f["document_id"] in {d["id"] for d in crew_docs}:
            v = N.norm_id(f["value"])
            if v:
                pp[f["document_id"]].add(v)
    arrival = [voyage.get("port_of_arrival") or ""] + [f["value"] for f in fields if f["field_key"] in ("port_of_arrival", "pod", "port_of_discharge")
                                                     and docs.get(f["document_id"], {}).get("doc_type") != "CREW_LIST" and f["value"]]
    words = set().union(*[_port_words(a) for a in arrival]) if arrival else set()
    info = {}
    for d in crew_docs:
        text = "\n".join(r["text"] or "" for r in db.rows(conn, "SELECT text FROM document_pages WHERE document_id=? ORDER BY page_no", (d["id"],)))
        norm = " " + N.norm_text(text) + " "
        names_port = bool(words) and all((" " + w + " ") in norm or w in norm.replace(" ", "") for w in words)
        info[d["id"]] = (names_port, _doc_date(text))
    out = {}
    ids = sorted(pp, key=lambda i: (info[i][0], info[i][1] or datetime.min), reverse=True)  # preferred first
    for i, a in enumerate(ids):
        if a in out:
            continue
        for b in ids[i + 1:]:
            if b in out or docs[b].get("voyage_confirmed"):
                continue
            small = min(len(pp[a]), len(pp[b]))
            if small and len(pp[a] & pp[b]) >= max(2, small / 2):
                if info[a][0] and not info[b][0]:
                    why = "Crew List được giữ có ghi cảng đến của chuyến này"
                elif info[a][1] and info[b][1] and info[a][1] != info[b][1]:
                    why = f"Crew List được giữ có ngày mới hơn ({info[a][1]:%d/%m/%Y} so với {info[b][1]:%d/%m/%Y})"
                else:
                    continue  # cannot tell which list is this voyage's: leave both, duplicates are reported
                out[b] = (a, why)
    return out


class Ctx:
    def __init__(self, conn, voyage_id):
        self.conn = conn
        self.voyage = db.row(conn, "SELECT * FROM voyages WHERE id=?", (voyage_id,))
        self.docs = {d["id"]: d for d in db.rows(conn, "SELECT * FROM documents WHERE voyage_id=?", (voyage_id,))}
        self.fields = db.rows(conn, "SELECT * FROM extracted_fields WHERE voyage_id=? AND status!='EXCLUDED'", (voyage_id,))
        # a crew list of another port call (same crew, e.g. last port's list) is set aside, not reported as duplicates
        self.superseded = superseded_crew_lists(conn, self.docs, self.fields, self.voyage)
        self.fields = [f for f in self.fields if f["document_id"] not in self.superseded]
        self.results = []
        self.acks = {(a["check_key"], a["value1"] or "", a["value2"] or ""): a for a in
                     db.rows(conn, "SELECT * FROM crosscheck_acks WHERE voyage_id=?", (voyage_id,))}

    def doc_type(self, f):
        d = self.docs.get(f["document_id"])
        return d["doc_type"] if d else "MANUAL"

    def doc_name(self, doc_id):
        d = self.docs.get(doc_id)
        return d["original_name"] if d else "Hồ sơ chuyến tàu (nhập tay)"

    def add(self, group, status, message, field_key=None, record_key=None, f1=None, f2=None, v1=None, v2=None,
            suggestion=None, blocking=None, check_key=None, doc1=None, doc2=None, page1=None, page2=None):
        if f1:
            doc1, v1, page1 = f1["document_id"], f1["value"], f1["page_no"]
        if f2:
            doc2, v2, page2 = f2["document_id"], f2["value"], f2["page_no"]
        if blocking is None:
            blocking = status in BLOCKING
        key = check_key or "|".join(str(x) for x in (group, field_key, record_key, doc1, doc2, status))
        ack = self.acks.get((key, v1 or "", v2 or ""))
        self.results.append(dict(group_name=group, check_key=key, field_key=field_key, record_key=record_key, status=status,
                                 doc1_id=doc1, value1=v1, page1=page1, field1_id=f1["id"] if f1 else None,
                                 doc2_id=doc2, value2=v2, page2=page2, field2_id=f2["id"] if f2 else None,
                                 message=message, suggestion=suggestion, blocking=1 if blocking and not ack else 0,
                                 acknowledged=1 if ack else 0, ack_note=ack["note"] if ack else None))

    def header(self, key, types=None):
        return [f for f in self.fields if f["section"] == "vessel" and f["record_key"] == "header" and f["field_key"] == key
                and (types is None or self.doc_type(f) in types) and (f["value"] or "").strip()]

    def records(self, section, types=None):
        recs = defaultdict(dict)
        for f in self.fields:
            if f["section"] == section and (types is None or self.doc_type(f) in types):
                recs[(f["document_id"], f["record_key"])][f["field_key"]] = f
        return recs


def check_vessel(c: Ctx):
    for key, cmp, types in VESSEL_CHECKS:
        label = FIELD_LABELS.get(key, key)
        vals = c.header(key, types)
        if not vals:  # not in the main documents: any other declaration that states it (e.g. ETA on the crew list)
            vals = [f for f in c.header(key) if c.doc_type(f) not in ("OTHER", "REFERENCE", "MANUAL")]
        if not vals:
            c.add(GROUP_VESSEL, "NOT_AVAILABLE", f"{label}: Not Available in Source - không chứng từ nào ghi.", key, "header")
            continue
        if key == "imo":
            for f in vals:
                if not N.imo_valid(f["value"]):
                    c.add(GROUP_VESSEL, "NEEDS_REVIEW", f"IMO '{f['value']}' sai số kiểm tra (check digit) - có thể đọc sai hoặc ghi sai.", key, "header", f1=f,
                          suggestion="Đối chiếu với bản gốc chứng từ.")
        if len(vals) == 1:  # vessel particulars stated in one document are taken as they are - nothing to list
            continue
        base = vals[0]
        diff = False
        for other in vals[1:]:
            if other["document_id"] == base["document_id"]:
                continue
            if not cmp(base["value"], other["value"]):
                diff = True
                c.add(GROUP_VESSEL, "MISMATCH", f"{label} khác nhau giữa 2 chứng từ.", key, "header", f1=base, f2=other,
                      suggestion="Kiểm tra bản gốc; chọn giá trị đúng ở màn hình Đối chiếu hoặc sửa tại Kiểm tra & xác nhận.")
        if not diff:
            c.add(GROUP_VESSEL, "PASSED", f"{label} thống nhất giữa {len(vals)} chứng từ.", key, "header", f1=base, f2=vals[1])


IDENTITY_DOCS = {"GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "TONNAGE_CERTIFICATE", "CARGO_MANIFEST", "BILL_OF_LADING", "CREW_LIST",
                 "DG_MANIFEST", "PASSENGER_LIST", "SHIP_SECURITY", "EMPTY_CONTAINER_LIST"}


def check_mixed_vessels(c: Ctx):
    """Several different vessels (name / IMO) inside one document set -> documents of several voyages mixed."""
    for key, label in (("imo", "số IMO"), ("vessel_name", "tên tàu")):
        groups = defaultdict(list)
        for f in c.header(key):
            d = c.docs.get(f["document_id"])
            if d and not d.get("voyage_confirmed") and d["doc_type"] not in ("OTHER", "REFERENCE", None):
                groups[N.norm_id(f["value"]) if key == "imo" else N.vessel_key(f["value"])].append(f)
        if len(groups) > 1:
            detail = "; ".join(f"'{fs[0]['value']}': " + ", ".join(sorted({c.doc_name(x['document_id']) for x in fs})) for fs in groups.values())
            c.add(GROUP_DOC, "WRONG_VOYAGE", f"Bộ chứng từ có {len(groups)} {label} khác nhau - nghi trộn lẫn chứng từ của nhiều chuyến tàu. {detail}",
                  key, "header", check_key=f"mixed|{key}|" + "|".join(sorted(groups)),
                  suggestion="Kiểm tra từng chứng từ: xác nhận đúng hồ sơ, chuyển sang chuyến khác hoặc xóa.")
            return


def check_identity_available(c: Ctx):
    for doc_id, d in c.docs.items():
        if d["status"] != "EXTRACTED" or d["doc_type"] not in IDENTITY_DOCS or d.get("voyage_confirmed") or doc_id in c.superseded:
            continue
        if not any(f["document_id"] == doc_id for k in ("vessel_name", "imo", "voyage_no") for f in c.header(k)):
            c.add(GROUP_DOC, "NEEDS_REVIEW", f"Needs Manual Review: '{d['original_name']}' không ghi tên tàu / IMO / số chuyến đọc được - "
                  "chưa xác định được chứng từ có thuộc chuyến này không.", doc1=d["id"], blocking=False,
                  suggestion="Kiểm tra bản gốc rồi bấm 'Xác nhận đúng hồ sơ' ở màn hình Xử lý chứng từ.")


def check_wrong_voyage(c: Ctx):
    v = c.voyage
    ref = {"vessel_name": v.get("vessel_name"), "imo": v.get("imo"), "voyage_no": v.get("voyage_no")}
    # if the voyage record is empty, use the General Declaration as reference
    gd = {k: (c.header(k, ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL"]) or [None])[0] for k in ref}
    for doc_id, d in c.docs.items():
        if d.get("voyage_confirmed") or d["doc_type"] in ("OTHER", "REFERENCE", None):
            continue  # confirmed by staff / unknown documents (free text) are not compared
        for key, cmp in (("vessel_name", _cmp_vessel), ("imo", _cmp_id), ("voyage_no", _cmp_id)):
            fs = [f for f in c.header(key) if f["document_id"] == doc_id]
            if not fs:
                continue
            f = fs[0]
            if ref[key]:
                refv, src = ref[key], "hồ sơ chuyến tàu"
                f2 = None
            elif gd[key] and gd[key]["document_id"] != doc_id:
                refv, src, f2 = gd[key]["value"], c.doc_name(gd[key]["document_id"]), gd[key]
            else:
                continue
            if key == "voyage_no" and d["doc_type"] == "TONNAGE_CERTIFICATE":
                continue
            if cmp(f["value"], refv):
                continue
            a, b = N.norm_id(f["value"]), N.norm_id(refv)
            if key == "voyage_no" and a and b and (a in b or b in a):
                c.add(GROUP_DOC, "NEEDS_REVIEW", f"Số chuyến trên '{d['original_name']}' ({f['value']}) gần giống {src} ({refv}).", key, "header",
                      f1=f, f2=f2, v2=None if f2 else refv, suggestion="Xác nhận đây là cùng chuyến.")
                continue
            c.add(GROUP_DOC, "WRONG_VOYAGE", f"'{d['original_name']}' ghi {FIELD_LABELS[key]} = '{f['value']}', khác {src} ('{refv}'). "
                  "Possible Wrong Voyage Document - dữ liệu của chứng từ này tạm không đưa vào file Excel.", key, "header", f1=f, f2=f2, v2=None if f2 else refv,
                  suggestion="Kiểm tra bản gốc: xác nhận đúng hồ sơ, chuyển sang chuyến khác hoặc xóa chứng từ.")


def _cargo_cmp(kind, a, b):
    if kind == "company":
        ka, kb = _company_key(a), _company_key(b)
        if ka == kb:
            return "same"
        na, nb = _company_name(a), _company_name(b)
        if na and na == nb and len(na.split()) >= 2:
            return "same"  # same company; only the address part is written differently
        if ka and kb and (ka.startswith(kb) or kb.startswith(ka)):
            return "similar"
        wa, wb = set(ka.split()), set(kb.split())
        if wa and wb and len(wa & wb) >= 0.5 * min(len(wa), len(wb)):
            return "similar"  # same party, address written differently
        if _is_vietnamese(a) != _is_vietnamese(b):
            return ("bilingual", N.bilingual_match(a, b)) if N.bilingual_match(a, b) else "language"
        return "diff"
    if kind == "text":
        if _cmp_text(a, b):
            return "same"
        ka, kb = N.norm_text(a), N.norm_text(b)
        if ka and kb and (ka in kb or kb in ka):
            return "similar"
        ev = N.bilingual_match(a, b)
        return ("bilingual", ev) if ev else "diff"
    if kind in ("number", "weight"):
        return "same" if _cmp_number(a, b) else "diff"
    if kind == "set":
        return "same" if _cmp_set(a, b) else "diff"
    if kind == "port":
        return "same" if _cmp_port(a, b) else "diff"
    return "same" if _cmp_text(a, b) else "diff"


def _with_unit(rec, key):
    f = rec.get(key)
    if not f:
        return None
    u = rec.get(key + "_unit")
    return f"{f['value']} {u['value']}" if u and not re.search(r"[A-Za-z]{2,}", f["value"] or "") else f["value"]


def check_cargo(c: Ctx):
    manifest = c.records("cargo", ["CARGO_MANIFEST"])
    bls = c.records("cargo", ["BILL_OF_LADING"])
    if not manifest and not bls:
        c.add(GROUP_CARGO, "NOT_AVAILABLE", "Chưa có Cargo Manifest và B/L - Not Available in Source.")
        return
    if not manifest:
        c.add(GROUP_CARGO, "NOT_ENOUGH_DATA", "Chưa có Cargo Manifest - Not Enough Data để đối chiếu với B/L.")
    if not bls:
        c.add(GROUP_CARGO, "NOT_ENOUGH_DATA", "Chưa có B/L - Not Enough Data để đối chiếu với Cargo Manifest.")

    by_bl = defaultdict(list)
    seen = {}
    for (doc_id, rk), rec in sorted(manifest.items(), key=lambda x: (x[0][0], x[1].get("bl_no", {}).get("record_index", 0))):
        bl = N.norm_id(rec.get("bl_no", {}).get("value"))
        if not bl:
            any_f = next(iter(rec.values()))
            c.add(GROUP_CARGO, "MISSING_INFO", f"Dòng manifest {rk} không có số B/L.", "bl_no", rk, f1=any_f, v1="", blocking=True)
            continue
        by_bl[bl].append(rec)
        sig = (bl, N.norm_id(rec.get("container_no", {}).get("value")), N.norm_text(rec.get("description", {}).get("value")))
        if sig in seen:
            c.add(GROUP_CARGO, "DUPLICATE", f"Dòng manifest trùng lặp: B/L {bl}, container {sig[1] or '-'}.", "bl_no", rk,
                  f1=seen[sig]["bl_no"], f2=rec["bl_no"])
        seen[sig] = rec
        for cn in re.split(r"[,;\s]+", rec.get("container_no", {}).get("value") or ""):
            if cn and not N.container_valid(cn):
                c.add(GROUP_CARGO, "NEEDS_REVIEW", f"Số container '{cn}' không đúng chuẩn ISO 6346 (check digit).", "container_no", rk, f1=rec["container_no"])

    matched = set()
    for (doc_id, rk), b in bls.items():
        blf = b.get("bl_no")
        if not blf:
            c.add(GROUP_CARGO, "MISSING_INFO", f"Không đọc được số B/L trong '{c.doc_name(doc_id)}'.", "bl_no", rk, doc1=doc_id, v1="", blocking=True)
            continue
        bl = N.norm_id(blf["value"])
        rows = by_bl.get(bl)
        if not manifest:
            continue
        if not rows:
            c.add(GROUP_CARGO, "NEEDS_REVIEW", f"B/L {blf['value']} có vận đơn nhưng không có trong Cargo Manifest.", "bl_no", rk, f1=blf, v2="",
                  blocking=True, suggestion="Kiểm tra B/L có thuộc chuyến này không / manifest có thiếu dòng không.")
            continue
        matched.add(bl)
        for key, kind in CARGO_CHECKS:
            label = FIELD_LABELS.get(key, key)
            bf = b.get(key)
            mvals = [r.get(key) for r in rows if r.get(key)]
            if not bf and not mvals:
                continue
            if not bf or not mvals:
                src = "B/L" if not bf else "Manifest"
                c.add(GROUP_CARGO, "SINGLE_SOURCE", f"B/L {bl} - {label}: đã lấy dữ liệu từ {'Manifest' if src == 'B/L' else 'B/L'} ({src} không ghi).", key, f"bl:{bl}",
                      f1=bf or mvals[0], blocking=False)
                continue
            if len(rows) > 1 and kind in ("number", "weight"):
                nums = [N.number_key(_with_unit(r, key)) for r in rows]
                if any(n is None for n in nums) or len({n[1] for n in nums}) > 1:
                    c.add(GROUP_CARGO, "NEEDS_REVIEW", f"B/L {bl} - {label}: manifest có {len(rows)} dòng, không cộng được để so sánh.", key, f"bl:{bl}", f1=bf)
                    continue
                total = sum(n[0] for n in nums)
                mval = f"{N.fmt_number(total)} {nums[0][1] or ''}".strip()
                res = "same" if _cmp_number(_with_unit(b, key), mval) else "diff"
                note = f" (tổng {len(rows)} dòng manifest)"
                mf = mvals[0]
            elif kind == "set" and len(rows) > 1:
                mval = ", ".join(r[key]["value"] for r in rows if r.get(key))
                res, note, mf = _cargo_cmp(kind, bf["value"], mval), f" (gộp {len(rows)} dòng manifest)", mvals[0]
            else:
                mf = mvals[0]
                mval = _with_unit(rows[0], key) if kind in ("number", "weight") else mf["value"]
                res, note = _cargo_cmp(kind, _with_unit(b, key) if kind in ("number", "weight") else bf["value"], mval), ""
            if isinstance(res, tuple):
                c.add(GROUP_CARGO, "PASSED", f"B/L {bl} - {label} khớp sau đối chiếu song ngữ Việt–Anh (căn cứ: \"{res[1]}\"){note}.",
                      key, f"bl:{bl}", f1=mf, f2=bf, v1=mval)
            elif res == "same":
                c.add(GROUP_CARGO, "PASSED", f"B/L {bl} - {label} khớp{note}.", key, f"bl:{bl}", f1=mf, f2=bf, v1=mval)
            elif res == "language":
                c.add(GROUP_CARGO, "NEEDS_REVIEW", f"B/L {bl} - {label}: một chứng từ ghi tiếng Việt, một chứng từ ghi tiếng Anh{note} - nhân viên xác nhận "
                      "cùng một bên.", key, f"bl:{bl}", f1=mf, f2=bf, v1=mval, blocking=False)
            elif res == "similar" or key == "description":
                # descriptions are free text (often another language / more detail): staff compare, no automatic verdict
                c.add(GROUP_CARGO, "NEEDS_REVIEW", f"B/L {bl} - {label}: cách ghi khác nhau{' (có thể viết tắt)' if res == 'similar' else ' (ngôn ngữ / mức chi tiết khác)'}"
                      f"{note} - nhân viên so sánh nội dung.", key, f"bl:{bl}", f1=mf, f2=bf, v1=mval, blocking=False)
            else:
                c.add(GROUP_CARGO, "MISMATCH", f"B/L {bl} - {label}: Cargo Manifest và B/L khác nhau{note}.", key, f"bl:{bl}", f1=mf, f2=bf, v1=mval,
                      suggestion="Kiểm tra bản gốc. Hệ thống không tự chọn giá trị.")
    if bls:
        for bl, rows in by_bl.items():
            if bl not in matched:
                c.add(GROUP_CARGO, "SINGLE_SOURCE", f"B/L {bl}: đã lấy dữ liệu từ Cargo Manifest (chưa có vận đơn riêng để so).", "bl_no", f"bl:{bl}",
                      f1=rows[0]["bl_no"], blocking=False)


def check_crew(c: Ctx):
    for b, (a, why) in c.superseded.items():
        c.add(GROUP_CREW, "NEEDS_REVIEW", f"'{c.doc_name(b)}' có cùng thuyền viên với '{c.doc_name(a)}' - đây là Crew List của cảng/thời điểm khác, "
              f"hệ thống dùng '{c.doc_name(a)}' cho chuyến này và KHÔNG đưa bản kia vào Excel ({why}).", None, None, doc1=b, doc2=a, blocking=False,
              suggestion="Nếu chọn sai: mở chứng từ bị loại ở màn hình Xử lý chứng từ và bấm 'Xác nhận đúng hồ sơ'.")
    crew_docs = [d for d in c.docs.values() if d["doc_type"] == "CREW_LIST" and d["id"] not in c.superseded]
    if not crew_docs:
        c.add(GROUP_CREW, "MISSING_INFO", "Chưa có Crew List trong bộ chứng từ.", blocking=False)
        return
    recs = c.records("crew", ["CREW_LIST", "MANUAL"])
    if not recs:
        c.add(GROUP_CREW, "MISSING_INFO", "Không trích xuất được dòng thuyền viên nào từ Crew List (bản scan/ảnh mờ hoặc bố cục chưa nhận diện). "
              "Cần nhập bổ sung tại màn hình Kiểm tra & xác nhận.", blocking=True)
        return
    n = len(recs)
    counts = c.header("crew_count", ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "CREW_LIST"])
    if not counts:
        c.add(GROUP_CREW, "SINGLE_SOURCE", f"Đã lấy {n} thuyền viên từ Crew List; GD/NOA không ghi số thuyền viên nên không so được số lượng.", "crew_count")
    for f in counts:
        try:
            k = int(re.sub(r"\D", "", f["value"]))
        except ValueError:
            continue
        if k == n:
            c.add(GROUP_CREW, "PASSED", f"Số thuyền viên khớp: {c.doc_name(f['document_id'])} = {k}, Crew List = {n} dòng.", "crew_count", f1=f, v2=str(n))
        else:
            c.add(GROUP_CREW, "MISMATCH", f"Số thuyền viên: {c.doc_name(f['document_id'])} ghi {k}, Crew List có {n} dòng.", "crew_count", f1=f, v2=str(n),
                  doc2=crew_docs[0]["id"], suggestion="Kiểm tra Crew List có thiếu/thừa dòng hoặc trích xuất bỏ sót trang.")
    seen_pp, seen_nm = {}, {}
    eta = (c.header("eta") or [None])[0]
    eta_d, _ = N.parse_date(eta["value"]) if eta else (None, False)
    for (doc_id, rk), r in sorted(recs.items(), key=lambda x: next(iter(x[1].values()))["record_index"]):
        name_f = r.get("full_name") or r.get("family_name") or r.get("given_name")
        nm = (name_f or {}).get("value") or rk
        missing = [FIELD_LABELS[k] for k in ("rank", "nationality", "dob", "passport_no") if not (r.get(k) and r[k]["value"])]
        if not name_f:
            missing.insert(0, "Họ tên")
        if missing:
            c.add(GROUP_CREW, "MISSING_INFO", f"Thuyền viên '{nm}' thiếu: {', '.join(missing)}.", None, rk, f1=name_f, doc1=doc_id, blocking=False)
        pp = N.norm_id((r.get("passport_no") or {}).get("value"))
        if pp:
            if pp in seen_pp:
                c.add(GROUP_CREW, "DUPLICATE", f"Trùng số hộ chiếu {pp}: '{seen_pp[pp][0]}' và '{nm}'.", "passport_no", rk, f1=seen_pp[pp][1], f2=r["passport_no"])
            seen_pp[pp] = (nm, r["passport_no"])
        key = (N.norm_text(nm), (r.get("dob") or {}).get("value"))
        if name_f and key in seen_nm:
            c.add(GROUP_CREW, "DUPLICATE", f"Trùng họ tên + ngày sinh: '{nm}'.", "full_name", rk, f1=seen_nm[key], f2=name_f)
        seen_nm[key] = name_f
        for dk in ("dob", "passport_expiry"):
            f = r.get(dk)
            if f and f["value"]:
                d, ok = N.parse_date(f["value"])
                yr = int(d[6:10]) if ok and re.match(r"\d{2}/\d{2}/\d{4}", d) else None
                if not ok:
                    c.add(GROUP_CREW, "NEEDS_REVIEW", f"'{nm}' - {FIELD_LABELS[dk]} '{f['value']}' không đúng định dạng ngày.", dk, rk, f1=f)
                elif yr and not ((1930 if dk == "dob" else 1990) <= yr <= (datetime.now().year if dk == "dob" else 2100)):
                    c.add(GROUP_CREW, "NEEDS_REVIEW", f"'{nm}' - {FIELD_LABELS[dk]} '{f['value']}' có năm không hợp lý (có thể đọc sai bản scan).", dk, rk, f1=f,
                          suggestion="Đối chiếu bản gốc và sửa tại Kiểm tra & xác nhận.")
                elif dk == "passport_expiry" and eta_d:
                    if datetime.strptime(d[:10], "%d/%m/%Y") < datetime.strptime(eta_d[:10], "%d/%m/%Y"):
                        c.add(GROUP_CREW, "NEEDS_REVIEW", f"'{nm}' - hộ chiếu hết hạn ({d}) trước ETA ({eta_d}).", dk, rk, f1=f)
    if not any(r["status"] in ("MISMATCH", "DUPLICATE") for r in c.results if r["group_name"] == GROUP_CREW):
        c.add(GROUP_CREW, "PASSED", f"Đã kiểm tra {n} thuyền viên: không phát hiện trùng lặp.", blocking=False)


def check_dg(c: Ctx):
    dg = c.records("dg", ["DG_MANIFEST"])
    if not dg:
        if any(d["doc_type"] == "DG_MANIFEST" for d in c.docs.values()):
            c.add(GROUP_DG, "MISSING_INFO", "Có DG Manifest nhưng không trích xuất được dòng hàng nguy hiểm nào.", blocking=True)
        else:
            c.add(GROUP_DG, "NOT_AVAILABLE", "Không có Dangerous Goods Manifest trong bộ chứng từ (Not Available in Source).")
        return
    manifest = c.records("cargo", ["CARGO_MANIFEST", "BILL_OF_LADING"])
    by_bl = defaultdict(list)
    for (_d, rk), r in manifest.items():
        if r.get("bl_no"):
            by_bl[N.norm_id(r["bl_no"]["value"])].append(r)
    for (doc_id, rk), r in dg.items():
        un = (r.get("un_no") or {}).get("value")
        if not un or not re.fullmatch(r"(UN)?\s*\d{4}", un.strip(), re.I):
            c.add(GROUP_DG, "NEEDS_REVIEW", f"Dòng DG {rk}: UN No. '{un or ''}' thiếu hoặc sai định dạng (4 chữ số).", "un_no", rk, f1=r.get("un_no"), doc1=doc_id)
        cls = (r.get("imdg_class") or {}).get("value")
        if not cls or not re.fullmatch(r"(CLASS\s*)?[1-9](\.\d)?[A-Z]?", cls.strip(), re.I):
            c.add(GROUP_DG, "NEEDS_REVIEW", f"Dòng DG {rk}: IMDG Class '{cls or ''}' thiếu hoặc sai định dạng.", "imdg_class", rk, f1=r.get("imdg_class"), doc1=doc_id)
        blf = r.get("bl_no")
        if not blf:
            c.add(GROUP_DG, "MISSING_INFO", f"Dòng DG {rk} không có số B/L.", "bl_no", rk, doc1=doc_id, blocking=False)
            continue
        rows = by_bl.get(N.norm_id(blf["value"]))
        if not manifest:
            c.add(GROUP_DG, "NOT_ENOUGH_DATA", "Chưa có Manifest/B/L để đối chiếu hàng nguy hiểm.", blocking=False)
            return
        if not rows:
            c.add(GROUP_DG, "MISMATCH", f"B/L {blf['value']} có trong DG Manifest nhưng không có trong Cargo Manifest/B/L.", "bl_no", rk, f1=blf, v2="")
            continue
        for key, dkey, kind in (("container_no", "container_no", "set"), ("gross_weight", "gross_weight", "weight"),
                                ("proper_shipping_name", "description", "text")):
            df = r.get(key)
            mf = next((x.get(dkey) for x in rows if x.get(dkey)), None)
            if not df or not mf:
                continue
            res = _cargo_cmp(kind, _with_unit(r, key) if kind == "weight" else df["value"], _with_unit(rows[0], dkey) if kind == "weight" else mf["value"])
            lbl = FIELD_LABELS.get(key, key)
            if isinstance(res, tuple):
                res = "same"
            if res == "same":
                c.add(GROUP_DG, "PASSED", f"B/L {blf['value']} - {lbl} khớp giữa DG Manifest và Cargo Manifest/B/L.", key, rk, f1=df, f2=mf)
            elif res == "similar" or kind == "text":
                c.add(GROUP_DG, "NEEDS_REVIEW", f"B/L {blf['value']} - {lbl}: cách ghi khác nhau giữa DG và manifest.", key, rk, f1=df, f2=mf, blocking=False)
            else:
                c.add(GROUP_DG, "MISMATCH", f"B/L {blf['value']} - {lbl} khác nhau giữa DG Manifest và Cargo Manifest/B/L.", key, rk, f1=df, f2=mf)


def check_containers(c: Ctx):
    """E. Containers across Cargo Manifest, B/L, Empty Container List and DG Manifest (key = container number)."""
    laden = defaultdict(set)   # container -> set of B/L numbers on the manifest / B/Ls
    where = {}
    for sec, types in (("cargo", ["CARGO_MANIFEST", "BILL_OF_LADING", "MANUAL"]),):
        for (doc_id, rk), r in c.records(sec, types).items():
            f = r.get("container_no")
            if not f:
                continue
            for cn in re.split(r"[,;\s]+", f["value"] or ""):
                cn = N.norm_id(cn)
                if cn:
                    laden[cn].add(N.norm_id((r.get("bl_no") or {}).get("value")) or "?")
                    where.setdefault(cn, f)
    empty = {}
    for (doc_id, rk), r in c.records("empty_container", ["EMPTY_CONTAINER_LIST", "MANUAL"]).items():
        f = r.get("container_no")
        if f and f["value"]:
            cn = N.norm_id(f["value"])
            if cn in empty:
                c.add(GROUP_CONT, "DUPLICATE", f"Container rỗng {cn} xuất hiện 2 lần trong danh sách container rỗng.", "container_no", rk,
                      f1=empty[cn], f2=f)
            empty[cn] = f
            if not N.container_valid(cn):
                c.add(GROUP_CONT, "NEEDS_REVIEW", f"Số container rỗng '{cn}' không đúng chuẩn ISO 6346.", "container_no", rk, f1=f)
    if not laden and not empty:
        c.add(GROUP_CONT, "NOT_AVAILABLE", "Bộ chứng từ không có số container (hàng rời / chưa tải manifest) - Not Available in Source.")
        return
    issues = 0
    for cn, bls in laden.items():
        manifest_bls = {b for b in bls if b != "?"}
        if len(manifest_bls) > 1:
            issues += 1
            c.add(GROUP_CONT, "NEEDS_REVIEW", f"Container {cn} khai cho {len(manifest_bls)} vận đơn ({', '.join(sorted(manifest_bls))}) - "
                  "kiểm tra hàng ghép (LCL) hay khai trùng.", "container_no", None, f1=where[cn], blocking=False)
        if cn in empty:
            issues += 1
            c.add(GROUP_CONT, "MISMATCH", f"Container {cn} vừa có trong danh sách container RỖNG vừa có hàng trên Manifest/B/L.",
                  "container_no", None, f1=empty[cn], f2=where[cn])
    dg = c.records("dg", ["DG_MANIFEST"])
    for (doc_id, rk), r in dg.items():
        f = r.get("container_no")
        if f and laden and N.norm_id(f["value"]) not in laden:
            issues += 1
            c.add(GROUP_CONT, "MISMATCH", f"Container {f['value']} trên DG Manifest không có trong Cargo Manifest/B/L.", "container_no", rk, f1=f, v2="")
    if not issues:
        c.add(GROUP_CONT, "PASSED" if (laden and (empty or dg)) else "SINGLE_SOURCE",
              f"{len(laden)} container có hàng, {len(empty)} container rỗng: không trùng giữa hàng/rỗng, không lệch giữa DG và Manifest."
              + ("" if (laden and (empty or dg)) else " (container chỉ có ở 1 loại chứng từ - đã lấy dữ liệu, không có nguồn thứ hai để so)"), blocking=False)


def check_documents(c: Ctx):
    hashes = defaultdict(list)
    for d in c.docs.values():
        if d["status"] == "SPLIT":
            continue  # combined file: its parts are checked as separate documents
        hashes[d["sha256"]].append(d)
        if d["status"] == "ERROR":
            c.add(GROUP_DOC, "NEEDS_REVIEW", f"'{d['original_name']}' xử lý lỗi: {d['error']}", doc1=d["id"], blocking=False)
        elif d["status"] != "EXTRACTED":
            c.add(GROUP_DOC, "NEEDS_REVIEW", f"'{d['original_name']}' chưa được trích xuất.", doc1=d["id"], blocking=False)
        if d["doc_type"] == "OTHER" and not d["doc_type_confirmed"] and d["status"] != "SPLIT":
            c.add(GROUP_DOC, "NEEDS_REVIEW", f"'{d['original_name']}' chưa nhận diện được loại chứng từ - cần chọn loại.", doc1=d["id"], blocking=False)
    for h, ds in hashes.items():
        if len(ds) > 1:
            c.add(GROUP_DOC, "DUPLICATE", "Tải trùng file: " + ", ".join(d["original_name"] for d in ds), doc1=ds[0]["id"], doc2=ds[1]["id"])


def check_quality(c: Ctx):
    for f in c.fields:
        if f["confidence"] is not None and f["confidence"] < LOW_CONF and f["status"] != "CONFIRMED":
            c.add(GROUP_QUALITY, "LOW_CONFIDENCE", f"{FIELD_LABELS.get(f['field_key'], f['field_key'])} = '{f['value']}' có độ tin cậy "
                  f"{round(f['confidence'] * 100)}% ({f['method']}). Cần đối chiếu bản gốc và xác nhận.", f["field_key"], f["record_key"], f1=f, blocking=False)


def run(conn, voyage_id, user):
    c = Ctx(conn, voyage_id)
    check_documents(c)
    check_mixed_vessels(c)
    check_identity_available(c)
    check_wrong_voyage(c)
    check_vessel(c)
    check_cargo(c)
    check_crew(c)
    check_dg(c)
    check_containers(c)
    check_quality(c)
    summary = defaultdict(int)
    for r in c.results:
        summary[r["status"]] += 1
    summary["BLOCKING"] = sum(r["blocking"] for r in c.results)
    cur = conn.execute("INSERT INTO crosscheck_runs(voyage_id,run_at,run_by,summary_json) VALUES(?,?,?,?)",
                       (voyage_id, db.now(), user, db.dumps(summary)))
    run_id = cur.lastrowid
    conn.execute("DELETE FROM crosscheck_results WHERE voyage_id=?", (voyage_id,))
    for r in c.results:
        cols = ",".join(r.keys())
        conn.execute(f"INSERT INTO crosscheck_results(run_id,voyage_id,{cols}) VALUES(?,?,{','.join('?' * len(r))})",
                     (run_id, voyage_id, *r.values()))
    return run_id, dict(summary)
