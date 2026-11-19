"""Generate SAMPLE document sets (fictitious vessels) for testing the 3 required scenarios.

All generated documents carry the watermark 'SAMPLE / DỮ LIỆU MẪU' and voyages created
from them are flagged is_sample=1, so they are never confused with real data.

  scenario 1 - complete & consistent set (text PDFs + DOCX + XLSX)
  scenario 2 - set with discrepancies (B/L gross weight vs manifest, container no.,
               duplicate crew passport, a B/L belonging to another vessel)
  scenario 3 - scanned set (image-only PDF + PNG) with missing information
"""
import io
import os
import random

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

STY = getSampleStyleSheet()

VESSELS = {
    1: dict(name="SAMPLE TEAL STAR", imo="9395044", call_sign="3EXA7", flag="PANAMA", voyage="2611N", gt="9,940", nt="5,231"),
    2: dict(name="SAMPLE MEKONG PEARL", imo="9187356", call_sign="XVQB9", flag="VIETNAM", voyage="045S", gt="6,543", nt="3,412"),
    3: dict(name="SAMPLE CUU LONG BREEZE", imo="9406087", call_sign="9V2210", flag="SINGAPORE", voyage="118W", gt="17,068", nt="7,889"),
}

FIRST = ["NGUYEN VAN", "TRAN MINH", "LE HOANG", "PHAM DUC", "HOANG THANH", "VU QUOC", "DANG VAN", "BUI XUAN", "DO MANH", "NGO TRUNG", "DUONG VAN", "LY THANH"]
LAST = ["AN", "BINH", "CUONG", "DUNG", "HAI", "HUNG", "KHOA", "LONG", "MINH", "NAM", "PHUC", "QUANG", "SON", "TAI", "THANG", "TUAN", "VIET"]
RANKS = ["MASTER", "CHIEF OFFICER", "2ND OFFICER", "3RD OFFICER", "CHIEF ENGINEER", "2ND ENGINEER", "3RD ENGINEER", "4TH ENGINEER",
         "ELECTRICIAN", "BOSUN", "AB", "AB", "AB", "OS", "OS", "FITTER", "OILER", "OILER", "WIPER", "CHIEF COOK", "MESSMAN", "DECK CADET"]


def _iso_container(prefix, serial):
    from .normalize import _ISO_VALS
    s = f"{prefix}{serial:06d}"
    total = sum((_ISO_VALS[ch] if ch.isalpha() else int(ch)) * (2 ** i) for i, ch in enumerate(s))
    return s + str((total % 11) % 10)


def _crew(n, seed):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        nat = "VIETNAMESE" if i % 5 else rnd.choice(["FILIPINO", "MYANMAR", "INDIAN"])
        out.append(dict(name=f"{rnd.choice(FIRST)} {rnd.choice(LAST)}", rank=RANKS[i % len(RANKS)], nat=nat,
                        dob=f"{rnd.randint(1,28):02d}/{rnd.randint(1,12):02d}/{rnd.randint(1965,2002)}",
                        pob=rnd.choice(["HAI PHONG", "NAM DINH", "THANH HOA", "NGHE AN", "HO CHI MINH", "MANILA", "YANGON"]),
                        sex="M" if i % 9 else "F", passport=f"C{rnd.randint(1000000,9999999)}",
                        expiry=f"{rnd.randint(1,28):02d}/{rnd.randint(1,12):02d}/{rnd.randint(2027,2034)}",
                        sbook=f"HP-{rnd.randint(10000,99999)}"))
    return out


def _cargo(seed, n=6):
    rnd = random.Random(seed)
    goods = ["RICE IN PP BAGS", "FROZEN SHRIMP", "STEEL COILS", "GARMENTS", "FURNITURE PARTS", "PAINT (FLAMMABLE)", "RUBBER SHEETS", "CASHEW NUTS"]
    out = []
    for i in range(n):
        g = goods[i % len(goods)]
        out.append(dict(bl=f"SGCL{seed}{i+1:03d}HCM", shipper=f"{rnd.choice(['SAIGON', 'MEKONG', 'ORIENT', 'PACIFIC'])} EXPORT CO., LTD",
                        consignee=f"{rnd.choice(['BANGKOK', 'MANILA', 'BUSAN', 'KAOHSIUNG'])} TRADING CORP", notify="SAME AS CONSIGNEE",
                        desc=g, pkgs=str(rnd.randint(50, 900)), kind="BAGS" if "BAGS" in g else "PACKAGES",
                        gw=f"{rnd.randint(8000, 26000):,}.{rnd.randint(0,99):02d}", meas=f"{rnd.randint(20, 66)}.{rnd.randint(0,9)}",
                        cont=_iso_container(rnd.choice(["MSKU", "TGHU", "CAIU", "SEGU"]), rnd.randint(100000, 999999)),
                        seal=f"SL{rnd.randint(100000, 999999)}", pol="SINGAPORE (SGSIN)", pod="CAT LAI, HO CHI MINH (VNCLI)",
                        un="1263" if "PAINT" in g else None))
    return out


def _doc(path, story, land=False):
    d = SimpleDocTemplate(path, pagesize=landscape(A4) if land else A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm)

    def mark(c, _d):
        c.saveState()
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(colors.red)
        c.drawString(12 * mm, 6 * mm, "SAMPLE DOCUMENT - DU LIEU MAU - FOR SYSTEM TESTING ONLY")
        c.restoreState()

    d.build(story, onFirstPage=mark, onLaterPages=mark)


def _kv(lines):
    return [Paragraph(l, STY["Normal"]) for l in lines]


def _grid(header, rows_, widths=None, font=7):
    t = Table([header] + rows_, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.black), ("FONTSIZE", (0, 0), (-1, -1), font),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


def gen_gd(path, v, crew_n, eta, last_port="SINGAPORE", next_port="BANGKOK", omit=()):
    lines = ["<b>GENERAL DECLARATION</b> (IMO FAL FORM 1)", "Arrival", ""]
    data = [("Name of ship", v["name"]), ("IMO number", v["imo"]), ("Call sign", v["call_sign"]), ("Flag State of ship", v["flag"]),
            ("Voyage number", v["voyage"]), ("Port of arrival", "HO CHI MINH CITY (VNCLI)"), ("Date and time of arrival", eta),
            ("Last port of call", last_port), ("Next port of call", next_port), ("Name of master", "CAPT. NGUYEN VAN AN"),
            ("Gross tonnage", v["gt"]), ("Net tonnage", v["nt"]), ("Number of crew", str(crew_n)), ("Number of passengers", "0"),
            ("Brief description of the cargo", "GENERAL CARGO IN CONTAINERS"), ("Position of the ship in the port", "CAT LAI TERMINAL BERTH 3")]
    for k, val in data:
        if k not in omit:
            lines.append(f"{k}: {val}")
    _doc(path, _kv(lines))


def gen_noa(path, v, eta):
    lines = ["<b>NOTICE OF ARRIVAL</b>", "To: Saigon Port Authority", "",
             f"Vessel name: {v['name']}", f"IMO No: {v['imo']}", f"Call sign: {v['call_sign']}", f"Flag: {v['flag']}",
             f"Voyage No: {v['voyage']}", f"Port of arrival: HO CHI MINH CITY (VNCLI)", f"ETA: {eta}", "Last port of call: SINGAPORE",
             "Next port of call: BANGKOK", f"Gross tonnage: {v['gt']}", f"Net tonnage: {v['nt']}", "Draft fwd: 7.20 M", "Draft aft: 8.10 M",
             "Air draft: 38.5 M", "ROB FO: 412.5 MT", "ROB DO: 58.2 MT", "ROB FW: 120 MT", "Purpose of call: DISCHARGING / LOADING"]
    _doc(path, _kv(lines))


def gen_tonnage(path, v, imo=None):
    lines = ["<b>INTERNATIONAL TONNAGE CERTIFICATE (1969)</b>", "", f"Name of ship: {v['name']}", f"IMO number: {imo or v['imo']}",
             f"Call sign: {v['call_sign']}", f"Port of registry: {v['flag']}", f"Gross tonnage: {v['gt']}", f"Net tonnage: {v['nt']}",
             "Date of issue: 14/03/2019", "Certificate No: ITC-2019-0042"]
    _doc(path, _kv(lines))


def gen_manifest(path, v, cargo):
    story = _kv(["<b>CARGO MANIFEST</b>", f"Vessel name: {v['name']}   Voyage No: {v['voyage']}", "Port of loading: SINGAPORE   Port of discharge: HO CHI MINH", ""])
    hdr = ["B/L No.", "Shipper", "Consignee", "Notify party", "Description of goods", "No. of packages", "Kind of packages",
           "Gross weight (KGS)", "Measurement (CBM)", "Container No.", "Seal No.", "Port of loading", "Port of discharge"]
    rws = [[c["bl"], Paragraph(c["shipper"], STY["Normal"]), Paragraph(c["consignee"], STY["Normal"]), c["notify"], Paragraph(c["desc"], STY["Normal"]),
            c["pkgs"], c["kind"], c["gw"], c["meas"], c["cont"], c["seal"], c["pol"], c["pod"]] for c in cargo]
    for r in rws:
        for i in (1, 2, 4):
            r[i] = r[i].text
    story.append(_grid(hdr, rws, font=6))
    _doc(path, story, land=True)


def gen_bl(path, v, c, vessel_name=None, voyage=None, gw=None, cont=None):
    lines = ["<b>BILL OF LADING</b>", f"B/L No: {c['bl']}", "", "Shipper:", c["shipper"], "", "Consignee:", c["consignee"], "",
             "Notify party:", c["notify"], "", f"Ocean vessel: {vessel_name or v['name']}", f"Voyage No: {voyage or v['voyage']}",
             f"Port of loading: {c['pol']}", f"Port of discharge: {c['pod']}", "",
             f"Description of goods: {c['desc']}", f"Number of packages: {c['pkgs']} {c['kind']}", f"Gross weight: {gw or c['gw']} KGS",
             f"Measurement: {c['meas']} CBM", f"Container / Seal: {cont or c['cont']} / {c['seal']}", "", "SHIPPED ON BOARD 05/11/2026",
             "FREIGHT PREPAID"]
    _doc(path, _kv(lines))


def gen_crew(path, v, crew):
    story = _kv(["<b>CREW LIST</b> (IMO FAL FORM 5)", f"Name of ship: {v['name']}   IMO number: {v['imo']}   Call sign: {v['call_sign']}",
                 f"Flag State of ship: {v['flag']}   Voyage No: {v['voyage']}", ""])
    hdr = ["No.", "Family name, given names", "Rank or rating", "Nationality", "Date of birth", "Place of birth", "Sex",
           "Passport No.", "Expiry date", "Seaman book No."]
    rws = [[str(i + 1), c["name"], c["rank"], c["nat"], c["dob"], c["pob"], c["sex"], c["passport"], c["expiry"], c["sbook"]] for i, c in enumerate(crew)]
    story.append(_grid(hdr, rws, font=9))
    _doc(path, story, land=True)


def gen_dg(path, v, cargo):
    story = _kv(["<b>DANGEROUS GOODS MANIFEST</b> (IMO FAL FORM 7)", f"Name of ship: {v['name']}   Voyage No: {v['voyage']}", ""])
    hdr = ["B/L No.", "Container No.", "Seal No.", "UN No.", "Class", "Proper shipping name", "Packing group", "No. of packages", "Gross weight (KGS)", "Stowage position"]
    rws = [[c["bl"], c["cont"], c["seal"], c["un"], "3", c["desc"], "II", c["pkgs"], c["gw"], "030282"] for c in cargo if c["un"]]
    story.append(_grid(hdr, rws))
    _doc(path, story, land=True)


def gen_stores_xlsx(path, v):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Stores"
    ws.append(["SHIP'S STORES DECLARATION (IMO FAL FORM 3) - SAMPLE / DU LIEU MAU"])
    ws.append([f"Name of ship: {v['name']}", f"Voyage No: {v['voyage']}"])
    ws.append([])
    ws.append(["No.", "Name of article", "Quantity", "Unit", "Location on board"])
    for i, (a, q, u) in enumerate([("RICE", 500, "KGS"), ("FRESH VEGETABLES", 120, "KGS"), ("CIGARETTES", 40, "CTNS"), ("WHISKY", 24, "BTLS"), ("FRESH WATER", 120, "MT")]):
        ws.append([i + 1, a, q, u, "BONDED STORE" if u in ("CTNS", "BTLS") else "PROVISION ROOM"])
    wb.save(path)


def gen_effects_docx(path, v, crew):
    import docx
    d = docx.Document()
    d.add_paragraph("CREW'S EFFECTS DECLARATION (IMO FAL FORM 4) - SAMPLE / DU LIEU MAU")
    d.add_paragraph(f"Name of ship: {v['name']}")
    d.add_paragraph(f"Voyage No: {v['voyage']}")
    t = d.add_table(rows=1, cols=4)
    for i, h in enumerate(["No.", "Family name, given names", "Rank or rating", "Effects ineligible for relief from customs duties"]):
        t.rows[0].cells[i].text = h
    for i, c in enumerate(crew[:6]):
        cells = t.add_row().cells
        cells[0].text, cells[1].text, cells[2].text, cells[3].text = str(i + 1), c["name"], c["rank"], ["LAPTOP 1 PC", "MOBILE PHONE 1 PC", "CIGARETTES 1 CTN"][i % 3]
    d.save(path)


def _scan(pdf_path, out_pdf, out_png=None, seed=0):
    """Render a PDF to a noisy, slightly rotated image-only PDF (simulated scan)."""
    import pymupdf as fitz
    from PIL import Image, ImageFilter
    rnd = random.Random(seed)
    src = fitz.open(pdf_path)
    imgs = []
    for p in src:
        pix = p.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
        img = img.rotate(rnd.uniform(-0.8, 0.8), expand=True, fillcolor=255).filter(ImageFilter.GaussianBlur(0.5))
        px = img.load()
        for _ in range(img.width * img.height // 400):
            x, y = rnd.randrange(img.width), rnd.randrange(img.height)
            px[x, y] = rnd.choice([0, 90, 200])
        imgs.append(img)
    imgs[0].save(out_pdf, save_all=True, append_images=imgs[1:], resolution=300)
    if out_png:
        imgs[0].save(out_png)


def generate(scenario, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    v = VESSELS[scenario]
    crew = _crew(22 if scenario != 3 else 14, seed=scenario)
    cargo = _cargo(scenario)
    eta = "20/11/2026 14:00"
    files = []

    def p(name):
        files.append(os.path.join(out_dir, name))
        return files[-1]

    if scenario in (1, 2):
        gen_gd(p("01_general_declaration.pdf"), v, len(crew), eta)
        gen_noa(p("02_notice_of_arrival.pdf"), v, eta if scenario == 1 else "21/11/2026 06:00")
        gen_tonnage(p("03_tonnage_certificate.pdf"), v)
        gen_manifest(p("04_cargo_manifest.pdf"), v, cargo)
        for i, c in enumerate(cargo[:3]):
            gw = cont = None
            if scenario == 2 and i == 0:
                gw = "19,999.00"  # differs from manifest
            if scenario == 2 and i == 1:
                cont = _iso_container("TGHU", 123456)  # different container number
            gen_bl(p(f"05_bill_of_lading_{i+1}.pdf"), v, c, gw=gw, cont=cont)
        if scenario == 2:
            other = VESSELS[3]
            gen_bl(p("05_bill_of_lading_OTHER_VESSEL.pdf"), v, cargo[4], vessel_name=other["name"], voyage=other["voyage"])
            crew[7]["passport"] = crew[3]["passport"]  # duplicate passport in crew list
        gen_crew(p("06_crew_list.pdf"), v, crew)
        gen_dg(p("07_dangerous_goods_manifest.pdf"), v, cargo)
        gen_stores_xlsx(p("08_ships_stores.xlsx"), v)
        gen_effects_docx(p("09_crew_effects.docx"), v, crew)
    else:
        tmp = os.path.join(out_dir, "_tmp")
        os.makedirs(tmp, exist_ok=True)
        gen_gd(os.path.join(tmp, "gd.pdf"), v, len(crew), eta, omit=("Date and time of arrival", "Number of crew"))
        _scan(os.path.join(tmp, "gd.pdf"), p("01_general_declaration_SCAN.pdf"), seed=3)
        gen_crew(os.path.join(tmp, "crew.pdf"), v, crew)
        _scan(os.path.join(tmp, "crew.pdf"), p("02_crew_list_SCAN.pdf"), seed=4)
        gen_tonnage(os.path.join(tmp, "ton.pdf"), v)
        _scan(os.path.join(tmp, "ton.pdf"), p("03_tonnage_certificate_SCAN.pdf"), out_png=p("04_tonnage_certificate_PHOTO.png"), seed=5)
        import shutil
        shutil.rmtree(tmp)
    return files
