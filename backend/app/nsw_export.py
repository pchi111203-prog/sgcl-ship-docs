"""NSW template mapping, export and post-export verification.

The mapping below was built from the actual template workbook (21 sheets).  Cell positions
come from the template labels (column A) - see docs/NSW_TEMPLATE_ANALYSIS.md.
Only values confirmed by staff (or entered by staff) are written.  Nothing is invented:
cells without a source stay empty and are listed in the export report.
"""
import os
import re
import shutil
import subprocess
import tempfile
import warnings
from collections import defaultdict

from . import db
from . import normalize as N
from . import crosscheck
from .crosscheck import _locode
from .extract import OPERATION_KEYS
from .xlsxpatch import Book, col2num, num2col, split_ref

SIGNERS = ["Thuyền trưởng/Master", "Đại lý/ShipAgency", "Chủ tàu/ShipOwner"]
NAME_SPLITS = {
    "dash_family": "Họ = '-', Tên = họ tên đầy đủ",
    "full_in_both": "Ghi họ tên đầy đủ vào cả cột Họ và cột Tên",
    "last_word_given": "Họ = các từ đầu, Tên = từ cuối cùng (VD: NGUYEN VAN | AN)",
    "first_word_family": "Họ = từ đầu tiên, Tên = các từ còn lại (VD: NGUYEN | VAN AN)",
}
DEFAULT_OPTIONS = {"doc_function": "CN01", "doc_no": "", "doc_year": "", "sign_place": "", "sign_date": "", "signer": "",
                   "crew_passport_type": "", "name_split": "dash_family", "passenger_passport_type": ""}

GD, NOA = "GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL"
SEC = "SHIP_SECURITY"


def _gd_rows(offset_after_19):
    """Rows 3..19 identical for 'General Declaration' and 'Notice ship to port'; rows after 19 differ.
    Port cells hold UN/LOCODE codes; B7/B8 = port of arrival, as in SGCL's filled NSW workbook."""
    rows = [("B3", "Số hồ sơ / Document's No", "opt:doc_no"), ("B4", "Năm đăng ký hồ sơ", "opt:doc_year"),
            ("B5", "Chức năng của chứng từ", "opt:doc_function"),
            ("B6", "Các cảng trước (mã cảng rời cuối)", "src:last_port:locode"),
            ("B7", "Các cảng sẽ đến (mã cảng đến)", "src:port_of_arrival:locode"),
            ("B8", "Các cảng sẽ dỡ hàng (mã cảng đến)", "src:port_of_arrival:locode"), ("B9", "Số hàng còn lại", "manual"),
            ("B10", "Mớn nước F (m)", "src:draft_fwd:num"), ("B11", "Mớn nước A (m)", "src:draft_aft:num"),
            ("B12", "Chiều cao tĩnh không (m)", "src:air_draft:num"), ("B13", "Ghi chú", "voyage:notes"),
            ("B14", "Bản khai hàng hóa kèm theo (1/0)", "docs:CARGO_MANIFEST|BILL_OF_LADING"),
            ("B15", "Bản khai dự trữ tàu kèm theo (1/0)", "docs:SHIP_STORES"),
            ("B16", "Danh sách thuyền viên kèm theo (1/0)", "docs:CREW_LIST"),
            ("B17", "Danh sách hành khách kèm theo (1/0)", "docs:PASSENGER_LIST"),
            ("B18", "Bản khai hành lý thuyền viên kèm theo (1/0)", "docs:CREW_EFFECTS"),
            ("B19", "Bản khai kiểm dịch y tế kèm theo (1/0)", "docs:HEALTH_DECLARATION")]
    return rows + offset_after_19


SHEET_HEADERS = {
    "General Declaration": (_gd_rows([
        ("B20", "Yêu cầu tiếp nhận chất thải", "src:waste_request"), ("B21", "Vị trí tàu tại cảng", "src:berth"), ("B22", "Tàu lai", "src:tug"),
        ("B23", "Mã số giấy phép rời cảng", "src:port_clearance_no"), ("B24", "Thời gian đến cảng", "src:eta:date"), ("B25", "Thời gian cập cảng", "src:berthing_time:date"),
        ("B26", "Thời gian hoa tiêu lên tàu", "src:pilot_on_board:date"), ("B27", "Link tra cứu GP rời cảng", "manual"), ("B28", "Mã vạch GP rời cảng", "manual"),
        ("B29", "Dầu DO", "src:rob_do:num"), ("B30", "Dầu FO", "src:rob_fo:num"), ("B31", "Nước ngọt FW", "src:rob_fw:num"),
        ("B32", "Nơi ký", "opt:sign_place"), ("B33", "Ngày ký", "opt:sign_date"), ("B34", "Người ký", "opt:signer")]), [GD, NOA]),
    "Notice ship to port": (_gd_rows([
        ("B20", "Yêu cầu tiếp nhận chất thải", "src:waste_request"), ("B21", "Vị trí tàu tại cảng", "src:berth"), ("B22", "Tàu lai", "src:tug"),
        ("B23", "Mã số giấy phép rời cảng", "src:port_clearance_no"), ("B24", "Thời gian đến/rời cảng", "src:eta:date"),
        ("B25", "Thời gian cập cảng", "src:berthing_time:date"), ("B26", "Thời gian hoa tiêu lên tàu", "src:pilot_on_board:date"), ("B27", "Dầu DO", "src:rob_do:num"), ("B28", "Dầu FO", "src:rob_fo:num"),
        ("B29", "Nước ngọt FW", "src:rob_fw:num"), ("B30", "Nơi ký", "opt:sign_place"), ("B31", "Ngày ký", "opt:sign_date"),
        ("B32", "Người ký", "opt:signer")]), [NOA, GD]),
    "ConfirmationOfArrival": ([("B3", "Số hồ sơ", "opt:doc_no"), ("B4", "Năm đăng ký", "opt:doc_year"), ("B5", "Chức năng", "opt:doc_function"),
                               ("B6", "Thời gian đến/rời (thực tế)", "manual"), ("B7", "Các yêu cầu khác", "manual"),
                               ("B8", "Nơi ký", "opt:sign_place"), ("B9", "Ngày ký", "opt:sign_date"), ("B10", "Người ký", "opt:signer")], []),
    "Goods Declaration": ([("B3", "Số hồ sơ", "opt:doc_no"), ("B4", "Năm đăng ký", "opt:doc_year"), ("B5", "Chức năng", "opt:doc_function"),
                           ("B6", "Tổng số kiện", "derived:total_packages"), ("B7", "Loại kiện (mã)", "derived:package_kind")], []),
    "Crew list": ([("B3", "Số hồ sơ", "opt:doc_no"), ("B4", "Năm đăng ký", "opt:doc_year"), ("B5", "Chức năng", "opt:doc_function"),
                   ("B6", "Nơi ký", "opt:sign_place"), ("B7", "Ngày ký", "opt:sign_date"), ("B8", "Người ký", "opt:signer")], []),
    "Crew's Effects Declaration": ([("B3", "Số hồ sơ", "opt:doc_no"), ("B4", "Năm đăng ký", "opt:doc_year"), ("B5", "Chức năng", "opt:doc_function"),
                                    ("B6", "Nơi ký", "opt:sign_place"), ("B7", "Ngày ký", "opt:sign_date"), ("B8", "Người ký", "opt:signer")], []),
    "Ship's store declaration": ([("B3", "Số hồ sơ", "opt:doc_no"), ("B4", "Năm đăng ký", "opt:doc_year"), ("B5", "Chức năng", "opt:doc_function"),
                                  ("B6", "Số người trên tàu", "manual"), ("B7", "Thời gian ở cảng", "manual"),
                                  ("B8", "Nơi ký", "opt:sign_place"), ("B9", "Ngày ký", "opt:sign_date"), ("B10", "Người ký", "opt:signer")], []),
    "Passenger list": ([("B3", "Số hồ sơ", "opt:doc_no"), ("B4", "Năm đăng ký", "opt:doc_year"), ("B5", "Chức năng", "opt:doc_function"),
                        ("B6", "Nơi ký", "opt:sign_place"), ("B7", "Ngày ký", "opt:sign_date"), ("B8", "Người ký", "opt:signer")], []),
    "Dangerous goods manifest": ([("B3", "Số hồ sơ", "opt:doc_no"), ("B4", "Năm đăng ký", "opt:doc_year"), ("B5", "Chức năng", "opt:doc_function"),
                                  ("B6", "Cảng nhận hàng (mã)", "src:port_of_loading:locode"), ("B7", "Cảng trả hàng (mã)", "src:port_of_discharge:locode"),
                                  ("B8", "Thông tin bổ sung", "manual"), ("B9", "Nơi ký", "opt:sign_place"), ("B10", "Ngày ký", "opt:sign_date"),
                                  ("B11", "Người ký", "opt:signer")], ["DG_MANIFEST", "CARGO_MANIFEST"]),
    "Empty Container": ([("B3", "Số hồ sơ", "opt:doc_no"), ("B4", "Năm đăng ký", "opt:doc_year")], []),
    "Declaration For Ship Security": ([("B3", "Số hồ sơ", "opt:doc_no"), ("B4", "Năm đăng ký", "opt:doc_year"),
                                       ("B9", "Tên cơ quan cấp ISSC", "src:issc_issuer"), ("B10", "Ngày cấp ISSC", "src:issc_issue_date:date"),
                                       ("B11", "Ngày ISSC hết hạn", "src:issc_expiry:date"), ("B12", "Cấp độ an ninh hiện tại", "src:security_level:level"),
                                       ("B17", "Vĩ độ", "src:latitude"), ("B18", "Kinh độ", "src:longitude"), ("B19", "ETA", "src:eta:date"),
                                       ("B20", "Nơi ký", "opt:sign_place"), ("B21", "Ngày ký", "opt:sign_date"), ("B22", "Người ký", "opt:signer")], [SEC]),
}
# header block is only written when the matching document exists in the voyage
ONLY_IF_DOC = {"Declaration For Ship Security": SEC, "Empty Container": "EMPTY_CONTAINER_LIST"}
# Regions with no source document in this system: any leftover value is cleared, structure kept.
CLEAR_ONLY = {
    "General Declaration": ["A38:C43", "A46:G51"],
    "Notice ship to port": ["A36:C41", "A44:G46"],
    "ConfirmationOfArrival": ["A13:F18"],
    "List of House bill of lading": ["A4:X4", "B7:G7"],
    "Cargo manifest": ["B3:B9", "A12:K15"],
    "Declaration For Ship Security": ["B6:B8", "B13:B16"],
    "Declaration For Plant": ["B3:B4", "B6:B15"],
    "Declaration For Animal": ["B3:B4", "B6:B12"],
    "Declaration For Health": ["B3:B4", "B6:B22", "B25:B42", "A46:G49", "A52:N54"],
    "Arms And Explosive Materials": ["A8:A8", "C8:H8"],
    "Declaration of Stowaway": ["B4:B5", "B7:B10", "A13:AS13"],
    "Add User": ["A5:Q6"],
}
DOC_FUNCTION_CELLS = {"Declaration For Ship Security": "B5", "Declaration For Plant": "B5", "Declaration For Animal": "B5",
                      "Declaration For Health": "B5", "Empty Container": "B5", "Arms And Explosive Materials": "B5",
                      "Declaration of Stowaway": "B6", "Cargo manifest": None}

TABLES = {
    "Crew list": dict(first=11, old_last=11, cols="A:K", source="crew"),
    "Crew's Effects Declaration": dict(first=11, old_last=11, cols="A:D", source="effects"),
    "Ship's store declaration": dict(first=13, old_last=13, cols="A:E", source="store"),
    "Passenger list": dict(first=11, old_last=11, cols="A:M", source="passenger"),
    "Goods Declaration": dict(first=10, old_last=10, cols="A:W", source="cargo"),
    "Dangerous goods manifest": dict(first=14, old_last=14, cols="A:P", source="dg"),
    "Empty Container": dict(first=8, old_last=11, cols="A:D", source="empty_container"),  # rows 8-11 carry the port-name lookup formula
    # NSW form: last 10 port calls (rows 25-34)
    "Declaration For Ship Security": dict(first=25, old_last=25, cols="A:E", source="port_calls", max_row=34),
}


PORT_KEYS = {"pod", "pol", "port_of_arrival", "last_port", "next_port", "port_of_loading", "port_of_discharge", "place_of_delivery"}


class Plan:
    def __init__(self):
        self.cells = {}          # (sheet, ref) -> value
        self.prov = {}           # (sheet, ref) -> {label, sources:[...], kind}
        self.tables = {}         # sheet -> list of row dicts {col: value}
        self.table_prov = {}
        self.used_fields = set()
        self.blockers = []
        self.warnings = []
        self.empty = []          # mapped cells without data


def _opts(conn, voyage_id):
    o = dict(DEFAULT_OPTIONS)
    for r in db.rows(conn, "SELECT key,value FROM export_options WHERE voyage_id=?", (voyage_id,)):
        o[r["key"]] = r["value"]
    return o


def _num(v):
    n, _ = N.parse_number(v)
    return N.fmt_number(n) if n is not None else v


class Data:
    def __init__(self, conn, voyage_id):
        self.docs = {d["id"]: d for d in db.rows(conn, "SELECT * FROM documents WHERE voyage_id=?", (voyage_id,))}
        # documents suspected to belong to another voyage are kept out of the declaration until staff confirm / move them
        self.suspect = {r["doc1_id"] for r in db.rows(conn, "SELECT doc1_id FROM crosscheck_results WHERE voyage_id=? AND status='WRONG_VOYAGE' "
                                                          "AND acknowledged=0 AND doc1_id IS NOT NULL", (voyage_id,))}
        self.suspect -= {d for d, x in self.docs.items() if x.get("voyage_confirmed")}
        all_fields = db.rows(conn, "SELECT * FROM extracted_fields WHERE voyage_id=? AND status!='EXCLUDED'", (voyage_id,))
        voyage = db.row(conn, "SELECT * FROM voyages WHERE id=?", (voyage_id,))
        self.superseded = set(crosscheck.superseded_crew_lists(conn, self.docs, all_fields, voyage)) - self.suspect
        self.fields = [f for f in db.rows(conn, "SELECT * FROM extracted_fields WHERE voyage_id=? AND status!='EXCLUDED' ORDER BY record_index, id",
                                          (voyage_id,)) if f["document_id"] not in self.suspect and f["document_id"] not in self.superseded]
        self.opts = _opts(conn, voyage_id)
        self.voyage = db.row(conn, "SELECT * FROM voyages WHERE id=?", (voyage_id,)) or {}
        self.auto_codes = {}

    def dtype(self, f):
        d = self.docs.get(f["document_id"])
        return d["doc_type"] if d else "MANUAL"

    def header(self, key, types):
        out = []
        for t in types:
            out += [f for f in self.fields if f["section"] == "vessel" and f["record_key"] == "header" and f["field_key"] == key
                    and self.dtype(f) == t and (f["value"] or "").strip()]
        return out

    def records(self, section, types=None):
        recs = defaultdict(dict)
        order = {}
        for f in self.fields:
            if f["section"] == section and (types is None or self.dtype(f) in types):
                k = (f["document_id"] or 0, f["record_key"])
                recs[k][f["field_key"]] = f
                order.setdefault(k, (f["document_id"] or 10 ** 9, f["record_index"]))
        return [recs[k] for k in sorted(recs, key=lambda k: order[k])]

    def _same_port_code(self, raw):
        """'LONG AN PORT, VIETNAM' is not precise enough for the UN/LOCODE list, but another document of this voyage
        names the same port precisely ('Cảng Quốc tế Long An' = VNLAP): use that code when exactly one code results."""
        from .crosscheck import _cmp_port
        names = {f["value"] for f in self.fields if f["field_key"] in PORT_KEYS and f["value"]}
        if self.voyage.get("port_of_arrival"):
            names.add(self.voyage["port_of_arrival"])
        codes = set()
        for other in names:
            if other != raw and _cmp_port(raw, other):
                oc = _locode(other) or N.suggest_locode(other)
                if oc:
                    codes.add(oc)
        return codes.pop() if len(codes) == 1 else None

    def code(self, kind, raw):
        if not raw:
            return None, True
        ov = self.opts.get(f"code:{kind}:{N.norm_text(raw)}")
        if ov:
            return ov, True
        fn = {"rank": N.suggest_rank, "state": N.suggest_state, "gender": N.suggest_gender, "package": N.suggest_package}.get(kind)
        if fn:
            c = fn(raw)
            return (c, True) if c else (raw, False)
        if kind == "unit":
            c = N.unit_code(raw)
            if c and (c in N.CODES["units"] or not N.CODES["units"]):
                return c, True
            return raw, False
        if kind == "locode":
            c = _locode(raw) or (raw.strip().upper() if re.fullmatch(r"[A-Za-z]{2}[A-Za-z2-9]{3}", raw.strip()) else None)
            if not c:
                # port written in words: look it up in the UN/LOCODE seaport list (only an unambiguous match)
                c = N.suggest_locode(raw) or self._same_port_code(raw)
                if c:
                    self.auto_codes[(kind, raw)] = c
            return (c, True) if c else (raw, False)
        return raw, True


def _set(plan, sheet, ref, value, label, sources, kind):
    plan.cells[(sheet, ref)] = value
    plan.prov[(sheet, ref)] = {"label": label, "sources": sources, "kind": kind}


def _src(f, data):
    d = data.docs.get(f["document_id"])
    return {"field_id": f["id"], "doc": d["original_name"] if d else "Nhập tay", "page": f["page_no"], "status": f["status"],
            "original": f["original_value"], "value": f["value"]}


def build_plan(conn, voyage_id):
    data = Data(conn, voyage_id)
    plan = Plan()
    o = data.opts
    # ------------------------------------------------ header cells
    present = {d["doc_type"] for d in data.docs.values()}
    for sheet, (rows, types) in SHEET_HEADERS.items():
        if sheet in ONLY_IF_DOC and ONLY_IF_DOC[sheet] not in present:
            continue
        for ref, label, spec in rows:
            manual = o.get(f"cell:{sheet}!{ref}")
            if manual:
                _set(plan, sheet, ref, manual, label, [{"doc": "Nhân viên nhập", "status": "CONFIRMED"}], "manual")
                continue
            kind, *rest = spec.split(":")
            if kind == "opt":
                v = o.get(rest[0]) or ""
                if v:
                    _set(plan, sheet, ref, v, label, [{"doc": "Tùy chọn xuất file", "status": "CONFIRMED"}], "option")
                else:
                    plan.empty.append(f"{sheet}!{ref} - {label}")
            elif kind == "docs":
                types_ = rest[0].split("|")
                v = "1" if any(t in present for t in types_) else "0"
                _set(plan, sheet, ref, v, label, [{"doc": "Có chứng từ tương ứng trong bộ hồ sơ" if v == "1" else "Không có chứng từ tương ứng",
                                                  "status": "DERIVED"}], "derived")
            elif kind == "voyage":
                v = (data.voyage.get(rest[0]) or "").strip()
                if v:  # e.g. the notes typed when the voyage was created
                    _set(plan, sheet, ref, v, label, [{"doc": "Hồ sơ chuyến tàu (ghi chú khi tạo chuyến)", "status": "CONFIRMED"}], "voyage")
                else:
                    plan.empty.append(f"{sheet}!{ref} - {label} (ghi chú của hồ sơ chuyến đang trống)")
            elif kind == "manual":
                plan.empty.append(f"{sheet}!{ref} - {label} (không có trong chứng từ - nhập tay nếu cần)")
            elif kind == "src":
                key, tr = rest[0], (rest[1] if len(rest) > 1 else None)
                fs = data.header(key, types)
                if not fs:  # not in the main documents of this sheet: take it from any other declaration that states it
                    skip = ("MANUAL",) if key in OPERATION_KEYS else ("OTHER", "REFERENCE", "MANUAL")  # port-call facts: SOF, berthing plan...
                    others = [t for t in {data.dtype(f) for f in data.fields} if t not in types and t not in skip]
                    fs = data.header(key, sorted(others))
                if not fs and key in ROB_ARTICLES:
                    fs = _rob_from_stores(data, key)  # quantity on board from the Ship's Stores Declaration
                if not fs:
                    plan.empty.append(f"{sheet}!{ref} - {label} (Not Available in Source)")
                    continue
                vals = {}
                for f in fs:
                    v = f["value"]
                    if tr == "num":
                        v = _num(v)
                    elif tr == "date":
                        v = N.parse_date(v)[0] or v
                    elif tr == "locode":
                        v, ok = data.code("locode", v)
                        if not ok:
                            plan.warnings.append(f"{sheet}!{ref} ({label}): '{v}' chưa có mã cảng UN/LOCODE - đã ghi nguyên văn, chọn mã ở mục Ánh xạ mã.")
                            plan.unmapped_codes = getattr(plan, "unmapped_codes", set()) | {("locode", v)}
                    elif tr == "level":
                        m = re.search(r"[123]", v or "")
                        v = m.group(0) if m else v
                    vals.setdefault(N.norm_text(v), (v, f))
                if len(vals) > 1 and key in OPERATION_KEYS:
                    # port-call facts written in several documents (plan, notice, SOF): the first source in priority order is used
                    first = next(iter(vals.values()))
                    plan.warnings.append(f"{sheet}!{ref} ({label}): các chứng từ ghi khác nhau - đã dùng '{first[0]}' "
                                         f"({data.docs[first[1]['document_id']]['original_name']}); giá trị khác: "
                                         + " / ".join(f"'{v}'" for v, _ in list(vals.values())[1:]) + ". Sửa ở mục 'Giá trị nhập tay' nếu cần.")
                    vals = {"_": first}
                if len(vals) > 1:
                    plan.blockers.append(f"{sheet}!{ref} ({label}): các chứng từ ghi khác nhau: " +
                                         " / ".join(f"'{v}' ({data.docs[f['document_id']]['original_name']})" for v, f in vals.values()) +
                                         " - sửa cho thống nhất hoặc nhập giá trị tại mục 'Giá trị nhập tay'.")
                    continue
                v, f = next(iter(vals.values()))
                for ff in fs:
                    plan.used_fields.add(ff["id"])
                _set(plan, sheet, ref, v, label, [_src(ff, data) for ff in fs], "source")
    # ------------------------------------------------ list tables
    _crew(plan, data)
    _effects(plan, data)
    _stores(plan, data)
    _passengers(plan, data)
    _goods(plan, data)
    _house_bls(plan, data)
    _dg(plan, data)
    _dg_transporter_note(plan)
    _empty_containers(plan, data)
    _port_calls(plan, data)
    # derived header values for Goods Declaration
    rows = plan.tables.get("Goods Declaration", [])
    if rows:
        pk = [N.parse_number(r.get("_packages"))[0] for r in rows]
        if all(p is not None for p in pk) and not o.get("cell:Goods Declaration!B6"):
            _set(plan, "Goods Declaration", "B6", N.fmt_number(sum(pk)), "Tổng số kiện (cộng các dòng)", [{"doc": "Tính tổng từ các dòng hàng", "status": "DERIVED"}], "derived")
        kinds = {r.get("_kind_code") for r in rows}
        if len(kinds) == 1 and None not in kinds and not o.get("cell:Goods Declaration!B7"):
            _set(plan, "Goods Declaration", "B7", kinds.pop(), "Loại kiện (mã)", [{"doc": "Mã loại kiện chung của các dòng", "status": "DERIVED"}], "derived")
        elif not o.get("cell:Goods Declaration!B7"):
            plan.empty.append("Goods Declaration!B7 - Loại kiện: các dòng có nhiều loại kiện khác nhau → nhập tay")
    for sheet, cell in DOC_FUNCTION_CELLS.items():
        if cell and o.get("doc_function"):
            _set(plan, sheet, cell, o["doc_function"], "Chức năng của chứng từ", [{"doc": "Tùy chọn xuất file", "status": "CONFIRMED"}], "option")
    plan.auto_codes = dict(data.auto_codes)
    return plan, data


def _row(plan, sheet, values, fields, data, extra=None):
    row = {k: v for k, v in values.items() if v not in (None, "")}
    if extra:
        row.update(extra)
    plan.tables.setdefault(sheet, []).append(row)
    plan.table_prov.setdefault(sheet, []).append([_src(f, data) for f in fields if f])
    for f in fields:
        if f:
            plan.used_fields.add(f["id"])


def _names(rec, opt):
    fam, giv, full = rec.get("family_name"), rec.get("given_name"), rec.get("full_name")
    if fam or giv:
        return (fam or {}).get("value"), (giv or {}).get("value"), [fam, giv]
    if not full:
        return None, None, []
    name = full["value"].strip()
    parts = name.split()
    if opt == "last_word_given" and len(parts) > 1:
        return " ".join(parts[:-1]), parts[-1], [full]
    if opt == "dash_family" or opt not in NAME_SPLITS:
        return "-", name, [full]
    if opt == "first_word_family" and len(parts) > 1:
        return parts[0], " ".join(parts[1:]), [full]
    return name, name, [full]


def _v(rec, k):
    return (rec.get(k) or {}).get("value")


AS_WRITTEN = {("rank", None), ("unit", "Ship's store declaration")}  # SGCL: written exactly as in the documents, no code mapping


def _coded(plan, data, sheet, kind, raw, label):
    if (kind, None) in AS_WRITTEN or (kind, sheet) in AS_WRITTEN:
        ov = data.opts.get(f"code:{kind}:{N.norm_text(raw)}") if raw else None
        return ov or raw
    code, ok = data.code(kind, raw)
    if raw and not ok:
        plan.warnings.append(f"{sheet}: '{raw}' chưa ánh xạ được sang mã NSW ({label}) - đã ghi nguyên văn, cần chọn mã ở mục Ánh xạ mã.")
        plan.unmapped_codes = getattr(plan, "unmapped_codes", set()) | {(kind, raw)}
    return code


def _crew(plan, data):
    sheet = "Crew list"
    for rec in data.records("crew"):
        fam, giv, nf = _names(rec, data.opts.get("name_split"))
        _row(plan, sheet, {
            "A": fam, "B": giv, "C": _coded(plan, data, sheet, "rank", _v(rec, "rank"), "chức danh"),
            "D": _coded(plan, data, sheet, "state", _v(rec, "nationality"), "quốc tịch"), "E": _v(rec, "dob"), "F": _v(rec, "pob"),
            "G": data.opts.get("crew_passport_type") or None, "H": _v(rec, "passport_no"), "I": _v(rec, "passport_expiry"),
            "J": _coded(plan, data, sheet, "gender", _v(rec, "gender"), "giới tính"),
        }, nf + [rec.get(k) for k in ("rank", "nationality", "dob", "pob", "passport_no", "passport_expiry", "gender")], data)


def _effects(plan, data):
    sheet = "Crew's Effects Declaration"
    for rec in data.records("effects"):
        fam, giv, nf = _names(rec, data.opts.get("name_split"))
        _row(plan, sheet, {"A": fam, "B": giv, "C": _coded(plan, data, sheet, "rank", _v(rec, "rank"), "chức danh"), "D": N.nil_if_nothing(_v(rec, "effects"))},
             nf + [rec.get("rank"), rec.get("effects")], data)


def _stores(plan, data):
    sheet = "Ship's store declaration"
    for rec in data.records("store"):
        q, u = N.parse_number(_v(rec, "quantity"))
        if u and not _v(rec, "unit"):  # the unit exactly as written after the number ("Chai", "Cây", "Lít")
            m = re.search(r"\d\s*([^\W\d_][^\W_]*³?)", _v(rec, "quantity") or "")
            u = m.group(1) if m else u
        unit_raw = _v(rec, "unit") or u
        _row(plan, sheet, {"A": _v(rec, "article"), "B": N.fmt_number(q) if q is not None else _v(rec, "quantity"),
                           "C": _coded(plan, data, sheet, "unit", unit_raw, "đơn vị tính"), "D": _v(rec, "location")},
             [rec.get(k) for k in ("article", "quantity", "unit", "location")], data)


def _passengers(plan, data):
    sheet = "Passenger list"
    for rec in data.records("passenger"):
        fam, giv, nf = _names(rec, data.opts.get("name_split"))
        _row(plan, sheet, {"A": fam, "B": giv, "C": _coded(plan, data, sheet, "state", _v(rec, "nationality"), "quốc tịch"),
                           "D": _v(rec, "dob"), "E": _v(rec, "pob"), "F": data.opts.get("passenger_passport_type") or None,
                           "G": _v(rec, "passport_no"), "H": _v(rec, "passport_expiry"),
                           "I": _coded(plan, data, sheet, "locode", _v(rec, "port_embark"), "cảng lên tàu"),
                           "J": _coded(plan, data, sheet, "locode", _v(rec, "port_disembark"), "cảng rời tàu"),
                           "L": _coded(plan, data, sheet, "gender", _v(rec, "gender"), "giới tính")},
             nf + [rec.get(k) for k in ("nationality", "dob", "pob", "passport_no", "passport_expiry", "port_embark", "port_disembark", "gender")], data)


def _unit_of(rec, key):
    v = _v(rec, key)
    _, u = N.parse_number(v)
    return u or _v(rec, key + "_unit")


def _goods(plan, data):
    sheet = "Goods Declaration"
    recs = data.records("cargo", ["CARGO_MANIFEST", "MANUAL"])
    if not recs:
        recs = data.records("cargo", ["BILL_OF_LADING"])
        if recs:
            plan.warnings.append("Goods Declaration: không có Cargo Manifest - dữ liệu lấy từ các B/L.")
    missing_ct = []
    for rec in recs:
        cont = _v(rec, "container_no")
        if cont and "," in cont:
            plan.warnings.append(f"Goods Declaration: B/L {_v(rec, 'bl_no')} có nhiều container trên 1 dòng ({cont}) - NSW yêu cầu 1 container/dòng, cần kiểm tra.")
        kind = _coded(plan, data, sheet, "package", _v(rec, "package_kind"), "loại kiện") if _v(rec, "package_kind") else None
        gwu = _unit_of(rec, "gross_weight")
        mu = _unit_of(rec, "measurement")
        _row(plan, sheet, {
            "A": _v(rec, "bl_no"), "B": _v(rec, "shipper"), "C": _v(rec, "consignee"), "D": _v(rec, "notify"),
            "F": cont, "G": _v(rec, "seal_no"), "H": _v(rec, "hs_code"), "I": _v(rec, "description"),
            "J": _num(_v(rec, "net_weight")) if _v(rec, "net_weight") else None, "K": _num(_v(rec, "gross_weight")) if _v(rec, "gross_weight") else None,
            "L": _num(_v(rec, "measurement")) if _v(rec, "measurement") else None,
            "O": _coded(plan, data, sheet, "unit", gwu, "đơn vị trọng lượng") if gwu else None,
            "P": _coded(plan, data, sheet, "locode", _v(rec, "pod"), "cảng dỡ hàng"),
            "R": _coded(plan, data, sheet, "locode", _v(rec, "pol"), "cảng xếp hàng"),
            "V": _ctype(plan, rec, missing_ct),
            "W": _coded(plan, data, sheet, "unit", mu, "đơn vị thể tích") if mu else None,
        }, [rec.get(k) for k in ("bl_no", "shipper", "consignee", "notify", "container_no", "container_type", "seal_no", "hs_code", "description",
                                 "net_weight", "gross_weight", "measurement", "pod", "pol", "gross_weight_unit", "measurement_unit")], data,
            extra={"_packages": _v(rec, "packages"), "_kind_code": kind})
    if missing_ct:
        plan.warnings.append(f"Goods Declaration cột V 'Loại cont' (bắt buộc): {len(missing_ct)} dòng chưa có loại container "
                             f"(B/L {', '.join(missing_ct[:8])}{'…' if len(missing_ct) > 8 else ''}) → chọn tại Kiểm tra và xác nhận › tab Hàng hóa.")


HOUSE_SHEET = "List of House bill of lading"
HOUSE_BLOCK = (4, 5)  # one block per B/L: row 4 B/L data, 5 lookups, 6 goods headings, 7 goods, 8 spacing


def _house_bls(plan, data):
    """Every B/L of the voyage is one block of 'List of House bill of lading' (SGCL fills ordinary B/Ls here too,
    the B/L number being both house and master number) - B/L documents first, the manifest line completes them."""
    by_bl, order = {}, []
    for src in (data.records("cargo", ["BILL_OF_LADING"]), data.records("cargo", ["CARGO_MANIFEST", "MANUAL"])):
        for rec in src:
            k = N.norm_id(_v(rec, "bl_no"))
            if not k:
                continue
            if k not in by_bl:
                by_bl[k] = {}
                order.append(k)
            for f, v in rec.items():
                by_bl[k].setdefault(f, v)  # the B/L wins, the manifest fills what the B/L does not state
    o = data.opts
    plan.house_goods = []
    for i, k in enumerate(order, start=1):
        rec = by_bl[k]
        gwu = _unit_of(rec, "gross_weight")
        bulk = re.search(r"\bBULK\b|H[AÀ]NG\s+R[OỜ]I", N.strip_accents(" ".join(_v(rec, x) or "" for x in ("description", "packages", "package_kind"))).upper()) \
            or re.search(r"HANG\s+ROI", N.strip_accents(" ".join(_v(rec, x) or "" for x in ("description", "packages"))).upper())
        kind_raw = _v(rec, "package_kind") or ("BULK" if bulk else None)
        pod = _coded(plan, data, HOUSE_SHEET, "locode", _v(rec, "pod"), "cảng dỡ hàng")
        _row(plan, HOUSE_SHEET, {
            "A": i, "C": o.get("doc_year"), "D": o.get("doc_function"),
            "E": _v(rec, "shipper"), "F": _v(rec, "consignee"), "G": _v(rec, "notify"),
            "J": pod, "K": _coded(plan, data, HOUSE_SHEET, "locode", _v(rec, "pol"), "cảng xếp hàng"), "L": pod,
            "M": _v(rec, "place_of_delivery") or _v(rec, "pod"),
            "O": _v(rec, "bl_no"), "P": _v(rec, "date_of_bl"), "Q": _v(rec, "bl_no"), "R": _v(rec, "date_of_bl"), "S": _v(rec, "date_of_bl"),
            "T": _pkg_count(_v(rec, "packages")) or ("0" if bulk else None),
            "U": _coded(plan, data, HOUSE_SHEET, "package", kind_raw, "loại kiện") if kind_raw else None,
            "V": _num(_v(rec, "gross_weight")) if _v(rec, "gross_weight") else None,
            "W": _coded(plan, data, HOUSE_SHEET, "unit", gwu, "đơn vị trọng lượng") if gwu else None,
        }, [rec.get(x) for x in ("bl_no", "shipper", "consignee", "notify", "pod", "pol", "place_of_delivery", "date_of_bl", "packages",
                                 "package_kind", "gross_weight")], data)
        plan.house_goods.append({k2: v for k2, v in {
            "B": _v(rec, "hs_code"), "C": _v(rec, "description"),
            "D": _num(_v(rec, "gross_weight")) if _v(rec, "gross_weight") else None,
            "E": _num(_v(rec, "measurement")) if _v(rec, "measurement") else None,
            "F": _v(rec, "container_no"), "G": _v(rec, "seal_no")}.items() if v not in (None, "")})
        for x in ("description", "hs_code", "measurement", "container_no", "seal_no"):
            if rec.get(x):
                plan.used_fields.add(rec[x]["id"])
    if order and "N" not in (plan.tables[HOUSE_SHEET][0]):
        plan.empty.append(f"{HOUSE_SHEET}!N - Loại hàng (Cargo Type): chứng từ không ghi mã loại hàng NSW → nhập tay nếu cần")


ROB_ARTICLES = {
    "rob_do": r"\bD\.?O\b|DIESEL|\bMGO\b|GAS\s*OIL|DAU\s+DO\b",
    "rob_fo": r"\bF\.?O\b|FUEL\s+OIL|\bIFO\b|\bHFO\b|VLSFO|DAU\s+(NHIEN\s+LIEU|FO)\b",
    "rob_fw": r"FRESH\s+WATER|\bF\.?W\b|NUOC\s+NGOT",
}


def _rob_from_stores(data, key):
    """ROB DO / FO / FW = quantity of the matching article of the Ship's Stores Declaration (only one matching line)."""
    hits = []
    for rec in data.records("store"):
        art = N.strip_accents(_v(rec, "article") or "").upper()
        if re.search(ROB_ARTICLES[key], art) and not (key == "rob_fo" and re.search(r"LUB|NHON", art)) and rec.get("quantity"):
            hits.append(rec["quantity"])
    return hits if len(hits) == 1 else []


def _pkg_count(v):
    """Number of packages only when it is a count ('1,200 BAGS'), not a weight/volume ('5,800 MT IN BULK')."""
    q, u = N.parse_number(v)
    if q is None or (u and re.fullmatch(r"(MTS?|TNE|TONS?|T|KGS?|KGM|LBS?|M3|M³|CBM|MTQ|L|LTRS?|LÍT|LIT)", u.upper())):
        return None
    return N.fmt_number(q)


def _ctype(plan, rec, missing):
    v = _v(rec, "container_type")
    valid = N.CODES["container_types"] or ["Container 20", "Container 40", "Container 45", "Other"]
    if v in valid:
        return v
    if v:
        plan.warnings.append(f"Goods Declaration: B/L {_v(rec, 'bl_no')} có loại container '{v}' (nhiều loại trên 1 dòng hoặc không đúng danh mục) "
                             "→ cần chọn một loại tại Kiểm tra và xác nhận.")
        missing.append(_v(rec, "bl_no") or "?")
        return None
    return "Other"  # no container type in the documents (bulk cargo...): SGCL writes 'Other'


def _dg(plan, data):
    sheet = "Dangerous goods manifest"
    for rec in data.records("dg"):
        _row(plan, sheet, {
            "A": _v(rec, "bl_no"), "B": _v(rec, "marks"), "C": _num(_v(rec, "packages")) if _v(rec, "packages") else None,
            "D": _coded(plan, data, sheet, "package", _v(rec, "package_kind"), "loại kiện") if _v(rec, "package_kind") else None,
            # new NSW template: column E = "Cty vận chuyển / Transporter's name" (no proper-shipping-name column any more)
            "E": _v(rec, "transporter"), "F": _v(rec, "imdg_class"), "G": re.sub(r"\D", "", _v(rec, "un_no") or "") or None,
            "H": _v(rec, "packing_group"), "I": _v(rec, "subsidiary_risk"), "J": _v(rec, "flash_point"), "K": _v(rec, "marine_pollutant"),
            "L": _num(_v(rec, "gross_weight")) if _v(rec, "gross_weight") else None, "M": _v(rec, "stowage"),
            "N": _v(rec, "container_no"), "O": _v(rec, "seal_no"),
        }, [rec.get(k) for k in ("bl_no", "marks", "packages", "package_kind", "transporter", "imdg_class", "un_no", "packing_group",
                                 "subsidiary_risk", "flash_point", "marine_pollutant", "gross_weight", "stowage", "container_no", "seal_no")], data)


# ======================================================================== readiness
def readiness(conn, voyage_id):
    plan, data = build_plan(conn, voyage_id)
    blockers = list(plan.blockers)
    last = db.row(conn, "SELECT * FROM crosscheck_runs WHERE voyage_id=? ORDER BY id DESC LIMIT 1", (voyage_id,))
    if not data.docs:
        blockers.append("Chưa có chứng từ nào được tải lên.")
    if not last:
        blockers.append("Chưa chạy đối chiếu dữ liệu.")
    else:
        changed = db.row(conn, "SELECT MAX(updated_at) m FROM extracted_fields WHERE voyage_id=?", (voyage_id,))["m"]
        if changed and changed > last["run_at"]:
            blockers.append("Dữ liệu đã được chỉnh sửa sau lần đối chiếu gần nhất - cần chạy lại đối chiếu.")
        for r in db.rows(conn, "SELECT * FROM crosscheck_results WHERE voyage_id=? AND blocking=1", (voyage_id,)):
            blockers.append(f"[{r['status']}] {r['message']}")
    unconf = [f for f in data.fields if f["id"] in plan.used_fields and f["status"] != "CONFIRMED"]
    for did in data.suspect:
        plan.warnings.append(f"Chứng từ '{data.docs[did]['original_name']}' nghi thuộc chuyến khác - dữ liệu của nó KHÔNG được đưa vào file Excel "
                             "cho tới khi nhân viên xác nhận đúng hồ sơ.")
    # extracted data that has no cell in the NSW template (kept for cross-check / reference)
    unmapped = defaultdict(lambda: {"count": 0, "docs": set()})
    for f in data.fields:
        if f["id"] in plan.used_fields or f["field_key"] in ("seq",):
            continue
        u = unmapped[f["field_key"]]
        u["count"] += 1
        u["label"] = f["field_label"] or f["field_key"]
        u["docs"].add(data.docs[f["document_id"]]["original_name"] if f["document_id"] in data.docs else "Nhập tay")
    if unconf:
        blockers.append(f"Còn {len(unconf)} trường dữ liệu sẽ xuất ra Excel chưa được nhân viên xác nhận.")
    return {"ready": not blockers, "blockers": blockers, "warnings": plan.warnings, "empty": plan.empty,
            "unconfirmed_count": len(unconf), "plan": plan_view(plan),
            "unmapped_fields": sorted(({"field": k, "label": v["label"], "count": v["count"], "docs": sorted(v["docs"])[:5]}
                                       for k, v in unmapped.items()), key=lambda x: x["label"])}


def plan_view(plan):
    cells = [{"sheet": s, "cell": r, "value": v, **plan.prov[(s, r)]} for (s, r), v in plan.cells.items()]
    tables = {s: {"rows": [{k: v for k, v in row.items() if not k.startswith("_")} for row in rows], "sources": plan.table_prov.get(s, [])}
              for s, rows in plan.tables.items()}
    unmapped = sorted({f"{k}|{v}" for k, v in getattr(plan, "unmapped_codes", set())})
    auto = sorted(f"{k}|{v}|{code}" for (k, v), code in getattr(plan, "auto_codes", {}).items())
    return {"cells": cells, "tables": tables, "unmapped_codes": unmapped, "auto_codes": auto}


# ======================================================================== write + verify
def _regions(sheet):
    regs = []
    rows, _ = SHEET_HEADERS.get(sheet, ([], []))
    for ref, _, _ in rows:
        regs.append((ref, ref))
    for r in CLEAR_ONLY.get(sheet, []):
        a, b = r.split(":")
        regs.append((a, b))
    cell = DOC_FUNCTION_CELLS.get(sheet)
    if cell:
        regs.append((cell, cell))
    return regs


def write_workbook(template, plan, out_path):
    book = Book(template)
    written = {}
    for sheet in book.sheet_names:
        if sheet == "Declaration list":
            continue  # reference code lists - never modified
        sh = book.sheet(sheet)
        for a, b in _regions(sheet):
            sh.clear_range(f"{a}:{b}")
        spec = TABLES.get(sheet)
        if spec:
            rows = plan.tables.get(sheet, [])
            c1, c2 = spec["cols"].split(":")
            # clear sample values in the template rows first, then rebuild the list rows
            sh.clear_range(f"{c1}{spec['first']}:{c2}{spec['old_last']}")
            sh.regenerate_rows(spec["first"], spec["first"], spec["old_last"], max(1, len(rows)), max_row=spec.get("max_row"))
            for i, row in enumerate(rows):
                r = spec["first"] + i
                for col, v in row.items():
                    if col.startswith("_"):
                        continue
                    sh.set(f"{col}{r}", v)
                    written[(sheet, f"{col}{r}")] = str(v)
    blocks = plan.tables.get(HOUSE_SHEET, [])
    if blocks and HOUSE_SHEET in book.sheet_names:
        sh = book.sheet(HOUSE_SHEET)
        b0, bh = HOUSE_BLOCK
        heads = {col: sh.value(f"{col}{b0 + 2}") for col in "BCDEFG"}  # goods headings of the block (cleared by the copy)
        sh.regenerate_rows(b0, b0, b0 + bh - 1, len(blocks), block=HOUSE_BLOCK)
        goods = getattr(plan, "house_goods", [])
        for i, row in enumerate(blocks):
            top = b0 + i * bh
            for col, v in heads.items():
                if v:
                    sh.set(f"{col}{top + 2}", v)
                    written[(HOUSE_SHEET, f"{col}{top + 2}")] = str(v)  # headings of the repeated block, not left-over data
            for col, v in row.items():
                if not col.startswith("_"):
                    sh.set(f"{col}{top}", v)
                    written[(HOUSE_SHEET, f"{col}{top}")] = str(v)
            for col, v in (goods[i] if i < len(goods) else {}).items():
                sh.set(f"{col}{top + 3}", v)
                written[(HOUSE_SHEET, f"{col}{top + 3}")] = str(v)
    for (sheet, ref), v in plan.cells.items():
        book.sheet(sheet).set(ref, v)
        written[(sheet, ref)] = str(v)
    book.save(out_path)
    return written


def _cells(book, sheet):
    from .xlsxpatch import Q
    sh = book.sheet(sheet)
    out = {}
    for row in sh.sheetData.findall(Q("row")):
        for c in row.findall(Q("c")):
            f = c.find(Q("f"))
            out[c.get("r")] = ("F", f.text) if f is not None else ("V", book.cell_text(c))
    return out


def verify(template, out_path, written):
    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    # 1. file opens
    try:
        import openpyxl
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(out_path)
        add("Mở được file bằng thư viện Excel (openpyxl)", True)
    except Exception as e:  # pragma: no cover
        add("Mở được file bằng thư viện Excel (openpyxl)", False, str(e))
        return checks
    tb, ob = Book(template), Book(out_path)
    # 2. sheets
    add("Đủ sheet, đúng tên và thứ tự", tb.sheet_names == ob.sheet_names, f"{len(ob.sheet_names)} sheet")
    add("Giữ trạng thái ẩn/hiện của sheet", tb.sheet_state == ob.sheet_state)
    # 3. values in place
    bad = [f"{s}!{r}" for (s, r), v in written.items() if (ob.sheet(s).value(r) or "") != v]
    add("Dữ liệu được ghi đúng vị trí ô", not bad, ", ".join(bad[:10]))
    # 4. formulas, validations, comments preserved
    lost, residual = [], []
    last_row = {}
    for (s_, r_) in written:
        last_row[s_] = max(last_row.get(s_, 0), split_ref(r_)[1])
    for s in tb.sheet_names:
        tc, oc = _cells(tb, s), _cells(ob, s)
        spec = TABLES.get(s)
        regs = _regions(s)
        for ref, (kind, val) in tc.items():
            col, rn = split_ref(ref)
            in_table = spec and spec["first"] <= rn <= spec["old_last"]
            if kind == "F" and not in_table and oc.get(ref) != ("F", val):
                lost.append(f"{s}!{ref}")
        for ref, (kind, val) in oc.items():
            if kind != "V" or val in (None, ""):
                continue
            if (s, ref) in written:
                continue
            col, rn = split_ref(ref)
            in_region = any(col2num(split_ref(a)[0]) <= col2num(col) <= col2num(split_ref(b)[0]) and split_ref(a)[1] <= rn <= split_ref(b)[1] for a, b in regs)
            in_table = spec and spec["first"] <= rn <= max(spec["old_last"], last_row.get(s, 0)) and col2num(col) <= col2num(spec["cols"].split(":")[1])
            if in_region or in_table or tc.get(ref) != ("V", val):
                residual.append(f"{s}!{ref}={val}")
        if spec:
            tpl_f = sum(1 for ref, (k, _) in tc.items() if k == "F" and split_ref(ref)[1] == spec["first"])
            rows_out = {split_ref(ref)[1] for ref in oc if split_ref(ref)[1] >= spec["first"]}
            out_f = sum(1 for ref, (k, _) in oc.items() if k == "F" and split_ref(ref)[1] >= spec["first"])
            if tpl_f and out_f < tpl_f:
                lost.append(f"{s}: công thức dòng dữ liệu")
    add("Giữ nguyên công thức của mẫu", not lost, ", ".join(lost[:10]))
    add("Không còn dữ liệu mẫu / chuyến tàu cũ", not residual, ", ".join(residual[:15]))
    tx = sum(tb.parts[p].count(b"<x14:dataValidation ") for p in tb.parts if p.startswith("xl/worksheets/sheet"))
    ox = sum(ob.parts[p].count(b"<x14:dataValidation ") for p in ob.parts if p.startswith("xl/worksheets/sheet"))
    tdv = sum(tb.parts[p].count(b"<dataValidation ") for p in tb.parts if p.startswith("xl/worksheets/sheet"))
    odv = sum(ob.parts[p].count(b"<dataValidation ") for p in ob.parts if p.startswith("xl/worksheets/sheet"))
    add("Giữ danh sách chọn (Data Validation, kể cả x14)", tx == ox and tdv == odv, f"x14: {ox}/{tx}, thường: {odv}/{tdv}")
    tcm = sorted(p for p in tb.parts if p.startswith("xl/comments") or p.startswith("xl/externalLinks") or p.startswith("xl/styles"))
    add("Giữ styles, ghi chú (comments), liên kết ngoài", tcm == sorted(p for p in ob.parts if p in tcm) and all(ob.parts[p] == tb.parts[p] for p in tcm))
    add("Sheet danh mục 'Declaration list' không bị thay đổi",
        ob.parts[ob.sheet_paths["Declaration list"]] == tb.parts[tb.sheet_paths["Declaration list"]])
    # 5. real spreadsheet application
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice and os.environ.get("SGCL_SKIP_LIBREOFFICE") != "1":
        with tempfile.TemporaryDirectory() as td:
            try:
                r = subprocess.run([soffice, "--headless", f"-env:UserInstallation=file://{td}/profile", "--convert-to", "csv",
                                    "--outdir", td, out_path], capture_output=True, timeout=120)
                ok = any(f.endswith(".csv") for f in os.listdir(td))
                add("Mở được bằng LibreOffice (kiểm tra độc lập)", ok, "" if ok else r.stderr.decode()[-300:])
            except Exception as e:
                add("Mở được bằng LibreOffice (kiểm tra độc lập)", False, str(e))
    return checks


def _dg_transporter_note(plan):
    if plan.tables.get("Dangerous goods manifest") and not any(r.get("E") for r in plan.tables["Dangerous goods manifest"]):
        plan.warnings.append("Dangerous goods manifest cột E 'Cty vận chuyển' (bắt buộc): chứng từ không ghi → để trống, cần bổ sung.")


def _empty_containers(plan, data):
    sheet = "Empty Container"
    for rec in data.records("empty_container"):
        ct = _v(rec, "container_type")
        valid = N.CODES["container_types"] or ["Container 20", "Container 40", "Container 45", "Other"]
        _row(plan, sheet, {"A": _v(rec, "bl_no"), "B": _v(rec, "container_no"), "C": ct if ct in valid else None,
                           "D": _coded(plan, data, sheet, "locode", _v(rec, "pod"), "cảng dỡ hàng")},
             [rec.get(k) for k in ("bl_no", "container_no", "container_type", "pod")], data)
        if not ct or ct not in valid:
            plan.warnings.append(f"Empty Container: container {_v(rec, 'container_no')} chưa có loại cont 20/40/45 → chọn tại Kiểm tra và xác nhận.")


def _port_calls(plan, data):
    """Declaration For Ship Security rows 25-34: the last 10 port calls (most recent kept when the document lists more)."""
    sheet = "Declaration For Ship Security"
    recs = data.records("port_calls")
    if len(recs) > 10:
        plan.warnings.append(f"Ship Security: chứng từ có {len(recs)} cảng ghé, mẫu NSW chỉ có 10 dòng → ghi 10 dòng cuối danh sách, kiểm tra thứ tự.")
        recs = recs[-10:]
    for rec in recs:
        lvl = re.search(r"[123]", _v(rec, "security_level") or "")
        code = _coded(plan, data, sheet, "locode", _v(rec, "port_code") or _v(rec, "port_name"), "mã cảng")
        _row(plan, sheet, {"A": code, "B": _v(rec, "port_name"), "C": _v(rec, "arrival"), "D": _v(rec, "departure"),
                           "E": lvl.group(0) if lvl else None},
             [rec.get(k) for k in ("port_code", "port_name", "arrival", "departure", "security_level")], data)
