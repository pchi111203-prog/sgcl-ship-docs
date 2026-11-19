"""End-to-end tests of the 3 required scenarios + voyage isolation, through the REST API.

Run:  cd backend && SGCL_DATA_DIR=$(mktemp -d) python -m pytest -q tests
"""
import json
import os
import tempfile
import time

os.environ.setdefault("SGCL_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SGCL_SKIP_LIBREOFFICE", "0")

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
        if docs and all(d["status"] in ("EXTRACTED", "ERROR") for d in docs):
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
    assert wb["Goods Declaration"]["P10"].value == "VNCLI" and wb["Goods Declaration"]["R10"].value == "SGSIN"
    assert wb["Passenger list"]["A11"].value is None  # sample row cleared, no passengers
    eff = wb["Crew's Effects Declaration"]
    assert eff["A11"].value and eff["B11"].value and eff["C11"].value == "CAP"
    assert eff["C45"].value == "NameOfShip"  # template content below the list kept
    assert wb["General Declaration"]["B33"].value.startswith("=IF(")  # formula kept
    assert wb["Cargo manifest"].sheet_state == "hidden"
    assert wb.sheetnames[0] == "Declaration list" and len(wb.sheetnames) == 21
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
    r = client.post(f"/api/voyages/{vid}/export", json={"override_username": "admin", "override_password": "Sunny12", "override_reason": "Test ngoại lệ"}, headers=H)
    assert r.status_code == 200, r.text


def test_scenario3_scanned_missing():
    vid, docs = sample(3)
    assert all("ocr" in (d["extraction_method"] or "") for d in docs if d["status"] == "EXTRACTED")
    res = results(vid)
    fields = client.get(f"/api/voyages/{vid}/fields", headers=H).json()["fields"]
    gd = [f for f in fields if f["doc_type"] == "GENERAL_DECLARATION"]
    assert not any(f["field_key"] == "eta" for f in gd)          # not invented
    assert not any(f["field_key"] == "crew_count" for f in gd)   # not invented
    assert any(r["status"] == "NOT_AVAILABLE" and r["field_key"] == "eta" for r in res)
    assert any(r["group_name"].startswith("3") and r["status"] == "MISSING_INFO" for r in res)
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
    assert not rd["plan"]["tables"] and all(c["kind"] == "option" for c in rd["plan"]["cells"])
