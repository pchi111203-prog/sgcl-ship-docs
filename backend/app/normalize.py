"""Normalisation helpers and NSW code lists.

Code lists are read from the 'Declaration list' sheet of the NSW template at start-up,
so they always match the template in use.  Synonym tables below only translate common
document wordings to those codes; a suggestion is never exported unless staff confirm it.
"""
import re
import unicodedata
from datetime import datetime

MONTHS = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}
MONTHS.update({"SEPT": 9})


_QUOTES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'", "´": "'", "“": '"', "”": '"'})


def strip_accents(s):
    s = unicodedata.normalize("NFC", s).translate(_QUOTES)  # NFC keeps one character per letter; curly quotes -> straight
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").replace("đ", "d").replace("Đ", "D")


def norm_text(s):
    """Comparison key: upper-case, no accents, collapsed whitespace and punctuation."""
    if s is None:
        return ""
    s = strip_accents(str(s)).upper()
    s = re.sub(r"[\s\.,;:\-_/\\'\"()]+", " ", s)
    return s.strip()


def norm_id(s):
    """Identifiers (B/L, container, IMO): only letters & digits."""
    return re.sub(r"[^A-Z0-9]", "", strip_accents(str(s or "")).upper())


# ---------------------------------------------------------------- dates
_DATE_PATTERNS = [
    (r"(?P<d>\d{1,2})[/\.\-](?P<m>\d{1,2})[/\.\-](?P<y>\d{4})", "dmy"),
    (r"(?P<y>\d{4})[/\.\-](?P<m>\d{1,2})[/\.\-](?P<d>\d{1,2})", "ymd"),
    (r"(?P<d>\d{1,2})[\s\-/\.]*(?P<mon>[A-Za-z]{3,4})[A-Za-z]*[\s\-/\.,]*(?P<y>\d{4}|\d{2})\b", "dMy"),
    (r"(?P<mon>[A-Za-z]{3,4})[A-Za-z]*[\s\.]+(?P<d>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y>\d{4})", "Mdy"),
    (r"(?P<d>\d{1,2})[/\.\-](?P<m>\d{1,2})[/\.\-](?P<y>\d{2})\b", "dmy2"),
]
_TIME = re.compile(r"(?<!\d)(?P<h>[01]?\d|2[0-3])[:hH\.]?(?P<mi>[0-5]\d)(?:\s*(?:HRS|HOURS|H|LT|LOCAL))?(?!\d)", re.I)


def parse_date(s):
    """Return (normalized 'dd/mm/yyyy[ HH:MM]', ok). Day-first is assumed for numeric dates."""
    if not s:
        return None, False
    txt = str(s).strip()
    for pat, kind in _DATE_PATTERNS:
        m = re.search(pat, txt)
        if not m:
            continue
        g = m.groupdict()
        try:
            if "mon" in g and g.get("mon"):
                mon = MONTHS.get(g["mon"][:4].upper()) or MONTHS.get(g["mon"][:3].upper())
                if not mon:
                    continue
            else:
                mon = int(g["m"])
            y = int(g["y"])
            if y < 100:
                y += 2000
            d = int(g["d"])
            dt = datetime(y, mon, d)
        except (ValueError, TypeError):
            continue
        rest = txt[m.end():]
        tm = _TIME.search(rest)
        if tm and (":" in tm.group(0) or re.search(r"HRS|LT|H", tm.group(0), re.I) or len(rest.strip()) <= 6):
            return f"{dt:%d/%m/%Y} {int(tm.group('h')):02d}:{tm.group('mi')}", True
        before = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", txt[:m.start()])  # "08:00 hrs Ngày 18/10/2023"
        if before:
            return f"{dt:%d/%m/%Y} {int(before.group(1)):02d}:{before.group(2)}", True
        return f"{dt:%d/%m/%Y}", True
    return None, False


def date_key(s):
    v, ok = parse_date(s)
    return v if ok else norm_text(s)


# ---------------------------------------------------------------- numbers
UNIT_ALIASES = {
    "KGS": "KGM", "KG": "KGM", "KGM": "KGM", "KILOS": "KGM", "KILOGRAMS": "KGM",
    "MT": "TNE", "MTS": "TNE", "TON": "TNE", "TONS": "TNE", "TONNES": "TNE", "TNE": "TNE", "T": "TNE",
    "CBM": "MTQ", "M3": "MTQ", "MTQ": "MTQ", "CUM": "MTQ", "M³": "MTQ",
    "LTR": "LTR", "LTRS": "LTR", "L": "LTR", "LITRES": "LTR", "LITERS": "LTR",
    "PCS": "PCE", "PC": "PCE", "PCE": "PCE", "PIECES": "PCE",
}


def parse_number(s):
    """'12,345.50 KGS' -> (12345.5, 'KGS').  Returns (None, None) when no number."""
    if s is None:
        return None, None
    txt = str(s).strip()
    m = re.search(r"(-?\d[\d\s,\.]*)\s*([A-Za-z³]+)?", txt)
    if not m:
        return None, None
    num = m.group(1).strip().replace(" ", "")
    if "," in num and "." in num:
        num = num.replace(",", "") if num.rfind(".") > num.rfind(",") else num.replace(".", "").replace(",", ".")
    elif "," in num:
        parts = num.split(",")
        num = num.replace(",", "") if all(len(p) == 3 for p in parts[1:]) else num.replace(",", ".")
    elif num.count(".") > 1:
        num = num.replace(".", "")
    try:
        val = float(num)
    except ValueError:
        return None, None
    unit = (m.group(2) or "").upper() or None
    return val, unit


def fmt_number(v):
    if v is None:
        return None
    return str(int(v)) if float(v).is_integer() else f"{v:.3f}".rstrip("0").rstrip(".")


def unit_code(u):
    if not u:
        return None
    return UNIT_ALIASES.get(norm_id(u)) or UNIT_ALIASES.get(u.upper().strip())


def number_key(s):
    """Comparable (value, unit-code) for weights/measures; converts TNE->KGM for comparison only."""
    v, u = parse_number(s)
    if v is None:
        return None
    code = unit_code(u)
    if code == "TNE":
        return (round(v * 1000, 3), "KGM")
    return (round(v, 3), code)


# ---------------------------------------------------------------- check digits
def imo_valid(imo):
    d = re.sub(r"\D", "", str(imo or ""))
    if len(d) != 7:
        return False
    return sum(int(d[i]) * (7 - i) for i in range(6)) % 10 == int(d[6])


_ISO_VALS = {}
_v = 10
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    if _v % 11 == 0:
        _v += 1
    _ISO_VALS[_ch] = _v
    _v += 1


def container_valid(c):
    c = norm_id(c)
    if not re.fullmatch(r"[A-Z]{4}\d{7}", c):
        return False
    total = sum((_ISO_VALS[ch] if ch.isalpha() else int(ch)) * (2 ** i) for i, ch in enumerate(c[:10]))
    return (total % 11) % 10 == int(c[10])


CONTAINER_RE = re.compile(r"\b([A-Z]{4})\s?-?(\d{6})\s?-?(\d)\b")


def find_containers(text):
    out = []
    for m in CONTAINER_RE.finditer(text.upper()):
        c = m.group(1) + m.group(2) + m.group(3)
        if c not in out:
            out.append(c)
    return out


# ---------------------------------------------------------------- code lists (filled from template)
CODES = {"states": {}, "ranks": {}, "package_kinds": {}, "units": set(), "container_types": [], "passport_types": {}}

# English nationality / country wordings -> ISO alpha-2 (the NSW state list uses alpha-2 codes)
COUNTRY_SYNONYMS = {
    "VIETNAM": "VN", "VIET NAM": "VN", "VIETNAMESE": "VN", "VNM": "VN",
    "PHILIPPINES": "PH", "FILIPINO": "PH", "PHILIPPINE": "PH", "PHL": "PH",
    "CHINA": "CN", "CHINESE": "CN", "PRC": "CN", "CHN": "CN",
    "INDIA": "IN", "INDIAN": "IN", "IND": "IN",
    "INDONESIA": "ID", "INDONESIAN": "ID", "IDN": "ID",
    "MYANMAR": "MM", "BURMESE": "MM", "MYANMARESE": "MM", "MMR": "MM",
    "KOREA": "KR", "SOUTH KOREA": "KR", "KOREAN": "KR", "REPUBLIC OF KOREA": "KR", "KOR": "KR",
    "JAPAN": "JP", "JAPANESE": "JP", "JPN": "JP",
    "THAILAND": "TH", "THAI": "TH", "THA": "TH",
    "MALAYSIA": "MY", "MALAYSIAN": "MY", "MYS": "MY",
    "SINGAPORE": "SG", "SINGAPOREAN": "SG", "SGP": "SG",
    "RUSSIA": "RU", "RUSSIAN": "RU", "RUSSIAN FEDERATION": "RU", "RUS": "RU",
    "UKRAINE": "UA", "UKRAINIAN": "UA", "UKR": "UA",
    "PANAMA": "PA", "PANAMANIAN": "PA", "PAN": "PA",
    "LIBERIA": "LR", "LIBERIAN": "LR", "LBR": "LR",
    "MARSHALL ISLANDS": "MH", "MARSHALLESE": "MH", "MHL": "MH",
    "HONG KONG": "HK", "HONGKONG": "HK", "HKG": "HK",
    "TAIWAN": "TW", "TAIWANESE": "TW", "TWN": "TW",
    "BANGLADESH": "BD", "BANGLADESHI": "BD", "SRI LANKA": "LK", "SRI LANKAN": "LK",
    "PAKISTAN": "PK", "PAKISTANI": "PK", "CAMBODIA": "KH", "CAMBODIAN": "KH", "LAOS": "LA", "LAO": "LA",
    "GREECE": "GR", "GREEK": "GR", "CYPRUS": "CY", "CYPRIOT": "CY", "MALTA": "MT", "MALTESE": "MT",
    "TURKEY": "TR", "TURKISH": "TR", "ROMANIA": "RO", "ROMANIAN": "RO", "BULGARIA": "BG", "BULGARIAN": "BG",
    "CROATIA": "HR", "CROATIAN": "HR", "POLAND": "PL", "POLISH": "PL", "GERMANY": "DE", "GERMAN": "DE",
    "NETHERLANDS": "NL", "DUTCH": "NL", "NORWAY": "NO", "NORWEGIAN": "NO", "DENMARK": "DK", "DANISH": "DK",
    "UNITED KINGDOM": "GB", "BRITISH": "GB", "UK": "GB", "UNITED STATES": "US", "USA": "US", "AMERICAN": "US",
    "BAHAMAS": "BS", "BELIZE": "BZ", "TUVALU": "TV", "COMOROS": "KM", "MONGOLIA": "MN", "SIERRA LEONE": "SL",
    "PALAU": "PW", "TOGO": "TG", "GEORGIA": "GE", "LATVIA": "LV", "LITHUANIA": "LT", "ESTONIA": "EE",
    "AUSTRALIA": "AU", "AUSTRALIAN": "AU", "FRANCE": "FR", "FRENCH": "FR", "ITALY": "IT", "ITALIAN": "IT",
    "SPAIN": "ES", "SPANISH": "ES", "EGYPT": "EG", "EGYPTIAN": "EG", "MONTENEGRO": "ME", "SERBIA": "RS",
}

# Common crew-list rank wordings -> NSW rank codes ('Declaration list'!R:S)
RANK_SYNONYMS = {
    "MASTER": "CAP", "CAPTAIN": "CAP", "CAPT": "CAP", "THUYEN TRUONG": "CAP",
    "CHIEF OFFICER": "COF", "C O": "COF", "CO": "COF", "CH OFF": "COF", "CHIEF MATE": "COF", "DAI PHO": "COF", "1ST OFFICER": "COF",
    "2ND OFFICER": "2OF", "SECOND OFFICER": "2OF", "2 O": "2OF", "2O": "2OF", "2ND OFF": "2OF", "PHO HAI": "2OF",
    "3RD OFFICER": "3OF", "THIRD OFFICER": "3OF", "3 O": "3OF", "3O": "3OF", "3RD OFF": "3OF", "PHO BA": "3OF",
    "CHIEF ENGINEER": "CEG", "C E": "CEG", "CE": "CEG", "CH ENG": "CEG", "MAY TRUONG": "CEG",
    "2ND ENGINEER": "2EG", "SECOND ENGINEER": "2EG", "2 E": "2EG", "2E": "2EG", "2ND ENG": "2EG", "MAY HAI": "2EG",
    "3RD ENGINEER": "3EG", "THIRD ENGINEER": "3EG", "3 E": "3EG", "3E": "3EG", "3RD ENG": "3EG", "MAY BA": "3EG",
    "4TH ENGINEER": "XEG", "FOURTH ENGINEER": "XEG", "4 E": "XEG", "4E": "XEG", "MAY TU": "XEG",
    "RADIO OFFICER": "CRO", "R O": "CRO", "ELECTRICIAN": "ELE", "ELECTRICAL OFFICER": "ELE", "ETO": "ELE", "ELECT": "ELE",
    "BOSUN": "BSN", "BOATSWAIN": "BSN", "BSN": "BSN", "THUY THU TRUONG": "BSN",
    "AB": "ABS", "ABLE SEAMAN": "ABS", "A B": "ABS", "ABLE BODIED SEAMAN": "ABS",
    "OS": "COL", "O S": "COL", "ORDINARY SEAMAN": "COL",
    "FITTER": "FIT", "OILER": "OLR", "MOTORMAN": "OLR", "WIPER": "ABR",
    "CHIEF COOK": "CCK", "COOK": "COK", "MESSMAN": "SSD", "STEWARD": "SSD", "CHIEF STEWARD": "CSD",
    "PUMPMAN": "PUM", "PUMP MAN": "PUM", "WELDER": "WEL", "DECK CADET": "DOT", "ENGINE CADET": "EOT", "CADET": "DOT",
    "DOCTOR": "DTR", "NURSE": "NRS", "SUPERINTENDENT": "SRE", "OWNER REPRESENTATIVE": "SRE",
}

GENDER_MAP = {"M": "Nam/Man", "MALE": "Nam/Man", "MAN": "Nam/Man", "NAM": "Nam/Man",
              "F": "Nữ/Woman", "FEMALE": "Nữ/Woman", "WOMAN": "Nữ/Woman", "NU": "Nữ/Woman"}

PACKAGE_SYNONYMS = {
    "PACKAGES": "PK", "PACKAGE": "PK", "PKGS": "PK", "PKG": "PK", "CARTONS": "CT", "CARTON": "CT", "CTNS": "CT", "CTN": "CT",
    "BAGS": "BG", "BAG": "BG", "BALES": "BL", "BALE": "BL", "BUNDLES": "BE", "BUNDLE": "BE", "BDLS": "BE",
    "BOXES": "BX", "BOX": "BX", "CASES": "CS", "CASE": "CS", "COILS": "CL", "COIL": "CL", "DRUMS": "DR", "DRUM": "DR",
    "PALLETS": "PP", "PALLET": "PP", "PLTS": "PP", "PIECES": "PS", "PCS": "PS", "PIECE": "PS", "ROLLS": "RL", "ROLL": "RL",
    "CONTAINERS": "CN", "CONTAINER": "CN", "UNITS": "ZZ", "BULK": "NE", "IN BULK": "NE", "BARRELS": "BA", "CRATES": "CR",
}


def load_codes_from_template(path):
    import openpyxl
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["Declaration list"]
    states, ranks, pk, units, ct, pt = {}, {}, {}, set(), [], {}
    for r in ws.iter_rows(min_row=3, max_row=262, values_only=True):
        e, f = r[4], r[5]
        if e and f and not str(e).startswith("("):
            states[str(e)] = str(f)
        k = r[10]
        if k and not str(k).startswith("("):
            units.add(str(k).strip())
        if r[8] and isinstance(r[8], (int, float)):
            pt[str(int(r[8]))] = r[9]
        if r[14] and not str(r[14]).startswith("(") and r[14] != "Mã loại kiện":
            pk[str(r[14])] = r[15]
        if r[17] and not str(r[17]).startswith("(") and r[17] != "Code":
            ranks[str(r[17])] = str(r[18]).strip()
        if r[19] and not str(r[19]).startswith("(") and r[19] != "Code":
            ct.append(str(r[19]))
    wb.close()
    CODES.update(states=states, ranks=ranks, package_kinds=pk, units=units, container_types=ct, passport_types=pt)
    return CODES


def suggest_state(v):
    if not v:
        return None
    k = norm_text(v)
    if len(k) == 2 and k in CODES["states"]:
        return k
    if k in COUNTRY_SYNONYMS:
        return COUNTRY_SYNONYMS[k]
    for code, name in CODES["states"].items():
        if norm_text(name) == k:
            return code
    return None


def suggest_rank(v):
    if not v:
        return None
    k = norm_text(v)
    if k.replace(" ", "") in CODES["ranks"]:
        return k.replace(" ", "")
    if k in RANK_SYNONYMS:
        return RANK_SYNONYMS[k]
    for code, name in CODES["ranks"].items():
        if norm_text(name) == k:
            return code
    return None


def suggest_gender(v):
    return GENDER_MAP.get(norm_text(v)) if v else None


def suggest_package(v):
    if not v:
        return None
    k = norm_text(v)
    if k in CODES["package_kinds"]:
        return k
    return PACKAGE_SYNONYMS.get(k)


# ---------------------------------------------------------------- container size / type
# "1x40HC", "20GP", "40' HQ", "45 FT HC", ISO 6346 size-type codes "22G1", "45G1", "L5G1".
# ISO first character = length: 2 = 20 ft, 4 = 40 ft, L = 45 ft (45G1 is a 40 ft high cube!).
_CT_TEXT = re.compile(r"(?<![\d.,])(?:\d+\s*[X×]\s*)?(20|40|45)\s*(?:'|’|FT\b|FEET\b)?\s*(GP|DC|DV|HC|HQ|RF|RH|OT|FR|TK|ST|STD|NOR|DRY|REEFER|HIGH\s*CUBE)\b"
                      r"|(?<![\d.,])(20|40|45)\s*(?:'|’|FT\b|FEET\b|FOOT\b)", re.I)
_CT_ISO = re.compile(r"\b([24L])([0-9])([GRUPTHBVS])([0-9])\b")


def container_size(text):
    """Return the NSW container-type value ('Container 20/40/45') found in text, or None."""
    if not text:
        return None
    up = strip_accents(str(text)).upper()
    m = _CT_TEXT.search(up)
    size = (m.group(1) or m.group(3)) if m else None
    if not size:
        m = _CT_ISO.search(up)
        if m:
            size = {"2": "20", "4": "40", "L": "45"}[m.group(1)]
    if not size:
        return None
    code = f"Container {size}"
    if CODES["container_types"] and code not in CODES["container_types"]:
        return None
    return code


def container_sizes(text):
    """All container types mentioned in a text, in order, without duplicates."""
    out = []
    up = strip_accents(str(text or "")).upper()
    for m in list(_CT_TEXT.finditer(up)):
        c = f"Container {m.group(1) or m.group(3)}"
        if c not in out:
            out.append(c)
    if not out:
        for m in _CT_ISO.finditer(up):
            c = f"Container {({'2': '20', '4': '40', 'L': '45'})[m.group(1)]}"
            if c not in out:
                out.append(c)
    return out


_VESSEL_PREFIX = re.compile(r"^(M\s*/\s*V|M\.\s*V\.?|MV|M\s*/\s*T|M\.\s*T\.?|MT|M\s*/\s*S|MS|SS|S\.S\.|TB|T/B|TV|SB|LPG/C|LNG/C|MY)\s+", re.I)


def vessel_key(s):
    """Comparison key for vessel names: 'MV VINH QUANG GOLD', 'M/V Vinh Quang Gold', 'VINH QUANG GOLD' -> 'VINH QUANG GOLD'."""
    t = strip_accents(str(s or "")).strip()
    t = _VESSEL_PREFIX.sub("", t)
    return norm_text(t)


# ---------------------------------------------------------------- Vietnamese <-> English shipping terms
# Used only to COMPARE free text written in two languages (parties, goods descriptions). Extend as needed.
# Keys/values are accent-free upper case; longer phrases are applied first.
GLOSSARY_VI_EN = {
    "THEO LENH CUA": "TO THE ORDER OF", "THEO LENH": "TO THE ORDER OF", "GIAO THEO LENH": "TO THE ORDER OF",
    "NGAN HANG THUONG MAI CO PHAN": "JOINT STOCK COMMERCIAL BANK", "NGAN HANG TMCP": "JOINT STOCK COMMERCIAL BANK",
    "NGAN HANG": "BANK", "TMCP": "JOINT STOCK COMMERCIAL", "THUONG MAI CO PHAN": "JOINT STOCK COMMERCIAL", "CO PHAN": "JOINT STOCK",
    "NGOAI THUONG": "FOREIGN TRADE", "CONG THUONG": "INDUSTRY AND TRADE", "DAU TU VA PHAT TRIEN": "INVESTMENT AND DEVELOPMENT",
    "NONG NGHIEP VA PHAT TRIEN NONG THON": "AGRICULTURE AND RURAL DEVELOPMENT", "VIET NAM": "VIETNAM", "CHI NHANH": "BRANCH", "CN": "BRANCH",
    "CONG TY TNHH": "COMPANY LIMITED", "CONG TY CO PHAN": "JOINT STOCK COMPANY", "CONG TY": "COMPANY", "TNHH": "LIMITED",
    "XUAT NHAP KHAU": "IMPORT EXPORT", "THUONG MAI": "TRADING", "DICH VU": "SERVICE", "VAN TAI BIEN": "SHIPPING", "VAN TAI": "TRANSPORT",
    "NGO HAT VANG": "YELLOW CORN", "NGO HAT": "CORN", "NGO": "CORN", "LUA MI": "WHEAT", "GAO": "RICE", "DAU NANH": "SOYBEAN",
    "BA DAU NANH": "SOYBEAN MEAL", "KHO DAU": "SOYBEAN MEAL", "SAN LAT": "CASSAVA CHIPS", "SAN": "CASSAVA", "DUONG": "SUGAR",
    "PHAN BON": "FERTILIZER", "PHAN URE": "UREA", "URE": "UREA", "XI MANG": "CEMENT", "CLINKER": "CLINKER", "THAN DA": "COAL", "THAN": "COAL",
    "QUANG SAT": "IRON ORE", "THEP CUON": "STEEL COILS", "THEP": "STEEL", "SAT": "IRON", "GO": "TIMBER", "DAM GO": "WOOD CHIPS",
    "MUOI": "SALT", "CAT": "SAND", "DA": "STONE", "THUC AN CHAN NUOI": "ANIMAL FEED", "THUC AN GIA SUC": "ANIMAL FEED",
    "NGUYEN LIEU": "RAW MATERIAL", "HANG ROI": "IN BULK", "ROI": "BULK", "DONG BAO": "IN BAGS", "BAO": "BAGS", "CONTAINER": "CONTAINER",
}
_GLOSS = sorted(GLOSSARY_VI_EN.items(), key=lambda kv: -len(kv[0]))
_STOP = {"TO", "THE", "OF", "AND", "IN", "FOR", "ON", "AT", "BY", "A", "AN", "ORDER", "CO", "LTD", "LIMITED", "COMPANY", "JSC", "BRANCH",
         "INC", "CORP", "PTE", "PT", "TBK", "NO", "ST", "STREET", "ROAD", "WARD", "DIST", "DISTRICT", "CITY", "PROVINCE", "MST", "TAX",
         "CODE", "ADDRESS", "TEL", "FAX", "DUNG", "LAM", "HAT", "LOAI", "HANG", "VA", "CUA", "TAI", "SO"}


def to_english_terms(s):
    """Accent-free upper text with known Vietnamese shipping phrases replaced by their English equivalent."""
    t = " " + norm_text(s) + " "
    for vi, en in _GLOSS:
        t = t.replace(f" {vi} ", f" {en} ")
    return t.strip()


def significant_words(s):
    return {w for w in to_english_terms(s).split() if w not in _STOP and len(w) > 1 and not w.isdigit()}


def bilingual_match(a, b):
    """Evidence that two texts in different languages name the same thing, else None.
    1) the main phrase (before '(' / ':' / ';' / ',') of one side, translated, is contained in the other side;
    2) a translation/brand written in brackets on one side, e.g. '(Yellow Corn in bulk)', '(Vietcombank)', is found on the other."""
    wa, wb = significant_words(a), significant_words(b)
    for x, ywords in ((a, wb), (b, wa)):
        head = re.split(r"[(:;,.]|\s-\s|\bPACKING\b", str(x or ""), maxsplit=1, flags=re.I)[0]
        hw = significant_words(head)
        if len(hw) >= 2 and hw <= ywords:
            return " ".join(w for w in to_english_terms(head).split() if w in hw)
        for inner in re.findall(r"\(([^)]{3,80})\)", str(x or "")):
            iw = significant_words(inner)
            if iw and iw <= ywords and (len(iw) >= 2 or any(len(w) >= 7 for w in iw)):
                return inner.strip()
    return None


_NOTHING = re.compile(r"^\s*(?:(?:khong|ko)\b.*|nothing(?:\s+to\s+declare)?\b.*|none\b.*|nil\b.*|no\s+(?:dutiable|effects|declarable)\b.*|n/?a|-+|\.+)\s*$", re.I)


def nil_if_nothing(v):
    """Crew's effects: 'Không có hành lý vượt định mức' / 'Nothing to declare' / 'None' -> 'NIL' (NSW convention)."""
    if v is None:
        return v
    s = strip_accents(str(v)).strip()
    return "NIL" if s == "" or _NOTHING.match(s) and not re.search(r"\d", s) else v
