"""SGCL - Ship Documentation Automation System: REST API (FastAPI)."""
import hashlib
import os
import secrets
import shutil
import tempfile
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import crosscheck, db, extract, ingest, nsw_export, samples
from . import normalize as N

app = FastAPI(title="SGCL Ship Documentation Automation System")
SESSION_HOURS = int(os.environ.get("SGCL_SESSION_HOURS", "12"))
LOGIN_FAILS = {}  # (username, ip) -> [timestamps] ; 5 failures / 15 minutes -> locked
# Frontend hosted elsewhere (e.g. Vercel): allow its origin(s), comma separated
if os.environ.get("SGCL_CORS_ORIGINS"):
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip().rstrip("/") for o in os.environ["SGCL_CORS_ORIGINS"].split(",") if o.strip()],
                       allow_methods=["*"], allow_headers=["*"])
POOL = ThreadPoolExecutor(max_workers=2)
LOCK = threading.Lock()
MAX_UPLOAD = 50 * 1024 * 1024


@app.on_event("startup")
def startup():
    db.init_db()
    N.load_codes_from_template(db.TEMPLATE_PATH)
    with db.tx() as c:  # documents interrupted by a restart
        c.execute("UPDATE documents SET status='ERROR', error='Bị gián đoạn khi đang xử lý - hãy xử lý lại' WHERE status='PROCESSING'")


# ------------------------------------------------------------------ auth
def current_user(authorization: str = Header(default="")):
    token = authorization.replace("Bearer ", "").strip()
    with db.tx() as c:
        limit = (db.local_now() - timedelta(hours=SESSION_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
        c.execute("DELETE FROM sessions WHERE created_at < ?", (limit,))
        u = db.row(c, "SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,))
    if not u:
        raise HTTPException(401, "Phiên đăng nhập không hợp lệ")
    u.pop("password_hash", None)
    return u


def supervisor(u=Depends(current_user)):
    if u["role"] != "supervisor":
        raise HTTPException(403, "Chỉ tài khoản Supervisor được thực hiện")
    return u


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: LoginIn, request: Request):
    key = (body.username.strip().lower(), request.client.host if request.client else "")
    t = datetime.now().timestamp()
    fails = [x for x in LOGIN_FAILS.get(key, []) if t - x < 900]
    if len(fails) >= 5:
        raise HTTPException(429, "Đăng nhập sai quá 5 lần - vui lòng thử lại sau 15 phút")
    with db.tx() as c:
        u = db.row(c, "SELECT * FROM users WHERE username=?", (body.username.strip(),))
        if not u or not db.verify_password(body.password, u["password_hash"]):
            LOGIN_FAILS[key] = fails + [t]
            raise HTTPException(401, "Sai tên đăng nhập hoặc mật khẩu")
    LOGIN_FAILS.pop(key, None)
    with db.tx() as c:
        token = secrets.token_hex(24)
        c.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)", (token, u["id"], db.now()))
    return {"token": token, "user": {"id": u["id"], "username": u["username"], "full_name": u["full_name"], "role": u["role"]}}


@app.post("/api/logout")
def logout(authorization: str = Header(default="")):
    with db.tx() as c:
        c.execute("DELETE FROM sessions WHERE token=?", (authorization.replace("Bearer ", ""),))
    return {"ok": True}


@app.get("/api/me")
def me(u=Depends(current_user)):
    return u


# ------------------------------------------------------------------ helpers
def _voyage_or_404(c, vid):
    v = db.row(c, "SELECT * FROM voyages WHERE id=?", (vid,))
    if not v:
        raise HTTPException(404, "Không tìm thấy chuyến tàu")
    return v


def voyage_progress(c, v):
    vid = v["id"]
    docs = db.rows(c, "SELECT status FROM documents WHERE voyage_id=?", (vid,))
    n_docs = len(docs)
    n_ext = sum(1 for d in docs if d["status"] == "EXTRACTED")
    n_err = sum(1 for d in docs if d["status"] == "ERROR")
    n_proc = sum(1 for d in docs if d["status"] in ("PROCESSING", "UPLOADED"))
    run = db.row(c, "SELECT * FROM crosscheck_runs WHERE voyage_id=? ORDER BY id DESC LIMIT 1", (vid,))
    fstat = db.row(c, "SELECT COUNT(*) n, SUM(status='CONFIRMED') conf, MAX(updated_at) m FROM extracted_fields WHERE voyage_id=?", (vid,))
    blocking = db.row(c, "SELECT COUNT(*) n FROM crosscheck_results WHERE voyage_id=? AND blocking=1", (vid,))["n"]
    issues = db.row(c, "SELECT COUNT(*) n FROM crosscheck_results WHERE voyage_id=? AND status NOT IN ('PASSED','NOT_AVAILABLE','NOT_ENOUGH_DATA') AND acknowledged=0", (vid,))["n"]
    exports = db.row(c, "SELECT COUNT(*) n, MAX(created_at) last FROM exports WHERE voyage_id=?", (vid,))
    check_fresh = bool(run) and not (fstat["m"] and fstat["m"] > run["run_at"])
    unconfirmed_used = 0
    if fstat["n"]:
        plan, _ = nsw_export.build_plan(c, vid)
        if plan.used_fields:
            ids = list(plan.used_fields)
            unconfirmed_used = db.row(c, f"SELECT COUNT(*) n FROM extracted_fields WHERE status!='CONFIRMED' AND id IN ({','.join('?' * len(ids))})", ids)["n"]
    steps = [
        {"key": "create", "label": "Tạo chuyến tàu", "done": True, "why": ""},
        {"key": "upload", "label": "Tải chứng từ", "done": n_docs > 0, "why": "Chưa tải chứng từ nào."},
        {"key": "extract", "label": "Trích xuất", "done": n_docs > 0 and n_ext == n_docs,
         "why": f"{n_ext}/{n_docs} chứng từ đã trích xuất" + (f", {n_err} chứng từ lỗi xử lý" if n_err else "") + (f", {n_proc} đang xử lý" if n_proc else "") + "."},
        {"key": "check", "label": "Đối chiếu", "done": check_fresh and n_docs > 0,
         "why": "Chưa chạy đối chiếu." if not run else "Dữ liệu đã được sửa sau lần đối chiếu gần nhất - cần chạy lại đối chiếu."},
        # same rule as the export gate: no blocking issue + every field that goes into the NSW file confirmed
        {"key": "review", "label": "Xác nhận", "done": bool(fstat["n"]) and blocking == 0 and unconfirmed_used == 0,
         "why": "; ".join(x for x in [f"còn {blocking} lỗi chặn (Mismatch/Duplicate/Wrong Voyage) chưa xử lý" if blocking else "",
                                     f"còn {unconfirmed_used} trường sẽ ghi vào Excel chưa xác nhận" if unconfirmed_used else "",
                                     "chưa có dữ liệu trích xuất" if not fstat["n"] else ""] if x) + "."},
        {"key": "export", "label": "Xuất Excel", "done": exports["n"] > 0, "why": "Chưa xuất file Excel."},
    ]
    done = sum(s["done"] for s in steps)
    if exports["n"]:
        status = "EXPORTED"
    elif n_docs == 0:
        status = "NEW"
    elif n_proc:
        status = "PROCESSING"
    elif blocking or n_err or unconfirmed_used or not check_fresh:
        status = "IN_REVIEW"
    else:
        status = "READY"
    return {"steps": steps, "progress": round(done / len(steps) * 100), "status": status, "documents": n_docs, "extracted": n_ext,
            "errors": n_err, "fields": fstat["n"], "confirmed": fstat["conf"] or 0, "unconfirmed_export": unconfirmed_used, "blocking": blocking, "issues": issues,
            "exports": exports["n"], "last_export": exports["last"], "last_check": run["run_at"] if run else None, "check_fresh": check_fresh}


def _touch(c, vid):
    c.execute("UPDATE voyages SET updated_at=? WHERE id=?", (db.now(), vid))


# ------------------------------------------------------------------ dashboard
@app.get("/api/dashboard")
def dashboard(u=Depends(current_user)):
    with db.tx() as c:
        voyages = db.rows(c, "SELECT * FROM voyages ORDER BY id DESC")
        for v in voyages:
            v["progress"] = voyage_progress(c, v)
        stats = {
            "voyages": len(voyages),
            "in_progress": sum(1 for v in voyages if v["progress"]["status"] in ("PROCESSING", "IN_REVIEW", "NEW", "READY")),
            "documents": db.row(c, "SELECT COUNT(*) n FROM documents")["n"],
            "extracted": db.row(c, "SELECT COUNT(*) n FROM documents WHERE status='EXTRACTED'")["n"],
            "doc_errors": db.row(c, "SELECT COUNT(*) n FROM documents WHERE status='ERROR'")["n"],
            "issues": sum(v["progress"]["blocking"] for v in voyages),
            "exports": db.row(c, "SELECT COUNT(*) n FROM exports")["n"],
        }
    return {"stats": stats, "recent": voyages[:10]}


# ------------------------------------------------------------------ vessel profiles
class VesselIn(BaseModel):
    vessel_name: str
    imo: str | None = None
    call_sign: str | None = None
    flag: str | None = None
    gross_tonnage: str | None = None
    net_tonnage: str | None = None
    notes: str | None = None


@app.get("/api/vessels")
def vessels(u=Depends(current_user)):
    with db.tx() as c:
        return db.rows(c, "SELECT p.*, (SELECT COUNT(*) FROM voyages v WHERE v.vessel_profile_id=p.id) voyages FROM vessel_profiles p ORDER BY vessel_name")


@app.post("/api/vessels")
def create_vessel(body: VesselIn, u=Depends(current_user)):
    if body.imo and not N.imo_valid(body.imo):
        raise HTTPException(400, f"IMO {body.imo} không hợp lệ (sai số kiểm tra)")
    with db.tx() as c:
        cur = c.execute("INSERT INTO vessel_profiles(vessel_name,imo,call_sign,flag,gross_tonnage,net_tonnage,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (body.vessel_name.strip().upper(), body.imo, body.call_sign, body.flag, body.gross_tonnage, body.net_tonnage, body.notes, db.now(), db.now()))
        return db.row(c, "SELECT * FROM vessel_profiles WHERE id=?", (cur.lastrowid,))


@app.put("/api/vessels/{pid}")
def update_vessel(pid: int, body: VesselIn, u=Depends(current_user)):
    with db.tx() as c:
        c.execute("UPDATE vessel_profiles SET vessel_name=?,imo=?,call_sign=?,flag=?,gross_tonnage=?,net_tonnage=?,notes=?,updated_at=? WHERE id=?",
                  (body.vessel_name.strip().upper(), body.imo, body.call_sign, body.flag, body.gross_tonnage, body.net_tonnage, body.notes, db.now(), pid))
        return db.row(c, "SELECT * FROM vessel_profiles WHERE id=?", (pid,))


# ------------------------------------------------------------------ voyages
class VoyageIn(BaseModel):
    vessel_profile_id: int | None = None
    vessel_name: str | None = None
    imo: str | None = None
    call_sign: str | None = None
    flag: str | None = None
    voyage_no: str | None = None
    port_of_arrival: str | None = None
    last_port: str | None = None
    next_port: str | None = None
    eta: str | None = None
    etd: str | None = None
    cargo_type: str | None = None
    notes: str | None = None
    save_profile: bool = False


VOYAGE_COLS = ["vessel_profile_id", "vessel_name", "imo", "call_sign", "flag", "voyage_no", "port_of_arrival", "last_port", "next_port",
               "eta", "etd", "cargo_type", "notes"]


def _create_voyage(c, data: dict, user, is_sample=False):
    if data.get("imo") and not N.imo_valid(data["imo"]):
        raise HTTPException(400, f"IMO {data['imo']} không hợp lệ (sai số kiểm tra)")
    if data.get("vessel_name"):
        data["vessel_name"] = data["vessel_name"].strip().upper()
    cur = c.execute(f"INSERT INTO voyages(voyage_code,{','.join(VOYAGE_COLS)},status,is_sample,created_by,created_at,updated_at) "
                    f"VALUES(?,{','.join('?' * len(VOYAGE_COLS))},'NEW',?,?,?,?)",
                    ("TMP-" + secrets.token_hex(6), *[data.get(k) for k in VOYAGE_COLS], 1 if is_sample else 0, user, db.now(), db.now()))
    vid = cur.lastrowid
    code = f"{'SAMPLE' if is_sample else 'SGCL'}-{db.local_now():%y%m}-{vid:04d}"
    c.execute("UPDATE voyages SET voyage_code=? WHERE id=?", (code, vid))
    db.log(c, vid, "CREATE_VOYAGE", user, reason=code)
    return vid


@app.get("/api/voyages")
def list_voyages(u=Depends(current_user)):
    with db.tx() as c:
        vs = db.rows(c, "SELECT * FROM voyages ORDER BY id DESC")
        for v in vs:
            v["progress"] = voyage_progress(c, v)
        return vs


@app.post("/api/voyages")
def create_voyage(body: VoyageIn, u=Depends(current_user)):
    data = body.model_dump()
    with db.tx() as c:
        if body.save_profile and body.vessel_name and not body.vessel_profile_id:
            cur = c.execute("INSERT INTO vessel_profiles(vessel_name,imo,call_sign,flag,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                            (body.vessel_name.strip().upper(), body.imo, body.call_sign, body.flag, db.now(), db.now()))
            data["vessel_profile_id"] = cur.lastrowid
        vid = _create_voyage(c, data, u["username"])
        v = db.row(c, "SELECT * FROM voyages WHERE id=?", (vid,))
        v["progress"] = voyage_progress(c, v)
        return v


@app.get("/api/voyages/{vid}")
def get_voyage(vid: int, u=Depends(current_user)):
    with db.tx() as c:
        v = _voyage_or_404(c, vid)
        v["progress"] = voyage_progress(c, v)
        return v


@app.put("/api/voyages/{vid}")
def update_voyage(vid: int, body: VoyageIn, u=Depends(current_user)):
    data = body.model_dump()
    with db.tx() as c:
        old = _voyage_or_404(c, vid)
        if data.get("imo") and not N.imo_valid(data["imo"]):
            raise HTTPException(400, f"IMO {data['imo']} không hợp lệ (sai số kiểm tra)")
        for k in VOYAGE_COLS:
            if (old.get(k) or "") != (data.get(k) or ""):
                db.log(c, vid, "EDIT_VOYAGE", u["username"], field_key=k, old=old.get(k), new=data.get(k))
        c.execute(f"UPDATE voyages SET {','.join(k + '=?' for k in VOYAGE_COLS)},updated_at=? WHERE id=?",
                  (*[data.get(k) for k in VOYAGE_COLS], db.now(), vid))
        return get_voyage(vid, u)


@app.get("/api/voyages/{vid}/profile-suggestions")
def profile_suggestions(vid: int, u=Depends(current_user)):
    """Values for the voyage record proposed from GD / NOA / Tonnage (only when sources agree).
    Nothing is written until staff press 'Áp dụng'."""
    keys = {"vessel_name": ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "TONNAGE_CERTIFICATE"], "imo": None, "call_sign": None, "flag": None,
            "voyage_no": ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL"], "port_of_arrival": ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL"],
            "last_port": ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL"], "next_port": ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL"],
            "eta": ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL"], "etd": ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL"]}
    out = []
    with db.tx() as c:
        v = _voyage_or_404(c, vid)
        for k, types in keys.items():
            types = types or ["GENERAL_DECLARATION", "NOTICE_OF_ARRIVAL", "TONNAGE_CERTIFICATE"]
            fs = db.rows(c, f"SELECT f.value, d.original_name, f.page_no FROM extracted_fields f JOIN documents d ON d.id=f.document_id "
                            f"WHERE f.voyage_id=? AND f.section='vessel' AND f.record_key='header' AND f.field_key=? AND d.doc_type IN ({','.join('?' * len(types))})",
                         (vid, k, *types))
            vals = {N.norm_text(f["value"]): f["value"] for f in fs if f["value"]}
            out.append({"key": k, "label": extract.FIELD_LABELS.get(k, k), "current": v.get(k), "sources": fs,
                        "value": next(iter(vals.values())) if len(vals) == 1 else None, "conflict": len(vals) > 1})
    return out


@app.delete("/api/voyages/{vid}")
def delete_voyage(vid: int, u=Depends(supervisor)):
    with db.tx() as c:
        _voyage_or_404(c, vid)
        for d in db.rows(c, "SELECT stored_name FROM documents WHERE voyage_id=?", (vid,)):
            _rm(os.path.join(db.UPLOAD_DIR, d["stored_name"]))
        for e in db.rows(c, "SELECT stored_name FROM exports WHERE voyage_id=?", (vid,)):
            _rm(os.path.join(db.EXPORT_DIR, e["stored_name"]))
        c.execute("DELETE FROM voyages WHERE id=?", (vid,))
    return {"ok": True}


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


# ------------------------------------------------------------------ documents
@app.get("/api/voyages/{vid}/documents")
def list_documents(vid: int, u=Depends(current_user)):
    with db.tx() as c:
        docs = db.rows(c, "SELECT d.*, (SELECT COUNT(*) FROM extracted_fields f WHERE f.document_id=d.id) n_fields, "
                          "(SELECT COUNT(DISTINCT record_key) FROM extracted_fields f WHERE f.document_id=d.id AND record_key!='header') n_records "
                          "FROM documents d WHERE voyage_id=? ORDER BY id", (vid,))
    return {"documents": docs, "types": extract.DOC_TYPES}


def _save_upload(vid, f: UploadFile, user, c):
    ext = os.path.splitext(f.filename or "")[1].lower()
    if ext not in ingest.SUPPORTED:
        raise HTTPException(400, f"'{f.filename}': định dạng {ext or '(không rõ)'} chưa được hỗ trợ")
    data = f.file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(400, f"'{f.filename}' vượt quá 50MB")
    if not data:
        raise HTTPException(400, f"'{f.filename}' rỗng")
    stored = f"v{vid}_{secrets.token_hex(8)}{ext}"
    with open(os.path.join(db.UPLOAD_DIR, stored), "wb") as out:
        out.write(data)
    sha = hashlib.sha256(data).hexdigest()
    dup = db.row(c, "SELECT original_name FROM documents WHERE voyage_id=? AND sha256=?", (vid, sha))
    cur = c.execute("INSERT INTO documents(voyage_id,original_name,stored_name,ext,size,sha256,status,uploaded_by,uploaded_at) VALUES(?,?,?,?,?,?,'UPLOADED',?,?)",
                    (vid, f.filename, stored, ext, len(data), sha, user, db.now()))
    db.log(c, vid, "UPLOAD", user, reason=f.filename)
    return cur.lastrowid, dup


@app.post("/api/voyages/{vid}/documents")
def upload_documents(vid: int, files: list[UploadFile] = File(...), u=Depends(current_user)):
    results, ids = [], []
    with db.tx() as c:
        _voyage_or_404(c, vid)
    for f in files:
        try:
            with db.tx() as c:
                did, dup = _save_upload(vid, f, u["username"], c)
            ids.append(did)
            results.append({"file": f.filename, "ok": True, "id": did,
                            "warning": f"Trùng nội dung với '{dup['original_name']}' đã tải trước đó" if dup else None})
        except HTTPException as e:
            results.append({"file": f.filename, "ok": False, "error": e.detail})
    for did in ids:
        _queue(did, u["username"])
    return {"results": results}


@app.post("/api/documents/{did}/replace")
def replace_document(did: int, file: UploadFile = File(...), u=Depends(current_user)):
    with db.tx() as c:
        d = db.row(c, "SELECT * FROM documents WHERE id=?", (did,))
        if not d:
            raise HTTPException(404)
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ingest.SUPPORTED:
            raise HTTPException(400, f"Định dạng {ext} chưa được hỗ trợ")
        data = file.file.read()
        stored = f"v{d['voyage_id']}_{secrets.token_hex(8)}{ext}"
        with open(os.path.join(db.UPLOAD_DIR, stored), "wb") as out:
            out.write(data)
        _rm(os.path.join(db.UPLOAD_DIR, d["stored_name"]))
        c.execute("DELETE FROM extracted_fields WHERE document_id=?", (did,))
        c.execute("DELETE FROM document_pages WHERE document_id=?", (did,))
        c.execute("UPDATE documents SET original_name=?,stored_name=?,ext=?,size=?,sha256=?,status='UPLOADED',error=NULL,doc_type=NULL,"
                  "doc_type_confirmed=0,uploaded_at=? WHERE id=?",
                  (file.filename, stored, ext, len(data), hashlib.sha256(data).hexdigest(), db.now(), did))
        db.log(c, d["voyage_id"], "REPLACE_DOCUMENT", u["username"], old=d["original_name"], new=file.filename)
    _queue(did, u["username"])
    return {"ok": True}


@app.delete("/api/documents/{did}")
def delete_document(did: int, u=Depends(current_user)):
    with db.tx() as c:
        d = db.row(c, "SELECT * FROM documents WHERE id=?", (did,))
        if not d:
            raise HTTPException(404)
        c.execute("DELETE FROM documents WHERE id=?", (did,))
        _rm(os.path.join(db.UPLOAD_DIR, d["stored_name"]))
        db.log(c, d["voyage_id"], "DELETE_DOCUMENT", u["username"], old=d["original_name"])
        _touch(c, d["voyage_id"])
    return {"ok": True}


class TypeIn(BaseModel):
    doc_type: str
    reprocess: bool = True


@app.put("/api/documents/{did}/type")
def set_doc_type(did: int, body: TypeIn, u=Depends(current_user)):
    if body.doc_type not in extract.DOC_TYPES:
        raise HTTPException(400, "Loại chứng từ không hợp lệ")
    with db.tx() as c:
        d = db.row(c, "SELECT * FROM documents WHERE id=?", (did,))
        if not d:
            raise HTTPException(404)
        c.execute("UPDATE documents SET doc_type=?, doc_type_confirmed=1 WHERE id=?", (body.doc_type, did))
        db.log(c, d["voyage_id"], "SET_DOC_TYPE", u["username"], old=d["doc_type"], new=body.doc_type, reason=d["original_name"])
    if body.reprocess and d["doc_type"] != body.doc_type:
        _queue(did, u["username"])
    return {"ok": True}


@app.post("/api/documents/{did}/process")
def reprocess(did: int, u=Depends(current_user)):
    _queue(did, u["username"])
    return {"ok": True}


@app.get("/api/documents/{did}/file")
def doc_file(did: int, token: str = ""):
    current_user("Bearer " + token)
    with db.tx() as c:
        d = db.row(c, "SELECT * FROM documents WHERE id=?", (did,))
    if not d:
        raise HTTPException(404)
    return FileResponse(os.path.join(db.UPLOAD_DIR, d["stored_name"]), filename=d["original_name"],
                        content_disposition_type="inline")


@app.get("/api/documents/{did}/pages")
def doc_pages(did: int, u=Depends(current_user)):
    with db.tx() as c:
        return db.rows(c, "SELECT page_no,method,confidence,text FROM document_pages WHERE document_id=? ORDER BY page_no", (did,))


def _queue(did, user):
    with db.tx() as c:
        c.execute("UPDATE documents SET status='PROCESSING', error=NULL WHERE id=?", (did,))
    POOL.submit(process_document, did, user)


def process_document(did, user):
    """Read -> classify -> extract -> store. Runs in a worker thread."""
    try:
        with db.tx() as c:
            d = db.row(c, "SELECT * FROM documents WHERE id=?", (did,))
        if not d:
            return
        pages = ingest.read_document(os.path.join(db.UPLOAD_DIR, d["stored_name"]))
        auto, score, _ = extract.classify(pages)
        doc_type = d["doc_type"] if d["doc_type_confirmed"] and d["doc_type"] else auto
        fields = extract.extract_document(doc_type, pages)
        methods = sorted({p["method"] for p in pages})
        conf = round(sum(p["confidence"] for p in pages) / len(pages), 2) if pages else None
        with db.tx() as c:
            if not db.row(c, "SELECT id FROM documents WHERE id=?", (did,)):
                return
            c.execute("DELETE FROM extracted_fields WHERE document_id=?", (did,))
            c.execute("DELETE FROM document_pages WHERE document_id=?", (did,))
            for p in pages:
                c.execute("INSERT INTO document_pages(document_id,page_no,text,method,confidence) VALUES(?,?,?,?,?)",
                          (did, p["page_no"], p["text"], p["method"], p["confidence"]))
            for f in fields:
                c.execute("INSERT INTO extracted_fields(voyage_id,document_id,section,record_key,record_index,field_key,field_label,original_value,value,"
                          "page_no,confidence,method,status,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'EXTRACTED',?)",
                          (d["voyage_id"], did, f["section"], f["record_key"], f["record_index"], f["field_key"], f["field_label"],
                           f["original_value"], f["value"], f["page_no"], f["confidence"], f["method"], db.now()))
            err = None
            if not fields:
                err = "Không trích xuất được trường dữ liệu nào (nội dung không đọc được hoặc chưa có mẫu nhận diện)."
            c.execute("UPDATE documents SET status=?, error=?, doc_type=?, doc_type_auto=?, doc_type_score=?, page_count=?, extraction_method=?, "
                      "avg_confidence=?, processed_at=? WHERE id=?",
                      ("EXTRACTED" if fields else "ERROR", err, doc_type, auto, score, len(pages), "+".join(methods), conf, db.now(), did))
            db.log(c, d["voyage_id"], "EXTRACT", user, reason=f"{d['original_name']}: {len(fields)} trường, loại {doc_type}")
            _touch(c, d["voyage_id"])
    except Exception as e:
        traceback.print_exc()
        with db.tx() as c:
            c.execute("UPDATE documents SET status='ERROR', error=?, processed_at=? WHERE id=?", (str(e)[:500], db.now(), did))


# ------------------------------------------------------------------ extracted fields / review
@app.get("/api/voyages/{vid}/fields")
def get_fields(vid: int, u=Depends(current_user)):
    with db.tx() as c:
        fs = db.rows(c, "SELECT f.*, d.original_name doc_name, d.doc_type FROM extracted_fields f LEFT JOIN documents d ON d.id=f.document_id "
                        "WHERE f.voyage_id=? ORDER BY f.section, d.id, f.record_index, f.id", (vid,))
        flags = {}
        for r in db.rows(c, "SELECT field1_id, field2_id, status FROM crosscheck_results WHERE voyage_id=? AND status NOT IN ('PASSED','NOT_AVAILABLE','NOT_ENOUGH_DATA')", (vid,)):
            for k in ("field1_id", "field2_id"):
                if r[k]:
                    flags.setdefault(r[k], set()).add(r["status"])
        for f in fs:
            f["flags"] = sorted(flags.get(f["id"], []))
            f["low_confidence"] = f["confidence"] is not None and f["confidence"] < extract.LOW_CONF
    return {"fields": fs, "labels": extract.FIELD_LABELS}


class FieldEdit(BaseModel):
    value: str | None
    reason: str | None = None


@app.put("/api/fields/{fid}")
def edit_field(fid: int, body: FieldEdit, u=Depends(current_user)):
    with db.tx() as c:
        f = db.row(c, "SELECT * FROM extracted_fields WHERE id=?", (fid,))
        if not f:
            raise HTTPException(404)
        if (f["value"] or "") == (body.value or ""):
            return f
        c.execute("UPDATE extracted_fields SET value=?, status='EDITED', confirmed_by=NULL, confirmed_at=NULL, updated_at=? WHERE id=?",
                  (body.value, db.now(), fid))
        db.log(c, f["voyage_id"], "EDIT_FIELD", u["username"], fid, f["field_key"], f["value"], body.value, body.reason)
        return db.row(c, "SELECT * FROM extracted_fields WHERE id=?", (fid,))


class IdsIn(BaseModel):
    ids: list[int]
    confirm: bool = True


@app.post("/api/fields/confirm")
def confirm_fields(body: IdsIn, u=Depends(current_user)):
    with db.tx() as c:
        for fid in body.ids:
            f = db.row(c, "SELECT * FROM extracted_fields WHERE id=?", (fid,))
            if not f:
                continue
            if body.confirm and f["status"] != "CONFIRMED":
                c.execute("UPDATE extracted_fields SET status='CONFIRMED', confirmed_by=?, confirmed_at=? WHERE id=?", (u["username"], db.now(), fid))
                db.log(c, f["voyage_id"], "CONFIRM_FIELD", u["username"], fid, f["field_key"], new=f["value"])
            elif not body.confirm and f["status"] == "CONFIRMED":
                st = "EDITED" if (f["value"] or "") != (f["original_value"] or "") else "EXTRACTED"
                c.execute("UPDATE extracted_fields SET status=?, confirmed_by=NULL, confirmed_at=NULL WHERE id=?", (st, fid))
                db.log(c, f["voyage_id"], "UNCONFIRM_FIELD", u["username"], fid, f["field_key"])
    return {"ok": True, "count": len(body.ids)}


class RecordIn(BaseModel):
    section: str
    fields: dict[str, str]


@app.post("/api/voyages/{vid}/records")
def add_record(vid: int, body: RecordIn, u=Depends(current_user)):
    """Staff adds a record that could not be extracted (e.g. unreadable scan). Marked method=manual."""
    if body.section not in ("crew", "passenger", "cargo", "dg", "store", "effects", "vessel"):
        raise HTTPException(400, "Nhóm dữ liệu không hợp lệ")
    with db.tx() as c:
        _voyage_or_404(c, vid)
        n = db.row(c, "SELECT COUNT(DISTINCT record_key) n FROM extracted_fields WHERE voyage_id=? AND document_id IS NULL AND section=?", (vid, body.section))["n"]
        rk = "header" if body.section == "vessel" else f"manual-{body.section}:{n + 1}"
        for k, v in body.fields.items():
            if not (v or "").strip():
                continue
            c.execute("INSERT INTO extracted_fields(voyage_id,document_id,section,record_key,record_index,field_key,field_label,original_value,value,"
                      "page_no,confidence,method,status,updated_at) VALUES(?,NULL,?,?,?,?,?,NULL,?,NULL,NULL,'manual','EDITED',?)",
                      (vid, body.section, rk, 10000 + n + 1, k, extract.FIELD_LABELS.get(k, k), v.strip(), db.now()))
        db.log(c, vid, "ADD_MANUAL_RECORD", u["username"], field_key=body.section, new=str(body.fields))
    return {"ok": True}


@app.delete("/api/fields/{fid}")
def delete_manual_field(fid: int, u=Depends(current_user)):
    with db.tx() as c:
        f = db.row(c, "SELECT * FROM extracted_fields WHERE id=?", (fid,))
        if not f:
            raise HTTPException(404)
        if f["document_id"] is not None:
            raise HTTPException(400, "Chỉ xóa được dữ liệu nhập tay; dữ liệu trích xuất phải sửa hoặc xóa chứng từ.")
        c.execute("DELETE FROM extracted_fields WHERE voyage_id=? AND document_id IS NULL AND record_key=?", (f["voyage_id"], f["record_key"]))
        db.log(c, f["voyage_id"], "DELETE_MANUAL_RECORD", u["username"], fid, f["record_key"])
    return {"ok": True}


@app.get("/api/voyages/{vid}/log")
def review_log(vid: int, u=Depends(current_user)):
    with db.tx() as c:
        return db.rows(c, "SELECT * FROM review_log WHERE voyage_id=? ORDER BY id DESC LIMIT 500", (vid,))


# ------------------------------------------------------------------ cross-check
@app.post("/api/voyages/{vid}/crosscheck")
def run_crosscheck(vid: int, u=Depends(current_user)):
    with db.tx() as c:
        _voyage_or_404(c, vid)
        pending = db.row(c, "SELECT COUNT(*) n FROM documents WHERE voyage_id=? AND status IN ('PROCESSING','UPLOADED')", (vid,))["n"]
        if pending:
            raise HTTPException(409, f"Còn {pending} chứng từ đang xử lý - vui lòng chờ.")
        run_id, summary = crosscheck.run(c, vid, u["username"])
        db.log(c, vid, "CROSSCHECK", u["username"], reason=str(summary))
    return get_crosscheck(vid, u)


@app.get("/api/voyages/{vid}/crosscheck")
def get_crosscheck(vid: int, u=Depends(current_user)):
    with db.tx() as c:
        run = db.row(c, "SELECT * FROM crosscheck_runs WHERE voyage_id=? ORDER BY id DESC LIMIT 1", (vid,))
        res = db.rows(c, "SELECT r.*, d1.original_name doc1_name, d1.doc_type doc1_type, d2.original_name doc2_name, d2.doc_type doc2_type "
                         "FROM crosscheck_results r LEFT JOIN documents d1 ON d1.id=r.doc1_id LEFT JOIN documents d2 ON d2.id=r.doc2_id "
                         "WHERE r.voyage_id=? ORDER BY r.group_name, r.blocking DESC, r.id", (vid,))
        for r in res:
            r["field_label"] = extract.FIELD_LABELS.get(r["field_key"], r["field_key"])
        v = _voyage_or_404(c, vid)
        prog = voyage_progress(c, v)
    return {"run": run, "results": res, "fresh": prog["check_fresh"]}


class ResolveIn(BaseModel):
    action: str  # use1 | use2 | custom
    value: str | None = None
    note: str | None = None


@app.post("/api/crosscheck/{rid}/resolve")
def resolve(rid: int, body: ResolveIn, u=Depends(current_user)):
    """Staff decides the correct value; both source fields are set to it (originals kept) and logged."""
    with db.tx() as c:
        r = db.row(c, "SELECT * FROM crosscheck_results WHERE id=?", (rid,))
        if not r:
            raise HTTPException(404)
        value = {"use1": r["value1"], "use2": r["value2"], "custom": body.value}.get(body.action)
        if value is None:
            raise HTTPException(400, "Thiếu giá trị")
        for fid in (r["field1_id"], r["field2_id"]):
            if not fid:
                continue
            f = db.row(c, "SELECT * FROM extracted_fields WHERE id=?", (fid,))
            if f and (f["value"] or "") != value:
                c.execute("UPDATE extracted_fields SET value=?, status='CONFIRMED', confirmed_by=?, confirmed_at=?, updated_at=? WHERE id=?",
                          (value, u["username"], db.now(), db.now(), fid))
                db.log(c, r["voyage_id"], "RESOLVE_MISMATCH", u["username"], fid, f["field_key"], f["value"], value, body.note)
            elif f:
                c.execute("UPDATE extracted_fields SET status='CONFIRMED', confirmed_by=?, confirmed_at=? WHERE id=?", (u["username"], db.now(), fid))
        crosscheck.run(c, r["voyage_id"], u["username"])
    return {"ok": True}


class AckIn(BaseModel):
    note: str


@app.post("/api/crosscheck/{rid}/ack")
def acknowledge(rid: int, body: AckIn, u=Depends(current_user)):
    """Staff confirms a difference is legitimate (e.g. different scope); both values stay as they are."""
    if not body.note.strip():
        raise HTTPException(400, "Cần ghi lý do chấp nhận khác biệt")
    with db.tx() as c:
        r = db.row(c, "SELECT * FROM crosscheck_results WHERE id=?", (rid,))
        if not r:
            raise HTTPException(404)
        c.execute("INSERT INTO crosscheck_acks(voyage_id,check_key,value1,value2,note,user,at) VALUES(?,?,?,?,?,?,?)",
                  (r["voyage_id"], r["check_key"], r["value1"] or "", r["value2"] or "", body.note, u["username"], db.now()))
        c.execute("UPDATE crosscheck_results SET acknowledged=1, blocking=0, ack_note=? WHERE id=?", (body.note, rid))
        db.log(c, r["voyage_id"], "ACK_DIFFERENCE", u["username"], field_key=r["field_key"], old=r["value1"], new=r["value2"], reason=body.note)
    return {"ok": True}


# ------------------------------------------------------------------ export
@app.get("/api/voyages/{vid}/export/options")
def get_options(vid: int, u=Depends(current_user)):
    with db.tx() as c:
        _voyage_or_404(c, vid)
        o = nsw_export._opts(c, vid)
    return {"options": o, "signers": nsw_export.SIGNERS, "name_splits": nsw_export.NAME_SPLITS,
            "passport_types": N.CODES["passport_types"], "doc_functions": {"CN01": "Thêm mới bản khai (Create)", "CN02": "Sửa bản khai (Update)", "CN03": "Xóa bản khai (Delete)"},
            "manual_cells": [{"sheet": s, "cell": ref, "label": lbl, "spec": spec} for s, (rows, _) in nsw_export.SHEET_HEADERS.items()
                             for ref, lbl, spec in rows if spec.startswith(("manual", "src", "derived"))],
            "codes": {"rank": N.CODES["ranks"], "state": N.CODES["states"], "package": N.CODES["package_kinds"],
                      "unit": sorted(N.CODES["units"]), "gender": {"Nam/Man": "Nam/Man", "Nữ/Woman": "Nữ/Woman"}}}


@app.put("/api/voyages/{vid}/export/options")
def set_options(vid: int, body: dict, u=Depends(current_user)):
    with db.tx() as c:
        _voyage_or_404(c, vid)
        old = nsw_export._opts(c, vid)
        for k, v in body.items():
            if (old.get(k) or "") == (v or ""):
                continue
            c.execute("INSERT INTO export_options(voyage_id,key,value) VALUES(?,?,?) ON CONFLICT(voyage_id,key) DO UPDATE SET value=excluded.value", (vid, k, v))
            db.log(c, vid, "SET_EXPORT_OPTION", u["username"], field_key=k, old=old.get(k), new=v)
    return get_options(vid, u)


@app.get("/api/voyages/{vid}/export/readiness")
def export_readiness(vid: int, u=Depends(current_user)):
    with db.tx() as c:
        _voyage_or_404(c, vid)
        return nsw_export.readiness(c, vid)


class ExportIn(BaseModel):
    override_username: str | None = None
    override_password: str | None = None
    override_reason: str | None = None


@app.post("/api/voyages/{vid}/export")
def do_export(vid: int, body: ExportIn, u=Depends(current_user)):
    with db.tx() as c:
        v = _voyage_or_404(c, vid)
        rd = nsw_export.readiness(c, vid)
        override_by = None
        if not rd["ready"]:
            if not (body.override_username and body.override_password and (body.override_reason or "").strip()):
                raise HTTPException(409, {"message": "Chưa đủ điều kiện xuất file", "blockers": rd["blockers"]})
            sup = db.row(c, "SELECT * FROM users WHERE username=?", (body.override_username,))
            if not sup or sup["role"] != "supervisor" or not db.verify_password(body.override_password, sup["password_hash"]):
                raise HTTPException(403, "Xác nhận ngoại lệ thất bại: cần tài khoản Supervisor hợp lệ")
            override_by = sup["username"]
        plan, _ = nsw_export.build_plan(c, vid)
    name = f"NSW_{v['voyage_code']}_{(v['vessel_name'] or 'VESSEL').replace(' ', '_')}_{db.local_now():%Y%m%d_%H%M%S}.xlsx"
    stored = f"{vid}_{secrets.token_hex(6)}.xlsx"
    out = os.path.join(db.EXPORT_DIR, stored)
    try:
        written = nsw_export.write_workbook(db.TEMPLATE_PATH, plan, out)
    except ValueError as e:
        raise HTTPException(400, str(e))
    checks = nsw_export.verify(db.TEMPLATE_PATH, out, written)
    report = {"checks": checks, "warnings": rd["warnings"], "empty": rd["empty"], "blockers_overridden": rd["blockers"] if override_by else [],
              "cells_written": len(written), "rows": {s: len(r) for s, r in plan.tables.items()}}
    with db.tx() as c:
        cur = c.execute("INSERT INTO exports(voyage_id,file_name,stored_name,created_by,created_at,override_used,override_by,override_reason,report_json) "
                        "VALUES(?,?,?,?,?,?,?,?,?)", (vid, name, stored, u["username"], db.now(), 1 if override_by else 0, override_by,
                                                      body.override_reason if override_by else None, db.dumps(report)))
        db.log(c, vid, "EXPORT_EXCEL", u["username"], new=name, reason=("NGOẠI LỆ bởi " + override_by + ": " + body.override_reason) if override_by else None)
        _touch(c, vid)
        eid = cur.lastrowid
    return {"id": eid, "file_name": name, "report": report}


@app.get("/api/voyages/{vid}/exports")
def list_exports(vid: int, u=Depends(current_user)):
    import json
    with db.tx() as c:
        es = db.rows(c, "SELECT * FROM exports WHERE voyage_id=? ORDER BY id DESC", (vid,))
    for e in es:
        e["report"] = json.loads(e.pop("report_json") or "{}")
    return es


@app.get("/api/exports/{eid}/download")
def download_export(eid: int, token: str = ""):
    current_user("Bearer " + token)
    with db.tx() as c:
        e = db.row(c, "SELECT * FROM exports WHERE id=?", (eid,))
    if not e:
        raise HTTPException(404)
    return FileResponse(os.path.join(db.EXPORT_DIR, e["stored_name"]), filename=e["file_name"],
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ------------------------------------------------------------------ history
@app.get("/api/history")
def history(u=Depends(current_user)):
    with db.tx() as c:
        vs = db.rows(c, "SELECT * FROM voyages ORDER BY id DESC")
        for v in vs:
            v["progress"] = voyage_progress(c, v)
            v["documents"] = db.rows(c, "SELECT id, original_name, doc_type, status, uploaded_at FROM documents WHERE voyage_id=? ORDER BY id", (v["id"],))
            v["exports"] = db.rows(c, "SELECT id, file_name, created_at, created_by, override_used FROM exports WHERE voyage_id=? ORDER BY id DESC", (v["id"],))
    return vs


# ------------------------------------------------------------------ settings & samples
@app.get("/api/settings")
def settings(u=Depends(current_user)):
    with db.tx() as c:
        users = db.rows(c, "SELECT id, username, full_name, role, created_at FROM users ORDER BY id")
    tpl = nsw_export.Book(db.TEMPLATE_PATH)
    return {"ocr": ingest.ocr_status(), "template": {"path": os.path.basename(db.TEMPLATE_PATH), "sheets": tpl.sheet_names, "states": tpl.sheet_state},
            "codes": {k: len(v) for k, v in N.CODES.items()}, "users": users, "doc_types": extract.DOC_TYPES,
            "mapping": {"headers": {s: [{"cell": r, "label": l, "source": sp} for r, l, sp in rows] for s, (rows, _) in nsw_export.SHEET_HEADERS.items()},
                        "tables": nsw_export.TABLES, "clear_only": nsw_export.CLEAR_ONLY},
            "low_confidence_threshold": extract.LOW_CONF}


class UserIn(BaseModel):
    username: str
    full_name: str
    password: str
    role: str = "staff"


@app.post("/api/users")
def create_user(body: UserIn, u=Depends(supervisor)):
    if body.role not in ("staff", "supervisor") or len(body.password) < 6:
        raise HTTPException(400, "Vai trò không hợp lệ hoặc mật khẩu < 6 ký tự")
    with db.tx() as c:
        try:
            c.execute("INSERT INTO users(username,full_name,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                      (body.username.strip(), body.full_name, db.hash_password(body.password), body.role, db.now()))
        except Exception:
            raise HTTPException(400, "Tên đăng nhập đã tồn tại")
    return {"ok": True}


class PwIn(BaseModel):
    old_password: str
    new_password: str


@app.post("/api/me/password")
def change_password(body: PwIn, u=Depends(current_user)):
    with db.tx() as c:
        full = db.row(c, "SELECT * FROM users WHERE id=?", (u["id"],))
        if not db.verify_password(body.old_password, full["password_hash"]) or len(body.new_password) < 6:
            raise HTTPException(400, "Mật khẩu cũ sai hoặc mật khẩu mới < 6 ký tự")
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (db.hash_password(body.new_password), u["id"]))
    return {"ok": True}


@app.post("/api/samples/{scenario}")
def create_sample(scenario: int, u=Depends(current_user)):
    """Create a SAMPLE voyage (is_sample=1) with generated documents for test scenario 1/2/3."""
    if scenario not in (1, 2, 3):
        raise HTTPException(400)
    with tempfile.TemporaryDirectory() as td:
        files = samples.generate(scenario, td)
        with db.tx() as c:
            vid = _create_voyage(c, {"notes": f"DỮ LIỆU MẪU - Tình huống kiểm thử {scenario}. Không dùng cho khai báo thật."}, u["username"], is_sample=True)
            ids = []
            for p in files:
                class F:  # minimal UploadFile stand-in
                    filename = os.path.basename(p)
                    file = open(p, "rb")
                did, _ = _save_upload(vid, F, u["username"], c)
                F.file.close()
                ids.append(did)
    for did in ids:
        _queue(did, u["username"])
    return {"voyage_id": vid}


@app.get("/api/health")
def health():
    return {"ok": True, "ocr": ingest.ocr_status()}


# ------------------------------------------------------------------ frontend
DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "dist")
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        p = os.path.join(DIST, path)
        if path and os.path.isfile(p):
            return FileResponse(p)
        return FileResponse(os.path.join(DIST, "index.html"))
