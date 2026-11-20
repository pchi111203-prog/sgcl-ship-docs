"""Document classification and rule-based field extraction.

Approach (no paid API needed):
  1. Classify a document from its *content* (keyword scoring, title lines weighted).
  2. Header fields: label dictionary -> value found after the label on the same line,
     or on the next line / aligned column when the label is a column header.
  3. Lists (crew, cargo lines, DG, stores...): table header detection with synonym
     matching, then every following row is kept (multi-page tables are continued).
Every value keeps document id, page number, extraction method and a confidence score.
Nothing is invented: when a label/value is not found, no field is produced.
"""
import re

from . import normalize as N

DOC_TYPES = {
    "GENERAL_DECLARATION": "General Declaration (Bản khai chung)",
    "NOTICE_OF_ARRIVAL": "Notice of Arrival (Thông báo tàu đến)",
    "TONNAGE_CERTIFICATE": "Tonnage Certificate (GCN dung tích)",
    "CARGO_MANIFEST": "Cargo Manifest (Bản lược khai hàng hóa)",
    "BILL_OF_LADING": "Bill of Lading (Vận đơn)",
    "CREW_LIST": "Crew List (Danh sách thuyền viên)",
    "PASSENGER_LIST": "Passenger List (Danh sách hành khách)",
    "DG_MANIFEST": "Dangerous Goods Manifest (Bản khai hàng nguy hiểm)",
    "CREW_EFFECTS": "Crew's Effects Declaration (Bản khai hành lý thuyền viên)",
    "SHIP_STORES": "Ship's Stores Declaration (Bản khai dự trữ tàu)",
    "SHIP_SECURITY": "Declaration for Ship Security (Bản khai an ninh tàu biển)",
    "HEALTH_DECLARATION": "Maritime Declaration of Health (Bản khai y tế)",
    "PLANT_DECLARATION": "Declaration for Plant (Bản khai kiểm dịch thực vật)",
    "ANIMAL_DECLARATION": "Declaration for Animal (Bản khai kiểm dịch động vật)",
    "EMPTY_CONTAINER_LIST": "Empty Container List (Danh sách container rỗng)",
    "REFERENCE": "Chứng từ khai thác – tham khảo (SOF, NOR, Draft survey, Voyage memory, kế hoạch cầu bến, công văn…)",
    "CERTIFICATE": "Ship Certificate / Particulars / Port Clearance (Giấy chứng nhận, hồ sơ tàu – tham khảo)",
    "OTHER": "Unknown Document – Chứng từ chưa nhận diện / khác",
}

CLASSIFY_RULES = {
    "GENERAL_DECLARATION": [(r"GENERAL\s+DECLARATION", 10), (r"BAN\s+KHAI\s+CHUNG", 10), (r"IMO\s+FAL\s+FORM\s+1\b", 8),
                            (r"BRIEF\s+PARTICULARS\s+OF\s+VOYAGE", 4), (r"NUMBER\s+OF\s+CREW", 2), (r"ARRIVAL\s*/?\s*DEPARTURE", 2)],
    "NOTICE_OF_ARRIVAL": [(r"NOTICE\s+OF\s+ARRIVAL", 10), (r"PRE[\s-]*ARRIVAL\s+NOTI", 9), (r"THONG\s+BAO\s+TAU\s+DEN", 10),
                          (r"\bNOA\b", 4), (r"ARRIVAL\s+NOTICE", 9), (r"DRAFT\s+(FWD|FORE|AFT)", 2), (r"\bROB\b", 2)],
    "TONNAGE_CERTIFICATE": [(r"TONNAGE\s+CERTIFICATE", 10), (r"INTERNATIONAL\s+TONNAGE", 10), (r"TONNAGE\s+MEASUREMENT", 6),
                            (r"CHUNG\s+NHAN\s+DUNG\s+TICH", 10), (r"NET\s+TONNAGE", 2), (r"GROSS\s+TONNAGE", 2)],
    "CARGO_MANIFEST": [(r"CARGO\s+MANIFEST", 10), (r"\bMANIFEST\b", 4), (r"LUOC\s+KHAI", 10), (r"FREIGHT\s+MANIFEST", 8),
                       (r"IMO\s+FAL\s+FORM\s+2\b", 6), (r"CARGO\s+DECLARATION", 6)],
    "BILL_OF_LADING": [(r"BILL\s+OF\s+LADING", 10), (r"\bVAN\s+DON\b", 8), (r"SHIPPED\s+ON\s+BOARD", 4),
                       (r"PLACE\s+OF\s+RECEIPT", 3), (r"FREIGHT\s+(PREPAID|COLLECT)", 3), (r"NUMBER\s+OF\s+ORIGINAL", 3)],
    "CREW_LIST": [(r"CREW\s+LIST", 10), (r"DANH\s+SACH\s+THUYEN\s+VIEN", 10), (r"IMO\s+FAL\s+FORM\s+5\b", 8),
                  (r"RANK\s+OR\s+RATING", 4), (r"SEAMAN", 2), (r"PASSPORT", 1)],
    "PASSENGER_LIST": [(r"PASSENGER\s+LIST", 10), (r"DANH\s+SACH\s+HANH\s+KHACH", 10), (r"IMO\s+FAL\s+FORM\s+6\b", 8),
                       (r"PORT\s+OF\s+EMBARKATION", 4)],
    "DG_MANIFEST": [(r"DANGEROUS\s+GOODS", 9), (r"HAZARDOUS", 5), (r"IMDG", 5), (r"HANG\s+NGUY\s+HIEM", 10),
                    (r"\bUN\s*(NO|NUMBER)", 3), (r"FLASH\s*POINT", 3), (r"IMO\s+FAL\s+FORM\s+7\b", 8)],
    "CREW_EFFECTS": [(r"CREW'?S?\s+EFFECTS", 12), (r"HANH\s+LY\s+THUYEN\s+VIEN", 12), (r"IMO\s+FAL\s+FORM\s+4\b", 8)],
    # ship's certificates are reference documents, not declarations (registry, ISSC, sanitation, phytosanitary...)
    "CERTIFICATE": [(r"SHIP'?S?\s+PARTICULARS", 25), (r"THONG\s+SO\s+KY\s+THUAT\s+TAU", 25), (r"CERTIFICATE\s+OF\s+REGISTRY", 25), (r"GIAY\s+CHUNG\s+NHAN\s+DANG\s+KY\s+TAU", 25),
                    (r"INTERNATIONAL\s+SHIP\s+SECURITY\s+CERTIFICATE", 25), (r"CHUNG\s+NHAN\s+QUOC\s+TE\s+VE\s+AN\s+NINH", 25),
                    (r"SANITATION\s+CONTROL(\s+EXEMPTION)?\s+CERTIFICATE", 25), (r"MIEN\s+XU\s+LY\s+VE\s+SINH", 25),
                    (r"PHYTOSANITARY\s+CERTIFICATE", 25), (r"SAFETY\s+MANAGEMENT\s+CERTIFICATE", 25), (r"DOCUMENT\s+OF\s+COMPLIANCE", 20),
                    (r"PORT\s+CLEARANCE", 20), (r"GIAY\s+PHEP\s+ROI\s+CANG", 20)],
    # operational / commercial papers: kept for reference, never mapped to the NSW declaration
    "REFERENCE": [(r"STATEMENT\s+OF\s+FACTS?", 25), (r"NOTICE\s+OF\s+READINESS", 25), (r"DRAFT\s+SURVEY", 25), (r"VOYAGE\s+MEMORY", 25),
                  (r"KE\s+HOACH\s+TAU\s+(CAP|ROI)", 25), (r"BERTHING\s+PLAN", 20), (r"LETTER\s+OF\s+PROTEST", 25), (r"STOWAGE\s+PLAN", 20),
                  (r"MATE'?S\s+RECEIPT", 20), (r"XIN\s+VI\s+TRI\s+NEO", 20), (r"XAC\s+BAO\s+TAU\s+DI\s+CHUYEN", 25),
                  (r"CONFIRMATION\s+OF\s+SHIFTING", 25), (r"TIME\s+SHEET", 20)],
    "SHIP_SECURITY": [(r"SHIP\s+SECURITY", 10), (r"PRE[\s-]*ARRIVAL\s+SECURITY", 12), (r"AN\s+NINH\s+TAU", 10), (r"\bISSC\b", 5),
                      (r"SECURITY\s+LEVEL", 4), (r"LAST\s+(10|TEN)\s+PORTS?", 6), (r"SHIP\s+SECURITY\s+OFFICER", 3)],
    "HEALTH_DECLARATION": [(r"DECLARATION\s+OF\s+HEALTH", 12), (r"MARITIME\s+DECLARATION", 10), (r"Y\s+TE\s+HANG\s+HAI", 12),
                           (r"SHIP\s+SANITATION", 4), (r"HEALTH\s+QUESTIONS", 5), (r"DECLARATION\s+FOR\s+HEALTH", 12),
                           (r"KHAI\s+BAO\s+Y\s+TE", 12), (r"KIEM\s+DICH\s+Y\s+TE", 10)],
    "PLANT_DECLARATION": [(r"DECLARATION\s+FOR\s+PLANT", 12), (r"KIEM\s+DICH\s+THUC\s+VAT", 12), (r"PHYTOSANITARY", 8), (r"PLANT\s+QUARANTINE", 10)],
    "ANIMAL_DECLARATION": [(r"DECLARATION\s+FOR\s+ANIMAL", 12), (r"KIEM\s+DICH\s+DONG\s+VAT", 12), (r"ANIMAL\s+QUARANTINE", 10),
                           (r"VETERINARY", 6)],
    "EMPTY_CONTAINER_LIST": [(r"EMPTY\s+CONTAINERS?\s+(LIST|DECLARATION|MANIFEST)", 12), (r"CONTAINER\s+RONG", 12),
                             (r"LIST\s+OF\s+EMPTY\s+CONTAINERS?", 12), (r"\bEMPTY\b", 2)],
    "SHIP_STORES": [(r"SHIP'?S?\s+STORES?", 12), (r"DU\s+TRU\s+(CUA\s+)?TAU", 12), (r"IMO\s+FAL\s+FORM\s+3\b", 8),
                    (r"NAME\s+OF\s+ARTICLE", 4), (r"LOCATION\s+ON\s+BOARD", 3)],
}


def document_title_type(text, top_lines=12):
    """Type whose main title (pattern weight >= 8) appears in the first lines; strongest title wins, then earliest."""
    lines = [N.strip_accents(l).upper().strip() for l in (text or "").splitlines() if l.strip()][:top_lines]
    best = None
    for li, line in enumerate(lines):
        core = re.sub(r"[^A-Z0-9]", "", line)
        for t, rules in CLASSIFY_RULES.items():
            for pat, w in rules:
                if w < 8:
                    continue
                m = re.search(pat, line)
                # a title line is (mostly) the title itself, not a phrase inside a long sentence / table row
                if m and len(re.sub(r"[^A-Z0-9]", "", m.group(0))) >= 0.35 * max(1, len(core)) and \
                        (best is None or (w, -li) > (best[1], -best[2])):
                    best = (t, w, li)
    return best[0] if best else None


def classify(pages):
    text = "\n".join(p["text"] for p in pages)
    up = N.strip_accents(text).upper()
    title = "\n".join(N.strip_accents(pages[0]["text"]).upper().splitlines()[:15]) if pages else ""
    scores = {}
    for t, rules in CLASSIFY_RULES.items():
        s = 0
        for pat, w in rules:
            if re.search(pat, up):
                s += w
                if re.search(pat, title):
                    s += w  # title lines count double
        scores[t] = s
    titled = document_title_type(pages[0]["text"]) if pages else None
    if titled:
        scores[titled] += 30  # the document's own title beats keywords mentioned in its body
    best = max(scores, key=scores.get)
    total = sum(scores.values()) or 1
    if scores[best] < (6 if titled else 10):  # without a title, a single body keyword is not enough
        return "OTHER", 0.0, scores
    return best, round(scores[best] / total, 2), scores


# ------------------------------------------------------------------ header labels
H = {
    "vessel_name": ("Tên tàu / Vessel name", [r"name\s+of\s+(the\s+)?(ship|vessel)", r"vessel'?s?\s+name", r"ship'?s?\s+name", r"name\s+and\s+type\s+of\s+ship",
                                              r"vessel\s*(name)?(?=\s*[:\-])", r"t[eê]n\s+t[aà]u", r"ocean\s+vessel", r"^\s*vessel\b(?!\s+(type|flag))"]),
    "imo": ("IMO Number", [r"imo\s*(no\.?|number|nr\.?)?(?=\s*[:\.\-\s]\s*\d)", r"imo\s+number", r"imo\s+no"]),
    "call_sign": ("Call sign", [r"call\s*sign", r"\bircs\b", r"h[oô]\s+hi[eệ]u", r"distinctive\s+(number\s+or\s+)?letters"]),
    "flag": ("Flag / Quốc tịch", [r"flag\s+state(\s+of\s+ship)?", r"\bflag\b", r"nationality\s+of\s+(ship|vessel)", r"qu[oố]c\s+t[iị]ch\s+t[aà]u"]),  # port of registry is NOT the flag
    "voyage_no": ("Voyage No.", [r"voyage\s*(no\.?|number|nr\.?)", r"\bchuy[eế]n(?=\s*:)", r"\bvoy\b\.?\s*(no\.?)?", r"^\s*voyage\b(?=\s*[:\-]|\s{2,}\S)", r"s[oố]\s+chuy[eế]n", r"chuy[eế]n\s+s[oố]"]),
    "port_of_arrival": ("Port of arrival", [r"c[aả]ng\s+[dđ][eế]n\s*/\s*r[oờ]i", r"port\s+of\s+arrival\s*/\s*departure", r"port\s+of\s+arrival(\s*/\s*departure)?", r"port\s+of\s+call(?!\s*[:\-]?\s*last)", r"arrival\s+port", r"c[aả]ng\s+[dđ][eế]n"]),
    "last_port": ("Last port of call", [r"last\s+port\s+of\s+call\s*/\s*port\s+of\s+destination", r"last\s+port(\s+of\s+call)?",
                                         r"c[aả]ng\s+r[oờ]i\s+cu[oố]i(\s+c[uù]ng)?(\s*/\s*c[aả]ng\s+[dđ][ií]ch)?", r"previous\s+port", r"port\s+arrived\s+from", r"arrived\s+from", r"c[aả]ng\s+r[oờ]i\s+cu[oố]i"]),
    "next_port": ("Next port of call", [r"next\s+port(\s+of\s+call)?", r"c[aả]ng\s+[dđ][eế]n\s+ti[eế]p"]),
    "eta": ("ETA", [r"\beta\b(?!\s+pilot)", r"estimated\s+time\s+of\s+arrival", r"date\s*(and|&|-)\s*time\s+of\s+arrival", r"arrival\s+date",
                    r"time\s+of\s+arrival", r"date\s+of\s+arrival", r"th[oờ]i\s+gian\s+[dđ][eế]n(\s*/\s*r[oờ]i)?",
                    r"ng[aà]y\s+[dđ][eế]n(\s*/\s*r[oờ]i)?"]),
    "etd": ("ETD", [r"\betd\b", r"estimated\s+time\s+of\s+departure", r"departure\s+date"]),
    "master_name": ("Master name", [r"name\s+of\s+master", r"master'?s?\s+name", r"\bmaster\b(?=\s*[:\-])", r"captain(?=\s*[:\-])", r"thuy[eề]n\s+tr[uư][oở]ng"]),
    "crew_count": ("Number of crew", [r"number\s+of\s+crew", r"no\.?\s+of\s+crew", r"crew\s+(number|on\s+board)", r"s[oố]\s+thuy[eề]n\s+vi[eê]n"]),
    "passenger_count": ("Number of passengers", [r"number\s+of\s+passengers", r"no\.?\s+of\s+passengers", r"s[oố]\s+h[aà]nh\s+kh[aá]ch"]),
    "gross_tonnage": ("Gross tonnage", [r"gross\s+tonnage", r"\bg\.?r\.?t\.?\b", r"\bgt\b(?=\s*[:\-\s]\s*\d)", r"t[oổ]ng\s+dung\s+t[ií]ch"]),
    "net_tonnage": ("Net tonnage", [r"net\s+tonnage", r"\bn\.?r\.?t\.?\b", r"\bnt\b(?=\s*[:\-\s]\s*\d)", r"dung\s+t[ií]ch\s+c[oó]\s+[ií]ch"]),
    "dwt": ("Deadweight", [r"dead\s*weight", r"\bdwt\b"]),
    "loa": ("LOA", [r"length\s+overall", r"\bloa\b"]),
    "draft_fwd": ("Mớn nước mũi (F)", [r"draft\s*(fwd|fore|forward|\(f\))", r"draught\s*(fwd|fore|forward)", r"fwd\s+draft"]),
    "draft_aft": ("Mớn nước lái (A)", [r"draft\s*(aft|\(a\))", r"draught\s*aft", r"aft\s+draft"]),
    "air_draft": ("Chiều cao tĩnh không", [r"air\s+draft", r"air\s+draught", r"clearance\s+height"]),
    "berth": ("Vị trí tàu tại cảng / Berth", [r"\bberth\b(?!ing)(?=\s*(no\.?)?\s*[:\-])", r"position\s+(of\s+the\s+ship\s+)?in\s+(the\s+)?port"]),
    "rob_do": ("ROB DO", [r"\bd\.?o\.?\b(?=\s*[:\-]?\s*\d)", r"diesel\s+oil", r"\bmgo\b", r"\bdo\s+rob\b", r"rob\s+do"]),
    "rob_fo": ("ROB FO", [r"\bf\.?o\.?\b(?=\s*[:\-]?\s*\d)", r"fuel\s+oil", r"\bhfo\b", r"\bifo\b", r"rob\s+fo", r"\bvlsfo\b"]),
    "rob_fw": ("ROB FW", [r"\bf\.?w\.?\b(?=\s*[:\-]?\s*\d)", r"fresh\s+water", r"rob\s+fw"]),
    "cargo_brief": ("Brief description of cargo", [r"brief\s+description\s+of\s+(the\s+)?cargo", r"cargo\s+on\s+board", r"description\s+of\s+cargo"]),
    "purpose_of_call": ("Purpose of call", [r"purpose\s+of\s+call"]),
    "port_of_loading": ("Port of loading", [r"port\s+of\s+loading", r"\bpol\b", r"loading\s+port", r"c[aả]ng\s+x[eế]p(\s+h[aà]ng)?"]),
    "port_of_discharge": ("Port of discharge", [r"port\s+of\s+discharge", r"\bpod\b", r"discharge\s+port", r"c[aả]ng\s+d[oỡ](\s+h[aà]ng)?"]),
    "place_of_delivery": ("Place of delivery", [r"place\s+of\s+delivery", r"final\s+destination"]),
    "date_of_issue": ("Date of issue", [r"date\s+of\s+issue", r"place\s+and\s+date\s+of\s+issue", r"issued?\s+(on|date)"]),
    "certificate_no": ("Certificate No.", [r"certificate\s+no\.?", r"cert\.?\s+no"]),
    # B/L specific
    "bl_no": ("B/L No.", [r"b\s*/\s*l\s*(no\.?|number|nr)", r"bill\s+of\s+lading\s+(no\.?|number)", r"\bbl\s*(no\.?|number)", r"s[oố]\s+v[aậ]n\s+[dđ][oơ]n"]),
    "shipper": ("Shipper", [r"\bshipper\b(\s*/\s*exporter)?", r"consignor", r"ng[uư][oờ]i\s+g[uử]i\s+h[aà]ng"]),
    "consignee": ("Consignee", [r"\bconsignee\b", r"ng[uư][oờ]i\s+nh[aậ]n\s+h[aà]ng"]),
    "notify": ("Notify party", [r"notify\s+part(y|ies)", r"notify\s+address", r"also\s+notify", r"\bnotify\b"]),
    "packages": ("Number of packages", [r"(no\.?|number)\s+of\s+(packages|pkgs)", r"total\s+(no\.?\s+of\s+)?packages", r"\bpackages\b(?=\s*[:\-])", r"quantity(?=\s*[:\-])"]),
    "gross_weight": ("Gross weight", [r"gross\s+weight", r"\bg\s*\.?\s*w\.?\b(?=\s*[:\-\s]\s*\d)", r"total\s+weight"]),
    "net_weight": ("Net weight", [r"net\s+weight", r"\bn\s*\.?\s*w\.?\b(?=\s*[:\-\s]\s*\d)"]),
    "measurement": ("Measurement", [r"measurement", r"\bvolume\b", r"\bcbm\b(?=\s*[:\-])"]),
    "description": ("Description of goods", [r"description\s+of\s+(the\s+)?goods", r"description\s+of\s+packages\s+and\s+goods", r"kind\s+of\s+packages;?\s*description\s+of\s+goods", r"\bcommodity\b", r"m[oô]\s+t[aả]\s+h[aà]ng"]),
    "issc_issuer": ("Cơ quan cấp ISSC", [r"issuing\s+authority", r"issued\s+by", r"c[oơ]\s+quan\s+c[aấ]p"]),
    "issc_issue_date": ("Ngày cấp ISSC", [r"date\s+of\s+issue\s+of\s+(the\s+)?issc", r"issc\s+(issue\s+)?date", r"issc\s+issued\s+on"]),
    "issc_expiry": ("Ngày hết hạn ISSC", [r"date\s+of\s+expiry\s+of\s+(the\s+)?issc", r"issc\s+expir\w*", r"expiry\s+date\s+of\s+issc"]),
    "security_level": ("Cấp độ an ninh hiện tại", [r"current\s+security\s+level", r"security\s+level(?!s)", r"c[aấ]p\s+[dđ][oộ]\s+an\s+ninh"]),
    "latitude": ("Vĩ độ", [r"\blatitude\b", r"v[iĩ]\s+[dđ][oộ]"]),
    "longitude": ("Kinh độ", [r"\blongitude\b", r"kinh\s+[dđ][oộ]"]),
    "container_type": ("Loại container", [r"size\s*/\s*type", r"cont(ainer)?\.?\s*type", r"equipment\s*type", r"container\s+size"]),
    "date_of_bl": ("Ngày phát hành B/L", [r"(shipped\s+on\s+board|on\s+board)\s+date", r"date\s+of\s+(b\s*/\s*l|issue)"]),
}

SECTION_OF_HEADER = "vessel"
DOC_HEADER_FIELDS = {
    "GENERAL_DECLARATION": ["vessel_name", "imo", "call_sign", "flag", "voyage_no", "port_of_arrival", "last_port", "next_port", "eta", "etd",
                            "master_name", "crew_count", "passenger_count", "gross_tonnage", "net_tonnage", "berth", "cargo_brief",
                            "draft_fwd", "draft_aft", "air_draft", "rob_do", "rob_fo", "rob_fw", "purpose_of_call"],
    "NOTICE_OF_ARRIVAL": ["vessel_name", "imo", "call_sign", "flag", "voyage_no", "port_of_arrival", "last_port", "next_port", "eta", "etd",
                          "master_name", "crew_count", "passenger_count", "gross_tonnage", "net_tonnage", "dwt", "loa", "draft_fwd", "draft_aft",
                          "air_draft", "berth", "rob_do", "rob_fo", "rob_fw", "cargo_brief", "purpose_of_call"],
    "TONNAGE_CERTIFICATE": ["vessel_name", "imo", "call_sign", "flag", "gross_tonnage", "net_tonnage", "date_of_issue", "certificate_no"],
    "CARGO_MANIFEST": ["vessel_name", "imo", "call_sign", "flag", "voyage_no", "port_of_loading", "port_of_discharge", "eta", "master_name"],
    "BILL_OF_LADING": ["vessel_name", "voyage_no"],
    "CREW_LIST": ["vessel_name", "imo", "call_sign", "flag", "voyage_no", "port_of_arrival", "last_port", "eta", "master_name", "crew_count"],
    "PASSENGER_LIST": ["vessel_name", "imo", "call_sign", "flag", "voyage_no", "port_of_arrival", "passenger_count"],
    "DG_MANIFEST": ["vessel_name", "imo", "call_sign", "flag", "voyage_no", "port_of_loading", "port_of_discharge"],
    "CREW_EFFECTS": ["vessel_name", "imo", "call_sign", "flag", "voyage_no"],
    "SHIP_STORES": ["vessel_name", "imo", "call_sign", "flag", "voyage_no", "port_of_arrival", "crew_count", "passenger_count"],
    "SHIP_SECURITY": ["vessel_name", "imo", "call_sign", "flag", "voyage_no", "port_of_arrival", "eta", "issc_issuer", "issc_issue_date",
                      "issc_expiry", "security_level", "latitude", "longitude", "purpose_of_call"],
    "HEALTH_DECLARATION": ["vessel_name", "imo", "call_sign", "flag", "voyage_no", "port_of_arrival", "last_port", "next_port", "crew_count",
                           "passenger_count", "master_name"],
    "PLANT_DECLARATION": ["vessel_name", "imo", "call_sign", "flag", "voyage_no", "port_of_loading", "next_port"],
    "ANIMAL_DECLARATION": ["vessel_name", "imo", "call_sign", "flag", "voyage_no", "next_port"],
    "EMPTY_CONTAINER_LIST": ["vessel_name", "imo", "call_sign", "flag", "voyage_no", "port_of_discharge"],
    "CERTIFICATE": ["vessel_name", "imo", "call_sign", "flag"],
    "REFERENCE": ["vessel_name", "imo", "call_sign", "flag", "voyage_no"],
    "OTHER": ["vessel_name", "imo", "call_sign", "flag", "voyage_no"],
}
BL_HEADER_FIELDS = ["bl_no", "shipper", "consignee", "notify", "port_of_loading", "port_of_discharge", "place_of_delivery",
                    "description", "packages", "gross_weight", "net_weight", "measurement", "date_of_bl", "container_type"]
MULTILINE_PARTY = {"shipper", "consignee", "notify"}
DATE_FIELDS = {"eta", "etd", "date_of_issue", "date_of_bl", "dob", "passport_expiry", "seaman_book_expiry", "issc_issue_date", "issc_expiry",
               "arrival", "departure"}


# ------------------------------------------------------------------ table specs
T = {
    "crew": {
        "seq": [r"^no\.?$", r"^s/?n$", r"^stt$", r"^sr\.?\s*no", r"^#$"],
        "family_name": [r"family\s+name", r"surname", r"last\s+name", r"^h[oọ]\b"],
        "given_name": [r"given\s+names?", r"first\s+name", r"^t[eê]n\b"],
        "full_name": [r"full\s+name", r"^name", r"name\s+of\s+crew", r"h[oọ]\s+(v[aà]\s+)?t[eê]n", r"family\s+name\s*,\s*given"],
        "rank": [r"rank", r"rating", r"position", r"capacity", r"ch[uứ]c\s+danh", r"duty"],
        "nationality": [r"nationality", r"qu[oố]c\s+t[iị]ch", r"citizenship"],
        "dob": [r"date\s+of\s+birth", r"d\.?o\.?b", r"birth\s+date", r"ng[aà]y\s+sinh"],
        "pob": [r"place\s+of\s+birth", r"birth\s*place", r"n[oơ]i\s+sinh"],
        "gender": [r"^sex$", r"gender", r"gi[oớ]i\s+t[ií]nh", r"^m/f$"],
        "passport_no": [r"passport\s*(no|number)?", r"identity\s+document", r"h[oộ]\s+chi[eế]u", r"id\s+doc"],
        "passport_expiry": [r"(passport\s+)?expiry", r"date\s+of\s+expiry", r"valid\s+(until|till)", r"h[eế]t\s+h[aạ]n"],
        "seaman_book_no": [r"seam[ae]n'?s?\s+book", r"s\.?\s*book", r"s[oổ]\s+thuy[eề]n\s+vi[eê]n", r"\bcdc\b"],
        "_required": ["rank|nationality|dob|passport_no"],
    },
    "passenger": {
        "seq": [r"^no\.?$", r"^stt$"],
        "family_name": [r"family\s+name", r"surname"], "given_name": [r"given\s+names?", r"first\s+name"],
        "full_name": [r"full\s+name", r"^name", r"h[oọ]\s+(v[aà]\s+)?t[eê]n", r"family\s+name\s*,\s*given"],
        "nationality": [r"nationality", r"qu[oố]c\s+t[iị]ch"], "dob": [r"date\s+of\s+birth", r"d\.?o\.?b"],
        "pob": [r"place\s+of\s+birth"], "gender": [r"^sex$", r"gender"],
        "passport_type": [r"type\s+of\s+identity", r"document\s+type"],
        "passport_no": [r"passport", r"serial\s+number\s+of\s+identity", r"identity\s+document"],
        "passport_expiry": [r"expiry", r"valid\s+until"],
        "port_embark": [r"port\s+of\s+embarkation", r"embark"], "port_disembark": [r"port\s+of\s+disembarkation", r"disembark"],
        "transit": [r"transit"],
        "_required": ["nationality|passport_no|port_embark"],
    },
    "cargo": {
        "seq": [r"^no\.?$", r"^stt$", r"^item$"],
        "bl_no": [r"b\s*/\s*l", r"bill\s+of\s+lading", r"\bbl\s*no", r"v[aậ]n\s+[dđ][oơ]n"],
        "shipper": [r"shipper", r"consignor", r"ng[uư][oờ]i\s+g[uử]i"], "consignee": [r"consignee", r"ng[uư][oờ]i\s+nh[aậ]n"],
        "notify": [r"notify", r"ng[uư][oờ]i\s+(nh[aậ]n\s+)?th[oô]ng\s+b[aá]o"],
        "marks": [r"marks"],
        "packages": [r"(no\.?|number)\s+of\s+(packages|pkgs)", r"^packages?$", r"^pkgs?\.?$", r"^q(uan)?ty", r"quantity", r"s[oố]\s+ki[eệ]n"],
        "package_kind": [r"kind\s+of\s+packages?", r"package\s+type", r"^type$", r"lo[aạ]i\s+ki[eệ]n"],
        "description": [r"description", r"commodity", r"goods", r"m[oô]\s+t[aả]", r"t[eê]n\s+h[aà]ng"],
        "gross_weight": [r"gross\s*weight", r"^g\.?\s*w\.?", r"^weight", r"tr[oọ]ng\s+l[uư][oợ]ng"],
        "net_weight": [r"net\s*weight", r"^n\.?\s*w\.?"],
        "measurement": [r"measurement", r"volume", r"cbm", r"^m3$", r"th[eể]\s+t[ií]ch"],
        "container_no": [r"container", r"\bcntr", r"\bctnr", r"s[oố]\s+cont"],
        "container_type": [r"cont(ainer)?\.?\s*type", r"size\s*/?\s*type", r"^size$", r"^sz\s*/?\s*tp", r"equipment", r"^eqp", r"lo[aạ]i\s+cont"],
        "seal_no": [r"seal"],
        "pol": [r"port\s+of\s+loading", r"^pol$", r"loading"],
        "pod": [r"port\s+of\s+discharge", r"^pod$", r"discharg"],
        "hs_code": [r"hs\s*code", r"h\.s\.", r"m[aã]\s+s[oố]\s+h[aà]ng"],
        "_required": ["bl_no", "description|gross_weight|packages"],
    },
    "dg": {
        "bl_no": [r"b\s*/\s*l", r"booking", r"reference"], "container_no": [r"container\s*(no|number)?", r"cntr"],
        "seal_no": [r"seal"], "marks": [r"marks"],
        "un_no": [r"\bun\s*(no|number)?\b", r"un\s*no"], "imdg_class": [r"class", r"imdg"],
        "proper_shipping_name": [r"proper\s+shipping\s+name", r"shipping\s+name", r"description", r"substance"],
        "packing_group": [r"packing\s+group", r"^p\.?g\.?$"], "subsidiary_risk": [r"subsidiary"],
        "flash_point": [r"flash\s*point"], "marine_pollutant": [r"marine\s+pollutant", r"pollutant"],
        "packages": [r"(no\.?|number)\s+of\s+packages", r"^packages?$", r"^q(uan)?ty"],
        "package_kind": [r"kind\s+of\s+packages?", r"package\s+type"],
        "gross_weight": [r"gross", r"weight", r"mass"], "stowage": [r"stowage", r"position"],
        "transporter": [r"transporter", r"carrier", r"shipping\s+line", r"^operator", r"cty\s+v[aậ]n\s+chuy[eể]n"],
        "_required": ["un_no", "imdg_class|proper_shipping_name"],
    },
    "empty_container": {
        "seq": [r"^no\.?$", r"^stt$"],
        "bl_no": [r"b\s*/\s*l", r"booking", r"bill\s+of\s+lading", r"v[aậ]n\s+[dđ][oơ]n"],
        "container_no": [r"container\s*(no|number)?", r"\bcntr", r"s[oố]\s+(hi[eệ]u\s+)?cont"],
        "container_type": [r"cont(ainer)?\.?\s*type", r"size\s*/?\s*type", r"^size$", r"^type$", r"lo[aạ]i\s+cont"],
        "pod": [r"port\s+of\s+discharge", r"^pod$", r"discharg", r"c[aả]ng\s+d[oỡ](\s+h[aà]ng)?"],
        "_required": ["container_no", "bl_no|container_type|pod"],
    },
    "port_calls": {
        "seq": [r"^no\.?$", r"^stt$"],
        "port_code": [r"locode", r"port\s*code", r"m[aã]\s+c[aả]ng"],
        "port_name": [r"^port(\s+(of\s+call|name))?$", r"port\s+of\s+call", r"port\s+name", r"t[eê]n\s+c[aả]ng", r"^port\b"],
        "arrival": [r"arriv", r"ng[aà]y\s+[dđ][eế]n"],
        "departure": [r"depart", r"ng[aà]y\s+[dđ]i"],
        "security_level": [r"security\s+level", r"^level$", r"c[aấ]p\s+[dđ][oộ]"],
        "_required": ["port_name|port_code", "arrival|departure"],
    },
    "store": {
        "seq": [r"^no\.?$", r"^stt$"],
        "article": [r"name\s+of\s+article", r"article", r"item", r"description", r"t[eê]n\s+v[aậ]t\s+ph[aẩ]m"],
        "quantity": [r"quantity", r"^q'?ty", r"amount", r"s[oố]\s+l[uư][oợ]ng"],
        "unit": [r"^unit", r"[dđ][oơ]n\s+v[iị]"],
        "location": [r"location", r"place\s+of\s+storage", r"v[iị]\s+tr[ií]"],
        "official_use": [r"official\s+use", r"in\s+use"],
        "_required": ["article", "quantity"],
    },
    "effects": {
        "seq": [r"^no\.?$", r"^stt$"],
        "family_name": [r"family\s+name", r"surname"], "given_name": [r"given\s+names?", r"first\s+name"],
        "full_name": [r"full\s+name", r"^name", r"name\s+of\s+crew", r"h[oọ]\s+(v[aà]\s+)?t[eê]n", r"family\s+name\s*,\s*given"],
        "rank": [r"rank", r"rating", r"position"],
        "effects": [r"effects", r"articles", r"dutiable", r"description", r"h[aà]nh\s+l[yý]"],
        "_required": ["effects", "full_name|family_name"],
    },
}
DOC_TABLES = {
    "CREW_LIST": ["crew"], "PASSENGER_LIST": ["passenger"], "CARGO_MANIFEST": ["cargo"], "BILL_OF_LADING": ["cargo"],
    "DG_MANIFEST": ["dg"], "SHIP_STORES": ["store"], "CREW_EFFECTS": ["effects"],
    "EMPTY_CONTAINER_LIST": ["empty_container"], "SHIP_SECURITY": ["port_calls"],
}
FIELD_LABELS = {
    "seq": "STT", "family_name": "Họ / Family name", "given_name": "Tên / Given name", "full_name": "Họ tên / Full name",
    "rank": "Chức danh / Rank", "nationality": "Quốc tịch / Nationality", "dob": "Ngày sinh / DOB", "pob": "Nơi sinh / POB",
    "gender": "Giới tính / Gender", "passport_no": "Số hộ chiếu / Passport No.", "passport_expiry": "Hạn hộ chiếu / Expiry",
    "seaman_book_no": "Sổ thuyền viên / Seaman book", "passport_type": "Loại giấy tờ", "port_embark": "Cảng lên tàu",
    "port_disembark": "Cảng rời tàu", "transit": "Quá cảnh", "marks": "Marks", "package_kind": "Loại kiện",
    "container_no": "Số container", "container_type": "Loại cont (20/40/45)", "seal_no": "Số seal", "pol": "Cảng xếp hàng (POL)", "pod": "Cảng dỡ hàng (POD)",
    "hs_code": "HS code", "un_no": "UN No.", "imdg_class": "IMDG Class", "proper_shipping_name": "Proper shipping name",
    "packing_group": "Packing group", "subsidiary_risk": "Subsidiary risk", "flash_point": "Flash point",
    "marine_pollutant": "Marine pollutant", "stowage": "Vị trí xếp", "article": "Tên vật phẩm", "quantity": "Số lượng",
    "transporter": "Cty vận chuyển / Transporter", "port_code": "Mã cảng", "port_name": "Tên cảng", "arrival": "Ngày đến",
    "departure": "Ngày đi", "security_level": "Cấp độ an ninh", "issc_issuer": "Cơ quan cấp ISSC",
    "unit": "Đơn vị", "gross_weight_unit": "Đơn vị trọng lượng (từ tiêu đề cột)", "measurement_unit": "Đơn vị thể tích (từ tiêu đề cột)",
    "net_weight_unit": "Đơn vị trọng lượng tịnh", "location": "Vị trí trên tàu", "official_use": "Sử dụng trên tàu", "effects": "Hành lý / Effects",
}
for _k, (_lbl, _) in H.items():
    FIELD_LABELS.setdefault(_k, _lbl)

LOW_CONF = 0.80


def _compile(pats):
    return [re.compile(p, re.I) for p in pats]


H_RE = {k: (lbl, _compile(p)) for k, (lbl, p) in H.items()}
T_RE = {s: {f: _compile(p) for f, p in spec.items() if not f.startswith("_")} for s, spec in T.items()}


def _fold(s):
    return N.strip_accents(s or "")


# ------------------------------------------------------------------ header extraction
def _label_hits(line, keys):
    """All label matches on a folded line: list of (start, end, key) without overlap (longest wins)."""
    cands = []
    for k in keys:
        for rx in H_RE[k][1]:
            for m in rx.finditer(line):
                if m.end() > m.start():
                    cands.append((m.start(), m.end(), k))
    cands = [c for c in cands if line[:c[0]].count("(") <= line[:c[0]].count(")")]  # "(gồm cả thuyền trưởng)" is not a label
    cands.sort(key=lambda c: (c[0], -(c[1] - c[0])))
    hits, last_end = [], -1
    for c in sorted(cands, key=lambda c: -(c[1] - c[0])):
        if all(c[1] <= h[0] or c[0] >= h[1] for h in hits):
            hits.append(c)
    hits.sort()
    return hits


_SEP = re.compile(r"^[\s:：\-–=\.\|/)\]]*(?:\((?:[^)]{0,45})\))?[\s:：\-–=\.\|)\]]*")
# an unknown label further on the same line: 1-3 Title-case words + ':' (e.g. " Inspection Order No.: ...")
_NEXT_LABEL = re.compile(r"\s+(?:[A-ZĐ][a-zà-ỹđ]+\.?\s?){1,3}(?:No\.?|Number)?\s*[:：]\s")


def _clean_value(v):
    v = _SEP.sub("", v or "").strip()
    v = re.split(r"\s{3,}|\t", v)[0]  # next table column / tab stop = next field
    v = re.split(r"\s*\|\s*", v)[0]
    v = _NEXT_LABEL.split(v)[0]  # "VINH QUANG GOLD | Số chuyến: 09/2023" -> next field starts after '|' 
    v = re.sub(r"\s{2,}", " ", v)
    return v.strip(" |;,")


def _word_conf(page, value):
    words = page.get("words")
    if not words or not value:
        return page.get("confidence", 1.0)
    cs = [words.get(w) for w in value.split() if words.get(w) is not None]
    return round(min(cs) if cs else page.get("confidence", 0.5) * 0.9, 2)


def extract_header(pages, keys, all_keys=None):
    """Return {key: {value, page_no, confidence, method}} for the first occurrence of each label."""
    all_keys = all_keys or list(H.keys())
    found = {}
    for page in pages:
        raw_lines = page["text"].splitlines()
        lines = [_fold(l) for l in raw_lines]
        for i, line in enumerate(lines):
            hits = _label_hits(line, all_keys)
            if not hits:
                continue
            # tabular header: several labels, no values -> values on next line split into columns
            values_inline = []
            for j, (s, e, k) in enumerate(hits):
                end = hits[j + 1][0] if j + 1 < len(hits) else len(line)
                values_inline.append(_clean_value(raw_lines[i][e:end]))
            if len(hits) > 1 and not any(values_inline) and i + 1 < len(lines):
                cols = [c.strip() for c in re.split(r"\s{3,}|\t|\|", raw_lines[i + 1]) if c.strip()]
                if len(cols) == len(hits) and not _label_hits(lines[i + 1], all_keys):
                    values_inline = cols
            for j, (s, e, k) in enumerate(hits):
                if k not in keys or k in found:
                    continue
                val = values_inline[j]
                method = page["method"]
                if method == "ocr" and val:
                    val = re.split(r"\s{3,}| [|©™¬“”] ", val)[0]
                if not val and j == len(hits) - 1:
                    # value on following line(s) (box layout: label above value)
                    nxt = []
                    for nl in range(i + 1, min(i + 5, len(lines))):
                        if not raw_lines[nl].strip():
                            continue
                        if _label_hits(lines[nl], all_keys):
                            break
                        nxt.append(re.split(r"\s{3,}", raw_lines[nl].strip())[0])
                        if k not in MULTILINE_PARTY or len(nxt) >= 1:
                            break
                    val = _clean_value(" ".join(nxt))
                if not val or len(val) > 160:
                    continue
                val = _post_header(k, val)
                if not val:
                    continue
                conf = 0.95 if method != "ocr" else _word_conf(page, val)
                found[k] = {"value": val, "page_no": page["page_no"], "confidence": conf, "method": method}
    if ("draft_fwd" in keys or "draft_aft" in keys) and "draft_fwd" not in found:
        for page in pages:
            m = re.search(r"(draft|draught|m[oớ]n\s+n[uư][oớ]c)[^\n]{0,40}?\bF\w*\s*[:.]?\s*([\d.,]+)\s*m?\s*[/,;]\s*A\w*\s*[:.]?\s*([\d.,]+)",
                          _fold(page["text"]), re.I)
            if m:
                for key, val in (("draft_fwd", m.group(2)), ("draft_aft", m.group(3))):
                    if key in keys:
                        found[key] = {"value": val + " m", "page_no": page["page_no"], "confidence": 0.9 if page["method"] != "ocr" else 0.7,
                                      "method": page["method"]}
                break
    # regex fallbacks for strongly-typed identifiers
    if "imo" in keys and "imo" not in found:
        for page in pages:
            m = re.search(r"IMO[^0-9\n]{0,15}(\d{7})\b", _fold(page["text"]), re.I)
            if m:
                found["imo"] = {"value": m.group(1), "page_no": page["page_no"],
                                "confidence": 0.9 if page["method"] != "ocr" else _word_conf(page, m.group(1)), "method": page["method"]}
                break
    return found


def _post_header(k, v):
    if k == "imo":
        m = re.search(r"\b(\d{7})\b", v)
        return m.group(1) if m else None
    if k == "call_sign":
        m = re.search(r"\b([A-Z0-9]{4,8})\b", v.upper())
        return m.group(1) if m and re.search(r"\d", m.group(1)) or (m and len(m.group(1)) >= 4) else None
    if k in ("gross_tonnage", "net_tonnage", "dwt"):
        m = re.search(r"\d[\d.,]*(\s*(GT|NT|MT|T|TONS?|MTS))?", v, re.I)
        return m.group(0) if m else None  # "(" or a label fragment is not a tonnage
    if k in ("eta", "etd"):
        return v if N.parse_date(v)[1] else None  # an arrival time must contain a date ("Pilot Vũng Tàu)" is not one)
    if k == "last_port":
        v = re.split(r"\s+/\s+", v)[0]  # "SURABAYA, INDONESIA / CẢNG ĐÍCH ..." -> last port only
    if k == "master_name":
        v = re.sub(r"^(CAPT\.?|CAPTAIN|MASTER)\s+", "", v.strip(), flags=re.I)
        if not re.match(r"^[A-Za-zÀ-ỹĐđ]", v) or len(re.findall(r"[A-Za-zÀ-ỹĐđ]{2,}", v)) < 2 or re.search(r"[()]", v):
            return None  # signature-block text, not a name
    if k in ("crew_count", "passenger_count"):
        m = re.search(r"\b(\d{1,4})\b", v)
        return m.group(1) if m else None
    if k in ("vessel_name",):
        v = re.split(r"\s{3,}|\bIMO\b|\bFLAG\b|\bCALL\s*SIGN\b|\s+[—–]\s+|\s+-\s+|\s*\(|\s+\d+\.\d*\s", v, flags=re.I)[0]
        v = v.strip(" ,;:/|-–—")
        v = re.sub(r"^(M/?V|M\.V\.|MV)\s+", "", v.strip(), flags=re.I)
        # sentence fragments ("at the port of ...") are not vessel names
        if re.match(r"^(AT|IN|ON|TO|FROM|OF|FOR|WITH|AND|THE|IS|WAS|WILL|SHALL|HAS|BY|AS|ARRIV\w*|DEPART\w*)\b", N.strip_accents(v).upper()):
            return None
        if N.strip_accents(v).upper().strip(" .:") in ("VOYAGE", "VESSEL", "SHIP", "NAME", "TYPE", "FLAG", "VOY", "PORT"):
            return None  # a column title, not a name
        if not re.match(r"^[A-Z0-9]", N.strip_accents(v).upper()) or re.match(r"^'?S\s+NAME\b", N.strip_accents(v).upper()):
            return None  # "'s Name (" = leftover of the label "Vessel's Name", not a name
    if k == "voyage_no":
        v = v.split()[0] if v.split() else v
        if not re.search(r"\d", v):  # a voyage number always contains digits ("AGE", "OF" ... are reading errors)
            return None
    return v.strip() or None


# ------------------------------------------------------------------ tables
def _match_header(row, section):
    spec = T_RE[section]
    mapping = {}
    for ci, cell in enumerate(row):
        c = _fold(cell).strip().lower()
        if not c or len(c) > 180:
            continue
        best, best_len = None, 0
        for f, rxs in spec.items():
            if f in mapping.values():
                continue
            for rx in rxs:
                m = rx.search(c)
                if m and (m.end() - m.start()) > best_len:
                    best, best_len = f, m.end() - m.start()
        if best:
            mapping[ci] = best
    return mapping


def _header_ok(mapping, section):
    fields = set(mapping.values())
    for req in T[section].get("_required", []):
        if not any(r in fields for r in req.split("|")):
            return False
    return len(fields) >= 3


def _text_rows(page):
    """Pseudo-table from text lines, columns split on 3+ spaces/tabs (layout text or OCR)."""
    out = []
    for ln in page["text"].splitlines():
        if not ln.strip():
            continue
        out.append([c.strip() for c in re.split(r"\s{3,}|\t|\s\|\s", ln.strip())])
    return out


def _is_total_row(cells):
    j = _fold(" ".join(cells)).lower()
    return bool(re.match(r"^\s*(total|grand total|tong cong|tong)\b", j))


def extract_table(pages, section):
    """Return list of records: {fields: {key: {value,page_no,confidence,method}}, page_no}."""
    records = []
    state = None  # (mapping, ncols, source) for continuation on next pages
    for page in pages:
        candidates = [("table", t) for t in page.get("tables") or []]
        candidates.append(("text", _text_rows(page)))
        used_page = False
        for source, table in candidates:
            if used_page and source == "text":
                break
            mapping, start = None, None
            for ri, r in enumerate(table[:40]):
                m = _match_header(r, section)
                if _header_ok(m, section):
                    mapping, start = m, ri + 1
                    # 2-line headers: merge if next row is also header-like
                    if ri + 1 < len(table):
                        m2 = _match_header(table[ri + 1], section)
                        if len(m2) >= 3 and not any(_looks_like_data(c) for c in table[ri + 1]):
                            if len(table[ri + 1]) > len(r):
                                mapping = m2  # sub-header splits merged cells (e.g. 'Họ tên...' -> 'Người gửi' | 'Người nhận')
                            else:
                                for k, v in m2.items():
                                    mapping.setdefault(k, v)
                            start = ri + 2
                    break
            if mapping is None and state and state[2] == source and table and len(table[0]) == state[1]:
                mapping, start = state[0], 0  # continuation of previous page's table
            if mapping is None:
                continue
            hdr_row = table[start - 1] if start else []
            units = {}
            for ci, f in mapping.items():
                if ci < len(hdr_row):
                    um = re.search(r"\b(KGS?|KGM|MTS?|TONS?|TNE|CBM|M3|MTQ|LTRS?)\b", _fold(hdr_row[ci]).upper())
                    if um:
                        units[f] = um.group(1)
            ncols = max((len(r) for r in table[start:start + 5]), default=len(table[0]))
            state = (mapping, ncols, source)
            got = 0
            for r in table[start:]:
                if not any(c.strip() for c in r):
                    continue
                if _header_ok(_match_header(r, section), section):
                    continue  # repeated header
                if _is_total_row(r):
                    continue
                if source == "text" and len(r) < max(2, len(mapping) // 2):
                    # narrative line, not a table row
                    continue
                fields = {}
                for ci, f in mapping.items():
                    if ci < len(r) and r[ci].strip():
                        val = r[ci].strip()
                        conf = (0.95 if page["method"] != "ocr" else _word_conf(page, val) * 0.95)
                        if source == "text" and page["method"] != "ocr":
                            conf = 0.85  # column split from text layout is less certain than a ruled table
                        fields[f] = {"value": val, "page_no": page["page_no"], "confidence": round(conf, 2),
                                     "method": page["method"] + ("-table" if source == "table" else "-columns")}
                _split_combined(fields)
                if section == "cargo" and "gross_weight" not in fields:
                    for src in ("packages", "description"):
                        f = fields.get(src)
                        wm = f and re.search(r"(\d[\d.,]*)\s*(MTS?|TNE|TONS?|KGS?|KGM)\b", f["value"], re.I)
                        if wm:
                            fields["gross_weight"] = {**f, "value": f"{wm.group(1)} {wm.group(2)}", "method": f["method"] + "-weight-in-" + src,
                                                      "confidence": min(f["confidence"], 0.85)}
                            break
                for f, u in units.items():
                    if f in fields and not re.search(r"[A-Za-z]{2,}", fields[f]["value"]):
                        fields[f + "_unit"] = {**fields[f], "value": u, "method": fields[f]["method"] + "-header-unit"}
                if section == "cargo" and "container_type" not in fields and "container_no" in fields:
                    # size written inside another cell, e.g. "SEGU1234567 / 40HC"
                    ct = N.container_size(" ".join(c for i, c in enumerate(r) if mapping.get(i) not in ("gross_weight", "net_weight", "measurement", "packages")))
                    if ct:
                        fields["container_type"] = {**fields["container_no"], "value": ct, "confidence": 0.85,
                                                    "method": fields["container_no"]["method"] + "-size-regex"}
                # skip signature/footer lines
                if len(fields) < 2:
                    continue
                if section in ("crew", "passenger", "effects") and not any(k in fields for k in ("full_name", "family_name", "given_name")):
                    continue
                records.append({"fields": fields, "page_no": page["page_no"]})
                got += 1
            if got:
                used_page = True
    return records


_DATE_HEAD = re.compile(r"^\s*(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s*[-–,;/]?\s*(.*)$")


def _split_combined(fields):
    """Columns that hold two values in Vietnamese forms:
    'Ngày và nơi sinh' = '14/05/1976 - THAI BINH'; 'Số hộ chiếu & hết hạn' = 'C6829104 (12/08/2029)'."""
    for key in ("dob", "pob"):
        f = fields.get(key)
        if f and not ("dob" in fields and "pob" in fields):
            m = _DATE_HEAD.match(f["value"])
            if m and m.group(2).strip():
                fields["dob"] = {**f, "value": m.group(1)}
                fields["pob"] = {**f, "value": m.group(2).strip(" -–,")}
            elif m and key == "pob":
                fields["dob"] = {**f, "value": m.group(1)}
                fields.pop("pob")
    f = fields.get("passport_no")
    if f and "passport_expiry" not in fields:
        m = re.match(r"^\s*([A-Z0-9][A-Z0-9\-]{4,})\s*[(/,;\-–]\s*(?:exp\w*\.?:?\s*)?(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})\)?\s*$", f["value"], re.I)
        if m:
            fields["passport_no"] = {**f, "value": m.group(1)}
            fields["passport_expiry"] = {**f, "value": m.group(2)}


def _looks_like_data(c):
    return bool(re.search(r"\d{3,}", c or ""))


# ------------------------------------------------------------------ B/L (single document) & block manifests
def extract_bl_document(pages):
    """A B/L document normally describes one B/L. Header labels + containers by regex."""
    hdr = extract_header(pages, BL_HEADER_FIELDS)
    rec = dict(hdr)
    table = extract_table(pages, "cargo")
    if table:
        for f, v in table[0]["fields"].items():
            rec.setdefault(f if f not in ("pol", "pod") else {"pol": "port_of_loading", "pod": "port_of_discharge"}[f], v)
    text = "\n".join(p["text"] for p in pages)
    conts = N.find_containers(text)
    if conts:
        page_no = next((p["page_no"] for p in pages if conts[0] in p["text"].upper().replace(" ", "")), pages[0]["page_no"])
        rec["container_no"] = {"value": ", ".join(conts), "page_no": page_no, "confidence": 0.9 if pages[0]["method"] != "ocr" else 0.7,
                               "method": "regex"}
        seals = []
        for c in conts:
            m = re.search(re.escape(c[:4]) + r"\s?-?" + c[4:10] + r"\s?-?" + c[10] + r"[^\n]{0,40}?SEAL\s*(?:NO\.?)?\s*[:#]?\s*([A-Z0-9\-]{4,})", text.upper())
            if not m:
                m = re.search(re.escape(c[:4]) + r"\s?-?" + c[4:10] + r"\s?-?" + c[10] + r"\s*[/,]\s*([A-Z]{0,4}\d{4,}[A-Z0-9]*)", text.upper())
            if m:
                seals.append(m.group(1))
        if seals:
            rec["seal_no"] = {"value": ", ".join(seals), "page_no": page_no, "confidence": 0.85, "method": "regex"}
    if "container_type" not in rec:
        sizes = N.container_sizes(text)
        if sizes:
            rec["container_type"] = {"value": ", ".join(sizes), "page_no": pages[0]["page_no"],
                                     "confidence": 0.85 if pages[0]["method"] != "ocr" else 0.7, "method": "size-regex"}
    for k in ("pol", "pod"):
        if k in rec:
            rec.pop(k)
    return rec


def extract_block_manifest(pages):
    """Manifest laid out as one block per B/L (label: value), not a grid table."""
    text_pages = []
    for p in pages:
        text_pages.append(p)
    blocks, cur = [], None
    for p in text_pages:
        for line in p["text"].splitlines():
            if re.search(r"b\s*/\s*l\s*(no\.?|number)", _fold(line), re.I):
                cur = {"page": p, "lines": []}
                blocks.append(cur)
            if cur is not None:
                cur["lines"].append(line)
    records = []
    for b in blocks:
        pseudo = [{**b["page"], "text": "\n".join(b["lines"]), "tables": []}]
        rec = extract_header(pseudo, ["bl_no", "shipper", "consignee", "notify", "description", "packages", "gross_weight",
                                      "net_weight", "measurement", "port_of_loading", "port_of_discharge"])
        conts = N.find_containers("\n".join(b["lines"]))
        if conts:
            rec["container_no"] = {"value": ", ".join(conts), "page_no": b["page"]["page_no"], "confidence": 0.85, "method": "regex"}
        if "bl_no" in rec:
            rename = {"port_of_loading": "pol", "port_of_discharge": "pod"}
            records.append({"fields": {rename.get(k, k): v for k, v in rec.items()}, "page_no": b["page"]["page_no"]})
    return records


# ------------------------------------------------------------------ main entry
def normalise_field(key, value):
    """Return normalized value (kept separately from the original)."""
    if value is None:
        return None
    v = value.strip()
    if key in DATE_FIELDS:
        d, ok = N.parse_date(v)
        return d if ok else v
    if key in ("imo",):
        return re.sub(r"\D", "", v)
    if key in ("container_no",):
        parts = [N.norm_id(x) for x in re.split(r"[,;/\n]+|\s{2,}", v) if x.strip()]
        return ", ".join(p for p in parts if p)
    if key == "container_type":
        sizes = N.container_sizes(v)
        return ", ".join(sizes) if sizes else v
    if key == "bl_no":
        # "SUB/LA-231008 Ngày: 10/10/2023" -> the number only (date written next to it in manifests)
        v = re.split(r"\s+(?:ng[aà]y|date[d]?|dd|d\.)\b|\s+\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}|\s*\(", v, flags=re.I)[0]
        return re.sub(r"\s+", "", v).upper()
    if key == "call_sign":
        return re.sub(r"\s+", "", v).upper()
    return re.sub(r"\s+", " ", v)


def extract_document(doc_type, pages):
    """Return list of field dicts ready to be stored."""
    out = []
    hdr_keys = DOC_HEADER_FIELDS.get(doc_type, DOC_HEADER_FIELDS["OTHER"])
    hdr = extract_header(pages, hdr_keys)
    for k, d in hdr.items():
        out.append(dict(section="vessel", record_key="header", record_index=0, field_key=k, **d))

    if doc_type == "BILL_OF_LADING":
        rec = extract_bl_document(pages)
        rename = {"port_of_loading": "pol", "port_of_discharge": "pod"}
        for k, d in rec.items():
            out.append(dict(section="cargo", record_key="bl:1", record_index=1, field_key=rename.get(k, k), **d))
    for section in DOC_TABLES.get(doc_type, []):
        if doc_type == "BILL_OF_LADING":
            continue
        recs = extract_table(pages, section)
        if not recs and section == "cargo":
            recs = extract_block_manifest(pages)
        if section == "cargo" and doc_type == "CARGO_MANIFEST":
            # ports printed once in the manifest heading apply to every line that has no port column
            for key, hk in (("pol", "port_of_loading"), ("pod", "port_of_discharge")):
                if hk in hdr:
                    for r in recs:
                        r["fields"].setdefault(key, {**hdr[hk], "method": hdr[hk]["method"] + "-manifest-heading"})
        prefix = {"cargo": "mf", "empty_container": "ec", "port_calls": "port"}.get(section, section)
        for i, r in enumerate(recs, start=1):
            for k, d in r["fields"].items():
                out.append(dict(section=section, record_key=f"{prefix}:{i}", record_index=i, field_key=k, **d))
    for f in out:
        f["original_value"] = f.pop("value")
        f["value"] = normalise_field(f["field_key"], f["original_value"])
        f["field_label"] = FIELD_LABELS.get(f["field_key"], f["field_key"])
    return out


NUMBER_FIELDS = {"packages", "gross_weight", "net_weight", "measurement", "quantity", "gross_tonnage", "net_tonnage", "dwt", "loa",
                 "crew_count", "passenger_count", "draft_fwd", "draft_aft", "air_draft", "rob_do", "rob_fo", "rob_fw", "seq"}
ID_FIELDS = {"imo", "call_sign", "voyage_no", "bl_no", "container_no", "seal_no", "passport_no", "seaman_book_no", "un_no",
             "certificate_no", "hs_code", "port_code"}
CODE_FIELDS = {"container_type", "imdg_class", "packing_group", "gender", "security_level", "package_kind"}


def field_meta(key, original):
    """(data_type, unit) of a field - stored with every extracted value."""
    if key.endswith("_unit"):
        return "unit", None
    if key in DATE_FIELDS:
        return "date", None
    if key in NUMBER_FIELDS:
        _, u = N.parse_number(original)
        return "number", (u or None)
    if key in ID_FIELDS:
        return "identifier", None
    if key in CODE_FIELDS:
        return "code", None
    return "text", None
