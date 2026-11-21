"""End-to-end tests of the 3 required scenarios + voyage isolation, through the REST API.

Run:  cd backend && SGCL_DATA_DIR=$(mktemp -d) python -m pytest -q tests
"""
import json
import os
import tempfile
import time

os.environ.setdefault("SGCL_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SGCL_SKIP_LIBREOFFICE", "0")
os.environ.setdefault("SGCL_STAFF_PASSWORD", "staff123")
os.environ.setdefault("SGCL_ADMIN_PASSWORD", "admin123")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
client.__enter__()  # run startup
H = {}


def login(user="staff", pw="staff123"):
    r = client.post("/api/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    H["Authorization"] = "Bearer " + r.json()["token"]


def wait_docs(vid, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        docs = client.get(f"/api/voyages/{vid}/documents", headers=H).json()["documents"]
        if docs and all(d["status"] in ("EXTRACTED", "ERROR", "SPLIT") for d in docs):
            return docs
        time.sleep(1)
    raise AssertionError("timeout")


def sample(n):
    vid = client.post(f"/api/samples/{n}", headers=H).json()["voyage_id"]
    return vid, wait_docs(vid)


def confirm_all(vid):
    ids = [f["id"] for f in client.get(f"/api/voyages/{vid}/fields", headers=H).json()["fields"]]
    client.post("/api/fields/confirm", json={"ids": ids}, headers=H)


def results(vid):
    return client.post(f"/api/voyages/{vid}/crosscheck", headers=H).json()["results"]


login()


def test_scenario1_consistent_set_exports():
    vid, docs = sample(1)
    types = {d["original_name"]: d["doc_type"] for d in docs}
    assert types["01_general_declaration.pdf"] == "GENERAL_DECLARATION"
    assert types["04_cargo_manifest.pdf"] == "CARGO_MANIFEST"
    assert types["06_crew_list.pdf"] == "CREW_LIST"
    assert types["08_ships_stores.xlsx"] == "SHIP_STORES"
    assert types["09_crew_effects.docx"] == "CREW_EFFECTS"
    assert all(d["status"] == "EXTRACTED" for d in docs)
    res = results(vid)
    blocking = [r for r in res if r["blocking"]]
    assert not blocking, blocking
    assert any(r["status"] == "PASSED" and r["field_key"] == "gross_weight" for r in res)
    assert any(r["status"] == "PASSED" and r["field_key"] == "crew_count" for r in res)
    rd = client.get(f"/api/voyages/{vid}/export/readiness", headers=H).json()
    assert not rd["ready"] and rd["unconfirmed_count"] > 0  # must confirm first
    # container type: 5 lines read from the manifest (ISO codes), line 6 has none -> warning, staff chooses
    assert any("1 dòng chưa có loại container" in w for w in rd["warnings"]), rd["warnings"]
    fields = client.get(f"/api/voyages/{vid}/fields", headers=H).json()["fields"]
    mf = [f for f in fields if f["doc_type"] == "CARGO_MANIFEST" and f["section"] == "cargo"]
    ct = {f["record_key"]: (f["original_value"], f["value"]) for f in mf if f["field_key"] == "container_type"}
    assert ct["mf:1"] == ("45G1", "Container 40") and ct["mf:2"] == ("22G1", "Container 20") and "mf:6" not in ct
    assert any(r["status"] == "PASSED" and r["field_key"] == "container_type" for r in res)
    r6 = client.post(f"/api/voyages/{vid}/fields", headers=H, json={"document_id": mf[0]["document_id"], "section": "cargo",
                                                                      "record_key": "mf:6", "field_key": "container_type", "value": "Container 20"})
    assert r6.status_code == 200, r6.text
    confirm_all(vid)
    results(vid)
    client.put(f"/api/voyages/{vid}/export/options", json={"sign_place": "TP. Hồ Chí Minh", "sign_date": "19/11/2026",
                                                            "signer": "Đại lý/ShipAgency", "crew_passport_type": "1"}, headers=H)
    rd = client.get(f"/api/voyages/{vid}/export/readiness", headers=H).json()
    assert rd["ready"], rd["blockers"]
    r = client.post(f"/api/voyages/{vid}/export", json={}, headers=H)
    assert r.status_code == 200, r.text
    rep = r.json()["report"]
    failed = [c for c in rep["checks"] if not c["ok"]]
    assert not failed, failed
    assert client.get(f"/api/voyages/{vid}", headers=H).json()["progress"]["progress"] == 100
    assert rep["rows"]["Crew list"] == 22 and rep["rows"]["Goods Declaration"] == 6
    # read back the file
    import openpyxl, warnings
    token = H["Authorization"].split()[1]
    data = client.get(f"/api/exports/{r.json()['id']}/download?token={token}").content
    p = os.path.join(tempfile.mkdtemp(), "out.xlsx")
    open(p, "wb").write(data)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(p)
    ws = wb["Crew list"]
    assert ws["C11"].value == "CAP" and ws["D11"].value in ("PH", "VN", "MM", "IN")
    assert ws["A32"].value and ws["A33"].value is None  # 22 rows: 11..32
    assert wb["General Declaration"]["B24"].value == "20/11/2026 14:00"
    assert wb["General Declaration"]["B6"].value == "SINGAPORE"
    assert wb["Goods Declaration"]["A10"].value.startswith("SGCL1")
    assert wb["Goods Declaration"]["O10"].value == "KGM"
    assert wb["Goods Declaration"]["V10"].value == "Container 40" and wb["Goods Declaration"]["V11"].value == "Container 20"
    assert wb["Goods Declaration"]["V15"].value == "Container 20"  # chosen by staff
    assert wb["Goods Declaration"]["P10"].value == "VNCLI" and wb["Goods Declaration"]["R10"].value == "SGSIN"
    assert wb["Passenger list"]["A11"].value is None  # sample row cleared, no passengers
    eff = wb["Crew's Effects Declaration"]
    assert eff["A11"].value and eff["B11"].value and eff["C11"].value == "CAP"
    assert eff["A11"].value == "-"  # SGCL convention from the filled NSW file: Họ = "-", Tên = full name
    assert wb["General Declaration"]["B33"].value == "19/11/2026" and wb["General Declaration"]["B34"].value == "Đại lý/ShipAgency"
    assert wb["General Declaration"]["B16"].value == "1" and wb["General Declaration"]["B17"].value == "0"  # attached declarations 1/0
    assert wb["Cargo manifest"].sheet_state == "hidden"
    assert wb.sheetnames[0] == "Declaration list" and len(wb.sheetnames) == 20
    globals()["VID1"] = vid


def test_scenario2_discrepancies_detected():
    vid, docs = sample(2)
    res = results(vid)
    mism = [r for r in res if r["status"] == "MISMATCH"]
    gw = [r for r in mism if r["field_key"] == "gross_weight"]
    assert gw, "gross weight mismatch not detected"
    assert gw[0]["value1"] and gw[0]["value2"] and gw[0]["doc1_name"] and gw[0]["doc2_name"] and gw[0]["page1"]
    assert any(r["field_key"] == "container_no" for r in mism)
    assert any(r["status"] == "WRONG_VOYAGE" for r in res)
    assert any(r["status"] == "DUPLICATE" and r["field_key"] == "passport_no" for r in res)
    assert any(r["status"] == "MISMATCH" and r["field_key"] == "eta" for r in res)
    confirm_all(vid)
    res = results(vid)
    gw = [r for r in res if r["status"] == "MISMATCH" and r["field_key"] == "gross_weight"]
    r = client.post(f"/api/voyages/{vid}/export", json={}, headers=H)
    assert r.status_code == 409  # blocked
    # staff resolves the GW mismatch by choosing the manifest value (originals kept)
    rid = gw[0]["id"]
    rr = client.post(f"/api/crosscheck/{rid}/resolve", json={"action": "use1", "note": "Theo manifest đã kiểm tra với hãng tàu"}, headers=H)
    assert rr.status_code == 200
    res2 = client.get(f"/api/voyages/{vid}/crosscheck", headers=H).json()["results"]
    assert not [r for r in res2 if r["status"] == "MISMATCH" and r["field_key"] == "gross_weight"]
    f = [f for f in client.get(f"/api/voyages/{vid}/fields", headers=H).json()["fields"] if f["id"] == gw[0]["field2_id"]][0]
    assert f["original_value"] != f["value"]  # original kept
    log = client.get(f"/api/voyages/{vid}/log", headers=H).json()
    assert any(l["action"] == "RESOLVE_MISMATCH" for l in log)
    # supervisor override still possible, with reason
    r = client.post(f"/api/voyages/{vid}/export", json={"override_username": "staff", "override_password": "staff123", "override_reason": "x"}, headers=H)
    assert r.status_code == 403
    r = client.post(f"/api/voyages/{vid}/export", json={"override_username": "admin", "override_password": "admin123", "override_reason": "Test ngoại lệ"}, headers=H)
    assert r.status_code == 200, r.text


def test_scenario3_scanned_missing():
    vid, docs = sample(3)
    assert all("ocr" in (d["extraction_method"] or "") for d in docs if d["status"] == "EXTRACTED" and d["doc_type"] != "OTHER")
    res = results(vid)
    fields = client.get(f"/api/voyages/{vid}/fields", headers=H).json()["fields"]
    gd = [f for f in fields if f["doc_type"] == "GENERAL_DECLARATION"]
    assert not any(f["field_key"] == "eta" for f in gd)          # not invented
    assert not any(f["field_key"] == "crew_count" for f in gd)   # not invented
    assert any(r["status"] == "NOT_AVAILABLE" and r["field_key"] == "eta" for r in res)
    # blanks in the crew list (the only source) are summarised once, not listed per member as issues
    assert any(r["group_name"].startswith("3") and r["field_key"] == "crew_blanks" and r["status"] == "NOT_AVAILABLE" for r in res)
    assert not any(r["group_name"].startswith("3") and r["status"] == "MISSING_INFO" and "thiếu" in r["message"] for r in res)
    assert all(f["method"].startswith("ocr") for f in fields if f["document_id"])
    # staff adds a crew member manually
    r = client.post(f"/api/voyages/{vid}/records", json={"section": "crew", "fields": {"full_name": "TEST MANUAL", "rank": "MASTER"}}, headers=H)
    assert r.status_code == 200


def test_voyages_isolated():
    a = client.post("/api/voyages", json={"vessel_name": "ISOLATION TEST A", "voyage_no": "001"}, headers=H).json()
    b = client.post("/api/voyages", json={"vessel_name": "ISOLATION TEST A", "voyage_no": "002"}, headers=H).json()
    assert a["voyage_code"] != b["voyage_code"]
    assert client.get(f"/api/voyages/{b['id']}/fields", headers=H).json()["fields"] == []
    assert client.get(f"/api/voyages/{b['id']}/documents", headers=H).json()["documents"] == []
    rd = client.get(f"/api/voyages/{b['id']}/export/readiness", headers=H).json()
    assert not rd["plan"]["tables"]
    # only form options and "attached declaration = 0" flags derived from this (empty) voyage - nothing from other voyages
    assert all(c["kind"] == "option" or (c["kind"] == "derived" and c["value"] == "0") for c in rd["plan"]["cells"])


def test_login_lockout():
    for _ in range(5):
        assert client.post("/api/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"username": "admin", "password": "admin123"}).status_code == 429


def test_scenario4_large_lists_neutral_filenames():
    vid, docs = sample(4)
    assert len(docs) == 5
    assert sorted(d["doc_type"] for d in docs) == sorted(["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "TONNAGE_CERTIFICATE", "CREW_LIST", "CARGO_MANIFEST"])
    fields = client.get(f"/api/voyages/{vid}/fields", headers=H).json()["fields"]
    assert len({f["record_key"] for f in fields if f["section"] == "crew"}) == 35
    assert len({f["record_key"] for f in fields if f["section"] == "cargo"}) == 50
    assert all(f["data_type"] for f in fields)  # data type stored with every value
    assert any(f["data_type"] == "date" for f in fields) and any(f["data_type"] == "identifier" for f in fields)
    res = results(vid)
    assert not [r for r in res if r["blocking"]], [r["message"] for r in res if r["blocking"]]
    assert any(r["status"] == "PASSED" and r["field_key"] == "crew_count" for r in res)
    confirm_all(vid)
    results(vid)
    r = client.post(f"/api/voyages/{vid}/export", json={}, headers=H)
    assert r.status_code == 200, r.text
    rep = r.json()["report"]
    assert not [c for c in rep["checks"] if not c["ok"]], rep["checks"]
    assert rep["rows"]["Crew list"] == 35 and rep["rows"]["Goods Declaration"] == 50
    # exclude a record -> it leaves the declaration and the crew count no longer matches
    crew1 = next(f for f in fields if f["section"] == "crew" and f["record_key"] == "crew:1")
    ex = client.post(f"/api/voyages/{vid}/records/exclude", headers=H, json={"document_id": crew1["document_id"], "section": "crew",
                                                                         "record_key": "crew:1", "exclude": True, "reason": "test"})
    assert ex.status_code == 200
    res = results(vid)
    assert any(r["status"] == "MISMATCH" and r["field_key"] == "crew_count" for r in res)
    rd = client.get(f"/api/voyages/{vid}/export/readiness", headers=H).json()
    assert len(rd["plan"]["tables"]["Crew list"]["rows"]) == 34
    client.post(f"/api/voyages/{vid}/records/exclude", headers=H, json={"document_id": crew1["document_id"], "section": "crew",
                                                                    "record_key": "crew:1", "exclude": False})
    assert len(client.get(f"/api/voyages/{vid}/export/readiness", headers=H).json()["plan"]["tables"]["Crew list"]["rows"]) == 35


def test_scenario2_containers_security_wrong_voyage_actions():
    vid, docs = sample(2)
    types = {d["original_name"]: d["doc_type"] for d in docs}
    assert types["11_doc_scan_0457.pdf"] == "SHIP_SECURITY" and types["10_empty_containers.xlsx"] == "EMPTY_CONTAINER_LIST"
    res = results(vid)
    assert any(r["group_name"].startswith("5") and r["status"] == "MISMATCH" and "RỖNG" in r["message"] for r in res)
    assert any(r["check_key"].startswith("mixed|") for r in res)  # several vessels in one set
    other = next(d for d in docs if "OTHER_VESSEL" in d["original_name"])
    # data of the suspect document is kept out of the declaration
    rd = client.get(f"/api/voyages/{vid}/export/readiness", headers=H).json()
    assert other["original_name"] not in str(rd["plan"]["tables"]["Goods Declaration"]["sources"])
    assert any("nghi thuộc chuyến khác" in w for w in rd["warnings"])
    # move it to the voyage it belongs to
    target = client.post("/api/voyages", json={"vessel_name": "SAMPLE CUU LONG BREEZE", "voyage_no": "118W-TEST"}, headers=H).json()
    mv = client.post(f"/api/documents/{other['id']}/move", json={"voyage_id": target["id"], "reason": "test"}, headers=H)
    assert mv.status_code == 200, mv.text
    res = client.get(f"/api/voyages/{vid}/crosscheck", headers=H).json()["results"]
    assert not any(r["doc1_id"] == other["id"] for r in res)
    assert client.get(f"/api/voyages/{target['id']}/documents", headers=H).json()["documents"][0]["id"] == other["id"]
    # security declaration -> NSW sheet (port calls + ISSC) when exported by supervisor override
    confirm_all(vid)
    results(vid)
    r = client.post(f"/api/voyages/{vid}/export", json={"override_username": "admin", "override_password": "admin123", "override_reason": "test"}, headers=H)
    assert r.status_code == 200, r.text
    import openpyxl, warnings
    p = os.path.join(tempfile.mkdtemp(), "o.xlsx")
    open(p, "wb").write(client.get(f"/api/exports/{r.json()['id']}/download?token={H['Authorization'].split()[1]}").content)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(p)
    sec = wb["Declaration For Ship Security"]
    assert sec["B9"].value == "PANAMA MARITIME AUTHORITY" and sec["B11"].value == "11/03/2029" and sec["B12"].value == "1"
    assert sec["A25"].value == "THBKK" and sec["B29"].value == "SINGAPORE" and sec["A30"].value is None
    ec = wb["Empty Container"]
    assert ec["B8"].value and ec["C8"].value == "Container 20" and ec["D8"].value == "VNCLI"


def test_unknown_document_and_confirm_voyage():
    vid, docs = sample(3)
    unk = next(d for d in docs if d["original_name"] == "05_Document01.pdf")
    assert unk["doc_type"] == "OTHER" and unk["status"] == "EXTRACTED"  # kept, not dropped, not an error
    steps = {s["key"]: s for s in client.get(f"/api/voyages/{vid}", headers=H).json()["progress"]["steps"]}
    assert not steps["classify"]["done"] and "Unknown" in steps["classify"]["why"]
    client.put(f"/api/documents/{unk['id']}/type", json={"doc_type": "OTHER", "reprocess": False}, headers=H)
    steps = {s["key"]: s for s in client.get(f"/api/voyages/{vid}", headers=H).json()["progress"]["steps"]}
    assert steps["classify"]["done"]
    assert client.post(f"/api/documents/{unk['id']}/confirm-voyage", json={"confirmed": True, "reason": ""}, headers=H).status_code == 400
    assert client.post(f"/api/documents/{unk['id']}/confirm-voyage", json={"confirmed": True, "reason": "checked"}, headers=H).status_code == 200


def test_duplicate_voyage_warning():
    body = {"vessel_name": "DUP TEST", "imo": "9395044", "voyage_no": "77A", "port_of_arrival": "VNCLI", "eta": "01/12/2026 08:00"}
    a = client.post("/api/voyages", json=body, headers=H)
    assert a.status_code == 200
    b = client.post("/api/voyages", json=body, headers=H)
    assert b.status_code == 409 and b.json()["detail"]["duplicate_id"] == a.json()["id"]
    c = client.post("/api/voyages", json={**body, "allow_duplicate": True}, headers=H)
    assert c.status_code == 200 and c.json()["voyage_code"] != a.json()["voyage_code"]
    d = client.post("/api/voyages", json={**body, "voyage_no": "78A"}, headers=H)  # another voyage of the same ship
    assert d.status_code == 200


def test_header_labels_not_misread_from_prose():
    """Regression: 'VOYAGE' read as label 'Voy.' + value 'AGE'; prose '...the vessel at the port...' read as vessel name."""
    from app import extract

    def read(text):
        pages = [{"page_no": 1, "method": "docx", "confidence": 1.0, "tables": [], "text": text}]
        return {k: v["value"] for k, v in extract.extract_header(pages, ["vessel_name", "voyage_no"]).items()}
    assert read("The vessel at the port of Ho Chi Minh\nVOYAGE   09/2023") == {"voyage_no": "09/2023"}
    assert read("Name of ship: MV VINH QUANG GOLD\nArrival of the vessel AT THE PORT is expected") == {"vessel_name": "VINH QUANG GOLD"}
    assert read("Vessel: VINH QUANG GOLD   Voy. No: 2311N") == {"vessel_name": "VINH QUANG GOLD", "voyage_no": "2311N"}



def test_vessel_prefix_and_pipe_separated_fields():
    """'MV VINH QUANG GOLD' = 'VINH QUANG GOLD'; 'Tên tàu: X | Số chuyến: Y' read as two fields."""
    from app import extract, normalize as N
    from app.crosscheck import _cmp_vessel
    assert _cmp_vessel("MV VINH QUANG GOLD", "VINH QUANG GOLD") and _cmp_vessel("M/V Vinh Quang Gold", "m.v. VINH QUANG GOLD")
    assert not _cmp_vessel("MV VINH QUANG GOLD", "VINH QUANG STAR")
    pages = [{"page_no": 1, "method": "docx", "confidence": 1.0, "tables": [],
              "text": "Tên tàu: MV VINH QUANG GOLD | Số chuyến: 09/2023 | IMO: 9395044"}]
    got = {k: v["value"] for k, v in extract.extract_header(pages, ["vessel_name", "voyage_no", "imo"]).items()}
    assert got == {"vessel_name": "VINH QUANG GOLD", "voyage_no": "09/2023", "imo": "9395044"}, got
    # wrong-voyage check must accept the 'MV' prefix difference
    v = client.post("/api/voyages", json={"vessel_name": "MV PREFIX TEST", "voyage_no": "11A"}, headers=H).json()
    import io
    from reportlab.pdfgen import canvas
    buf = io.BytesIO(); cv = canvas.Canvas(buf)
    for i, line in enumerate(["GENERAL DECLARATION", "Name of ship: PREFIX TEST", "Voyage number: 11A", "Port of arrival: VNCLI"]):
        cv.drawString(50, 800 - i * 20, line)
    cv.save()
    client.post(f"/api/voyages/{v['id']}/documents", files=[("files", ("gd.pdf", buf.getvalue(), "application/pdf"))], headers=H)
    wait_docs(v["id"])
    res = results(v["id"])
    assert not any(r["status"] == "WRONG_VOYAGE" for r in res), [r["message"] for r in res if r["status"] == "WRONG_VOYAGE"]



def test_scenario5_combined_files_are_split():
    vid, docs = sample(5)
    parents = [d for d in docs if d["status"] == "SPLIT"]
    assert len(parents) == 2
    kids = [d for d in docs if d["parent_id"]]
    types = sorted(d["doc_type"] for d in kids)
    assert types == sorted(["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "TONNAGE_CERTIFICATE", "CARGO_MANIFEST", "BILL_OF_LADING",
                            "BILL_OF_LADING", "BILL_OF_LADING", "DG_MANIFEST", "CREW_LIST", "CREW_EFFECTS", "SHIP_STORES"]), types
    assert all(d["status"] == "EXTRACTED" for d in kids)
    pdf_kids = [d for d in kids if d["page_from"] and d["original_name"].startswith("Tron_bo")]
    assert all(d["page_from"] >= 1 and d["page_to"] >= d["page_from"] for d in pdf_kids)
    fields = client.get(f"/api/voyages/{vid}/fields", headers=H).json()["fields"]
    assert len({f["record_key"] for f in fields if f["section"] == "crew"}) == 22
    # page numbers refer to the combined file
    gd_kid = next(d for d in kids if d["doc_type"] == "GENERAL_DECLARATION")
    assert gd_kid["page_from"] == 1
    res = results(vid)
    assert not [r for r in res if r["blocking"]], [r["message"] for r in res if r["blocking"]]
    assert any(r["status"] == "PASSED" and r["field_key"] == "gross_weight" for r in res)
    assert any(r["status"] == "PASSED" and r["field_key"] == "crew_count" for r in res)  # GD (PDF) vs Crew List (Word)
    prog = client.get(f"/api/voyages/{vid}", headers=H).json()["progress"]
    assert prog["documents"] == len(kids)
    # undo the split of the Word file -> processed as ONE document again
    docx_parent = next(d for d in parents if d["original_name"].endswith(".docx"))
    assert client.post(f"/api/documents/{docx_parent['id']}/split", json={"split": False}, headers=H).status_code == 200
    docs2 = wait_docs(vid)
    assert not [d for d in docs2 if d["parent_id"] == docx_parent["id"]]
    assert next(d for d in docs2 if d["id"] == docx_parent["id"])["status"] == "EXTRACTED"
    # delete the PDF combined file -> its parts and files go too
    pdf_parent = next(d for d in parents if d["original_name"].endswith(".pdf"))
    client.delete(f"/api/documents/{pdf_parent['id']}", headers=H)
    assert not [d for d in client.get(f"/api/voyages/{vid}/documents", headers=H).json()["documents"] if d["parent_id"] == pdf_parent["id"]]


def test_single_documents_are_not_split():
    """Normal multi-page documents (Crew List over 2 pages, one B/L) must never be split."""
    from app import ingest, samples, splitter
    d = tempfile.mkdtemp()
    for f in samples.generate(4, d):
        pages = ingest.read_document(f)
        assert not splitter.is_combined(splitter.split_pages(pages)), f


def test_vessel_name_curly_quote_and_trailing_label():
    from app import extract

    def read(text):
        pages = [{"page_no": 1, "method": "docx", "confidence": 1.0, "tables": [], "text": text}]
        return {k: v["value"] for k, v in extract.extract_header(pages, ["vessel_name", "voyage_no", "imo", "shipper"]).items()}
    assert read("Vessel’s Name (Tên tàu): MV VINH QUANG GOLD") == {"vessel_name": "VINH QUANG GOLD"}
    assert read("Vessel: MV VINH QUANG GOLD Inspection Order No.: CISVN 23.188") == {"vessel_name": "VINH QUANG GOLD"}
    assert read("Ship’s name: M/V VINH QUANG GOLD   IMO No: 9395044") == {"vessel_name": "VINH QUANG GOLD", "imo": "9395044"}
    assert read("Shipper: Mekong Export Co., Ltd") == {"shipper": "Mekong Export Co., Ltd"}



def test_split_docx_crew_list_without_clear_heading():
    """Crew List whose title is inside a table cell, and one with only a plain caption: both must become separate documents."""
    import docx
    from app import ingest, splitter, extract
    for variant in ("title_in_table", "plain_caption"):
        d = docx.Document()
        p = d.add_paragraph()
        p.add_run("GENERAL DECLARATION").bold = True
        for line in ["Name of ship: MV TEST STAR", "Voyage number: 12A", "Number of crew: 3", "Port of arrival: VNCLI"]:
            d.add_paragraph(line)
        p = d.add_paragraph()
        p.add_run("NOTICE OF ARRIVAL").bold = True
        d.add_paragraph("Vessel name: MV TEST STAR")
        d.add_paragraph("ETA: 01/12/2026 08:00")
        if variant == "plain_caption":
            d.add_paragraph("Danh sách thuyền viên / Crew list of the vessel")
        rows = [["No.", "Name", "Rank", "Nationality", "Date of birth", "Passport No."],
                ["1", "NGUYEN VAN A", "MASTER", "VIETNAMESE", "01/01/1980", "C1234567"],
                ["2", "TRAN VAN B", "C/O", "VIETNAMESE", "02/02/1985", "C2345678"],
                ["3", "LE VAN C", "AB", "VIETNAMESE", "03/03/1990", "C3456789"]]
        if variant == "title_in_table":
            rows = [["CREW LIST (IMO FAL Form 5)", "", "", "", "", ""]] + rows
        t = d.add_table(rows=0, cols=6)
        for r in rows:
            cells = t.add_row().cells
            for i, x in enumerate(r):
                cells[i].text = x
        path = os.path.join(tempfile.mkdtemp(), "combined.docx")
        d.save(path)
        segs = splitter.split_pages(ingest.read_document(path))
        types = [s["type"] for s in segs]
        assert types == ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "CREW_LIST"], (variant, types)
        crew = segs[2]["pages"]
        assert extract.classify(crew)[0] == "CREW_LIST", variant
        assert len({f["record_key"] for f in extract.extract_document("CREW_LIST", crew) if f["section"] == "crew"}) == 3



def test_vietnamese_forms_and_bilingual_values():
    """Patterns met in SGCL's real combined file (Vietnamese forms, bilingual labels, merged columns)."""
    from app import extract
    from app.crosscheck import _cmp_port, _cargo_cmp

    def read(text, keys):
        pages = [{"page_no": 1, "method": "docx", "confidence": 1.0, "tables": [], "text": text}]
        return {k: v["value"] for k, v in extract.extract_header(pages, keys).items()}
    noa = ("Hô hiệu / Call sign: 3WHB9   Cảng đến Port of arrival  CẢNG QUỐC TẾ LONG AN   Thời gian đến Time of arrival  08:00 hrs Ngày 18/10/2023 (ETA Pilot Vũng Tàu)\n"
           "Quốc tịch tàu Flag State of ship VIỆT NAM   Cảng rời cuối cùng/cảng đích: Last port of call/port of destination SURABAYA, INDONESIA  /  CẢNG QUỐC TẾ LONG AN\n"
           "Chiều cao tĩnh không Clearance height 28.50 m   Mớn nước thực tế Shown draft F: 6.10 m / A: 6.35 m\n"
           "Số thuyền viên (gồm cả thuyền trưởng): 12 thuyền viên (Việt Nam)   Số hành khách: 00 (Không)")
    got = read(noa, ["call_sign", "eta", "last_port", "flag", "draft_fwd", "draft_aft", "crew_count"])
    assert got["call_sign"] == "3WHB9" and got["last_port"] == "SURABAYA, INDONESIA" and got["crew_count"] == "12"
    assert extract.normalise_field("eta", got["eta"]) == "18/10/2023 08:00" and got["draft_fwd"].startswith("6.10")
    assert read("Hô hiệu / Distinctive letters 3WHB9 (VN-4195-VT)   Cảng đăng ký / Port of registry HAI PHONG, VIET NAM\nTỔNG DUNG TÍCH (GROSS TONNAGE): 4,353",
                ["call_sign", "flag", "gross_tonnage"]) == {"call_sign": "3WHB9", "gross_tonnage": "4,353"}  # port of registry is not the flag
    assert extract.normalise_field("bl_no", "SUB/LA-231008 Ngày: 10/10/2023") == "SUB/LA-231008"
    fields = {"dob": {"value": "14/05/1976 - THAI BINH"}, "passport_no": {"value": "C6829104 (12/08/2029)"}}
    extract._split_combined(fields)
    assert fields["dob"]["value"] == "14/05/1976" and fields["pob"]["value"] == "THAI BINH"
    assert fields["passport_no"]["value"] == "C6829104" and fields["passport_expiry"]["value"] == "12/08/2029"
    assert _cmp_port("Cảng Quốc tế Long An", "LONG AN INTERNATIONAL PORT, VIETNAM")
    assert not _cmp_port("Cảng Quốc tế Long An", "CAT LAI PORT, HO CHI MINH")
    assert isinstance(_cargo_cmp("company", "Theo lệnh Ngân hàng TMCP Ngoại thương Việt Nam", "TO THE ORDER OF JOINT STOCK COMMERCIAL BANK FOR FOREIGN TRADE OF VIETNAM"), tuple)



def test_bilingual_party_and_goods_match():
    from app import normalize as N
    from app.crosscheck import _cargo_cmp
    vi_cons = ("Theo lệnh Ngân hàng TMCP Ngoại thương Việt Nam (Vietcombank) CN Long An. Bên thông báo: Công ty TNHH Thức ăn Chăn nuôi "
               "Đại Phát KCN Thuận Đạo, Bến Lức, Long An MST: 1101849205")
    en_cons = "TO THE ORDER OF JOINT STOCK COMMERCIAL BANK FOR FOREIGN TRADE OF VIETNAM (VIETCOMBANK), LONG AN BRANCH"
    r = _cargo_cmp("company", vi_cons, en_cons)
    assert isinstance(r, tuple), r
    vi_desc = "Ngô hạt vàng rời dùng làm thức ăn chăn nuôi (Yellow Corn in bulk) Trọng lượng: 5,800.00 MT"
    en_desc = "YELLOW CORN IN BULK (Animal Feed Raw Material) PACKING: IN BULK (Stowed in Holds No. 1, 2 & 3) CLEAN SHIPPED ON BOARD"
    assert isinstance(_cargo_cmp("text", vi_desc, en_desc), tuple)
    # different goods / different bank must NOT match
    assert not isinstance(_cargo_cmp("text", "Gạo trắng đóng bao", en_desc), tuple)
    assert _cargo_cmp("company", "Theo lệnh Ngân hàng TMCP Công Thương Việt Nam (Vietinbank)", en_cons) == "language"



def test_same_company_different_address():
    from app.crosscheck import _cargo_cmp
    assert _cargo_cmp("company", "PT. NUSANTARA AGRO GRAINS Jl. Perak Timur No.", "PT. NUSANTARA AGRO GRAINS Jl. Perak Timur No. 112, Surabaya, East Java") == "same"
    assert _cargo_cmp("company", "PT. NUSANTARA AGRO GRAINS Jl. Perak Timur", "PT. SURYA AGRO GRAINS Jl. Perak Timur") != "same"


def test_single_source_status():
    """A value found in ONE document is shown as taken ('SINGLE_SOURCE'), not as 'Not Enough Data', and is exported."""
    v = client.post("/api/voyages", json={"vessel_name": "SINGLE SOURCE TEST", "voyage_no": "5A"}, headers=H).json()
    import io
    from reportlab.pdfgen import canvas
    buf = io.BytesIO(); cv = canvas.Canvas(buf)
    for i, line in enumerate(["NOTICE OF ARRIVAL", "Vessel name: SINGLE SOURCE TEST", "Voyage No: 5A", "ETA: 01/12/2026 08:00",
                              "Last port of call: SINGAPORE (SGSIN)", "Flag: PANAMA"]):
        cv.drawString(50, 800 - i * 20, line)
    cv.save()
    client.post(f"/api/voyages/{v['id']}/documents", files=[("files", ("noa.pdf", buf.getvalue(), "application/pdf"))], headers=H)
    wait_docs(v["id"])
    res = {r["field_key"]: r["status"] for r in results(v["id"]) if r["group_name"].startswith("1")}
    assert "eta" not in res and "flag" not in res and res["next_port"] == "NOT_AVAILABLE"  # vessel info from one document: not listed
    cells = {(c["sheet"], c["cell"]): c["value"] for c in client.get(f"/api/voyages/{v['id']}/export/readiness", headers=H).json()["plan"]["cells"]}
    assert cells[("Notice ship to port", "B24")] == "01/12/2026 08:00" and cells[("Notice ship to port", "B6")] == "SGSIN"



def test_vessel_summary_uses_crosscheck_comparison():
    """'4,353 GT' (NOA) and '4,353' (tonnage certificate) are the same gross tonnage in the consolidated vessel information."""
    from app import extract
    pages = [{"page_no": 1, "method": "docx", "confidence": 1.0, "tables": [],
              "text": "TỔNG DUNG TÍCH (GROSS TONNAGE): 4,353\nDUNG TÍCH THỰC DỤNG (NET TONNAGE): 2,485"}]
    assert {k: v["value"] for k, v in extract.extract_header(pages, ["gross_tonnage", "net_tonnage"]).items()} == {"gross_tonnage": "4,353", "net_tonnage": "2,485"}
    v = client.post("/api/voyages", json={"vessel_name": "GT TEST", "voyage_no": "1B"}, headers=H).json()
    import io
    from reportlab.pdfgen import canvas

    def pdf(lines):
        buf = io.BytesIO(); cv = canvas.Canvas(buf)
        for i, line in enumerate(lines):
            cv.drawString(50, 800 - i * 20, line)
        cv.save()
        return buf.getvalue()
    client.post(f"/api/voyages/{v['id']}/documents", headers=H, files=[
        ("files", ("noa.pdf", pdf(["NOTICE OF ARRIVAL", "Vessel name: MV GT TEST", "Gross tonnage: 4,353 GT"]), "application/pdf")),
        ("files", ("itc.pdf", pdf(["INTERNATIONAL TONNAGE CERTIFICATE (1969)", "Name of ship: GT TEST", "Gross tonnage: 4,353"]), "application/pdf"))])
    wait_docs(v["id"])
    rows = {r["key"]: r for r in client.get(f"/api/voyages/{v['id']}/profile-suggestions", headers=H).json()}
    assert not rows["gross_tonnage"]["conflict"] and rows["gross_tonnage"]["value"].startswith("4,353")
    assert not rows["vessel_name"]["conflict"]  # 'MV GT TEST' = 'GT TEST'


def test_scanned_bl_and_crew_lines():
    """Scanned forms: B/L number printed apart from its label, label row above value row, crew rows without a readable header."""
    from app import extract
    bl = [{"page_no": 1, "method": "ocr", "confidence": 0.9, "tables": [], "words": {}, "text": "\n".join([
        'CODE NAME : "CONGENBILL" EDITION 1994   B/L No.',
        "é   Shipper   BILL OF LADING   SP/PTK/LA-230901",
        "Consignee", "TO THE ORDER OF SOME BANK",
        "Vessel   Port of loading", "MV HTP OCEAN V16/2023   PONTIANAK,   INDONESIA",
        "Port of discharge", "LONG AN PORT,   VIETNAM",
        "Shippcrs description of goods   Gross weight", "PALM KERNEL EXPELLERS   SAID TO WEIGHT:   2200 MT"])}]
    rec = {f["field_key"]: f["value"] for f in extract.extract_document("BILL_OF_LADING", bl)}
    assert rec["bl_no"] == "SP/PTK/LA-230901" and rec["pol"] == "PONTIANAK, INDONESIA" and rec["pod"] == "LONG AN PORT, VIETNAM"
    assert rec["gross_weight"].startswith("2200") and rec["description"] == "PALM KERNEL EXPELLERS" and "shipper" not in rec
    assert rec["vessel_name"] == "HTP OCEAN"
    crew = [{"page_no": 1, "method": "ocr", "confidence": 0.8, "tables": [], "words": {}, "text": "\n".join([
        "DANH SACH THUYEN VIEN", "CREW LIST",
        "n1   NGUYEN VAN DIEP   VIETNAM   02/02/1972   C5773739   |09/08/2028",
        "l9.   VU VAN CHIEN | ABE   VIETNAM | 09/06/1966 | NAMDINH   |C6199518   {11/10/2028",
        "pan   VAN DUC TUYEN   COOK | VỊET NAM | 1984-10-02 | NGHEAN |   C0I2I147 | 2025-03-04"])}]
    rows = [{k: v["value"] for k, v in r["fields"].items()} for r in extract.extract_ocr_crew_rows(crew[0])]
    assert [r["full_name"] for r in rows] == ["NGUYEN VAN DIEP", "VU VAN CHIEN", "VAN DUC TUYEN"]
    assert rows[1]["rank"] == "ABE" and rows[1]["pob"] == "NAMDINH" and rows[2]["passport_no"] == "C0121147" and rows[2]["rank"] == "COOK"


def test_box_number_is_not_voyage_no():
    """FAL forms number their boxes: 'Voyage No.   2. Port of arrival' - '2.' is not the voyage number."""
    from app import extract
    pg = lambda t: [{"page_no": 1, "method": "text", "confidence": 1, "tables": [], "text": t}]
    assert "voyage_no" not in extract.extract_header(pg("Voyage No.   2. Port of arrival: LONG AN"), ["voyage_no"])
    assert extract.extract_header(pg("Voyage No.: 14/2023"), ["voyage_no"])["voyage_no"]["value"] == "14/2023"
    assert extract.extract_header(pg("Voyage No: 5"), ["voyage_no"])["voyage_no"]["value"] == "5"


def test_ocr_rank_normalised_and_row_number_dropped():
    from app import extract
    p = {"page_no": 1, "method": "ocr", "confidence": 0.8, "tables": [], "words": {}, "text":
         "II VAN DUC TUYEN   CO   VIETNAM | 1984-10-02 | NGHE AN | C0121147 | 2025-03-04"}
    r = {k: v["value"] for k, v in extract.extract_ocr_crew_rows(p)[0]["fields"].items()}
    assert r["full_name"] == "VAN DUC TUYEN" and r["rank"] == "C/O" and r["passport_no"] == "C0121147"


def test_bilingual_same_party_keeps_bl_wording():
    """VI manifest consignee vs EN B/L consignee: staff confirm same party -> Excel uses the B/L wording, VI kept in history."""
    from app import db
    v = client.post("/api/voyages", json={"vessel_name": "BILINGUAL TEST", "voyage_no": "7"}, headers=H).json()
    vi = "Theo lệnh Vietcombank CN Nghệ An. Bên thông báo: Công ty CP Đầu tư XNK Phương Trang"
    en = "TO THE ORDER OF JOINT STOCK COMMERCIAL BANK FOR FOREIGN TRADE OF VIETNAM, NGHE AN BRANCH"
    with db.tx() as c:
        ids = {}
        for t in ("CARGO_MANIFEST", "BILL_OF_LADING"):
            ids[t] = c.execute("INSERT INTO documents(voyage_id,original_name,stored_name,ext,size,sha256,status,uploaded_by,uploaded_at,doc_type) "
                               "VALUES(?,?,?,?,?,?,'EXTRACTED','t',?,?)", (v["id"], t + ".pdf", t, ".pdf", 1, t + str(v["id"]), db.now(), t)).lastrowid
        for t, rk, val in (("CARGO_MANIFEST", "mf:1", vi), ("BILL_OF_LADING", "bl:1", en)):
            for k, x in (("bl_no", "SP/PTK/LA-230901"), ("consignee", val)):
                c.execute("INSERT INTO extracted_fields(voyage_id,document_id,section,record_key,record_index,field_key,field_label,original_value,value,"
                          "page_no,confidence,method,status,updated_at) VALUES(?,?,'cargo',?,1,?,?,?,?,1,0.9,'text','EXTRACTED',?)",
                          (v["id"], ids[t], rk, k, k, x, x, db.now()))
    res = client.post(f"/api/voyages/{v['id']}/crosscheck", headers=H).json()["results"]
    r = next(x for x in res if (x.get("check_key") or "").startswith("lang|"))
    assert r["status"] == "NEEDS_REVIEW" and not r["blocking"]
    assert client.post(f"/api/crosscheck/{r['id']}/resolve", json={"action": "same_party"}, headers=H).status_code == 200
    fs = client.get(f"/api/voyages/{v['id']}/fields", headers=H).json()["fields"]
    mf = next(f for f in fs if f["field_key"] == "consignee" and f["document_id"] == ids["CARGO_MANIFEST"])
    assert mf["value"] == en and mf["original_value"] == vi
    res = results(v["id"])
    assert any(x["status"] == "PASSED" and x["field_key"] == "consignee" and "tiếng Việt gốc" in x["message"] for x in res)
    log = client.get(f"/api/voyages/{v['id']}/log", headers=H).json()
    assert any(e["action"] == "SAME_PARTY_BILINGUAL" and vi in (e.get("reason") or "") for e in log)


def test_passport_letter_completed_from_other_document():
    from app import db
    from app.main import _complete_passport_letters
    v = client.post("/api/voyages", json={"vessel_name": "PASSPORT TEST", "voyage_no": "8"}, headers=H).json()
    with db.tx() as c:
        docs = [c.execute("INSERT INTO documents(voyage_id,original_name,stored_name,ext,size,sha256,status,uploaded_by,uploaded_at,doc_type) "
                          "VALUES(?,?,?,?,?,?,'EXTRACTED','t',?,'CREW_LIST')", (v["id"], f"crew{i}.pdf", f"c{i}", ".pdf", 1, f"pp{i}{v['id']}", db.now())).lastrowid
                for i in (1, 2)]
        for d, val in ((docs[0], "1328382"), (docs[1], "C1328382")):
            c.execute("INSERT INTO extracted_fields(voyage_id,document_id,section,record_key,record_index,field_key,field_label,original_value,value,"
                      "page_no,confidence,method,status,updated_at) VALUES(?,?,'crew','crew:1',1,'passport_no','p',?,?,1,0.7,'ocr-line','EXTRACTED',?)",
                      (v["id"], d, val, val, db.now()))
        _complete_passport_letters(c, v["id"], "t")
        f = db.row(c, "SELECT value, original_value FROM extracted_fields WHERE document_id=?", (docs[0],))
    assert f["value"] == "C1328382" and f["original_value"] == "1328382"
