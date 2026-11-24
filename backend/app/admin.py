"""Admin workspace API (supervisor only): accounts, permissions, catalogs, NSW template,
access/activity monitoring, backup & restore, user statistics."""
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import db, nsw_export
from . import normalize as N

ROLES = {"supervisor": "Quản trị viên (Admin Workspace)", "staff": "Nhân viên (Staff Workspace)"}

# What each role may do. The API enforces the same split (admin endpoints require a supervisor).
PERMISSIONS = [
    ("Staff Workspace", "Quản lý chuyến tàu (xem, sửa, mở, lưu trữ)", True, True),
    ("Staff Workspace", "Tạo chuyến tàu mới", True, True),
    ("Staff Workspace", "Tải chứng từ, xử lý chứng từ, trích xuất dữ liệu", True, True),
    ("Staff Workspace", "Đối chiếu dữ liệu", True, True),
    ("Staff Workspace", "Kiểm tra và xác nhận", True, True),
    ("Staff Workspace", "Xuất file Excel NSW", True, True),
    ("Staff Workspace", "Lịch sử xử lý, Lưu trữ, Thùng rác (xem)", True, True),
    ("Duyệt ngoại lệ", "Xóa chuyến tàu vào Thùng rác, xóa vĩnh viễn", False, True),
    ("Duyệt ngoại lệ", "Xuất Excel khi còn lỗi chặn (mật khẩu Supervisor)", False, True),
    ("Admin Workspace", "Quản lý tài khoản, phân quyền", False, True),
    ("Admin Workspace", "Quản lý danh mục, hồ sơ tàu", False, True),
    ("Admin Workspace", "Quản lý mẫu NSW", False, True),
    ("Admin Workspace", "Giám sát hoạt động, lịch sử truy cập, sao lưu & khôi phục", False, True),
    ("Admin Workspace", "Thống kê người dùng và hoạt động", False, True),
]

CATALOGS = {
    "states": "Quốc gia / quốc tịch (NSW)", "ranks": "Chức danh thuyền viên (NSW)", "package_kinds": "Loại kiện hàng (NSW)",
    "unit_names": "Đơn vị tính (NSW)", "container_types": "Loại container (NSW)", "passport_types": "Loại hộ chiếu (NSW)",
    "ports": "Cảng biển UN/LOCODE", "countries": "Mã quốc gia ISO",
}
DATA = os.path.join(os.path.dirname(__file__), "data")
SAFE_NAME = re.compile(r"^[\w.\-]+\.zip$")


def _tsv(name):
    out = []
    with open(os.path.join(DATA, name), encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or "\t" not in line:
                continue
            a, b = line.rstrip("\n").split("\t", 1)
            out.append((a, b))
    return out


def _catalog(name):
    if name == "ports":
        return _tsv("unlocode_ports.tsv")
    if name == "countries":
        return _tsv("countries.tsv")
    v = N.CODES.get(name)
    if isinstance(v, dict):
        return sorted(v.items())
    if isinstance(v, (list, set, tuple)):
        return [(str(x), "") for x in sorted(v)]
    return []


def _mtime(path):
    from zoneinfo import ZoneInfo
    return db.datetime.fromtimestamp(os.stat(path).st_mtime, ZoneInfo(os.environ.get("SGCL_TZ", "Asia/Ho_Chi_Minh"))).strftime("%Y-%m-%d %H:%M:%S")


def _template_info():
    path = db.TEMPLATE_PATH
    book = nsw_export.Book(path)
    st = os.stat(path)
    return {"file": os.path.basename(path), "custom": os.path.abspath(path) == os.path.abspath(db.CUSTOM_TEMPLATE),
            "size": st.st_size, "modified": _mtime(path),
            "sheets": book.sheet_names, "states": book.sheet_state}


def _snapshot_db(dest):
    src = sqlite3.connect(db.DB_PATH, timeout=30)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _make_backup(label, user):
    os.makedirs(db.BACKUP_DIR, exist_ok=True)
    name = f"sgcl-backup-{db.local_now().strftime('%Y%m%d-%H%M%S')}{'-' + label if label else ''}.zip"
    path = os.path.join(db.BACKUP_DIR, name)
    with tempfile.TemporaryDirectory() as td:
        snap = os.path.join(td, "sgcl.db")
        _snapshot_db(snap)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "sgcl.db")
            for sub in ("uploads", "exports", "templates"):
                base = os.path.join(db.DATA_DIR, sub)
                for root, _, files in os.walk(base):
                    for f in files:
                        full = os.path.join(root, f)
                        z.write(full, os.path.relpath(full, db.DATA_DIR))
    with db.tx() as c:
        db.admin_log(c, "BACKUP", user, name)
    return name


def _backup_path(name):
    if not SAFE_NAME.match(name):
        raise HTTPException(400, "Tên file sao lưu không hợp lệ")
    p = os.path.join(db.BACKUP_DIR, name)
    if not os.path.isfile(p):
        raise HTTPException(404, "Không tìm thấy bản sao lưu")
    return p


def _check_zip(path):
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise HTTPException(400, "File không phải bản sao lưu SGCL (.zip)")
    with z:
        names = z.namelist()
        if "sgcl.db" not in names:
            raise HTTPException(400, "Bản sao lưu không có cơ sở dữ liệu sgcl.db")
        for n in names:
            parts = n.replace("\\", "/").split("/")
            if n.startswith("/") or ".." in parts or (n != "sgcl.db" and parts[0] not in ("uploads", "exports", "templates")):
                raise HTTPException(400, f"Bản sao lưu chứa đường dẫn không hợp lệ: {n}")
        with tempfile.TemporaryDirectory() as td:
            z.extract("sgcl.db", td)
            try:
                con = sqlite3.connect(os.path.join(td, "sgcl.db"))
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                con.close()
            except sqlite3.DatabaseError:
                raise HTTPException(400, "Cơ sở dữ liệu trong bản sao lưu bị hỏng")
            if not {"users", "voyages", "documents"} <= tables:
                raise HTTPException(400, "Cơ sở dữ liệu trong bản sao lưu không phải của SGCL")


class UserEdit(BaseModel):
    full_name: str | None = None
    role: str | None = None
    active: bool | None = None


class PasswordSet(BaseModel):
    new_password: str


def build_router(current_user, supervisor):
    r = APIRouter(prefix="/api/admin")

    # ---------------------------------------------------------------- accounts & permissions
    @r.get("/users")
    def users(u=Depends(supervisor)):
        with db.tx() as c:
            rows = db.rows(c, "SELECT id, username, full_name, role, COALESCE(active,1) active, created_at FROM users ORDER BY id")
            for x in rows:
                last = db.row(c, "SELECT at, ip FROM access_log WHERE username=? AND action='LOGIN' ORDER BY id DESC LIMIT 1", (x["username"],))
                x["last_login"] = last["at"] if last else None
                x["last_ip"] = last["ip"] if last else None
                x["online"] = bool(c.execute("SELECT 1 FROM sessions WHERE user_id=?", (x["id"],)).fetchone())
        return rows

    @r.put("/users/{uid}")
    def edit_user(uid: int, body: UserEdit, u=Depends(supervisor)):
        with db.tx() as c:
            t = db.row(c, "SELECT * FROM users WHERE id=?", (uid,))
            if not t:
                raise HTTPException(404, "Không tìm thấy tài khoản")
            role = body.role if body.role is not None else t["role"]
            active = int(body.active) if body.active is not None else int(t.get("active", 1) if t.get("active") is not None else 1)
            if role not in ROLES:
                raise HTTPException(400, "Vai trò không hợp lệ")
            if uid == u["id"] and (role != "supervisor" or not active):
                raise HTTPException(400, "Không thể tự hạ quyền hoặc tự khóa tài khoản đang đăng nhập")
            if t["role"] == "supervisor" and (role != "supervisor" or not active):
                others = c.execute("SELECT COUNT(*) FROM users WHERE role='supervisor' AND COALESCE(active,1)=1 AND id<>?", (uid,)).fetchone()[0]
                if not others:
                    raise HTTPException(400, "Phải còn ít nhất một tài khoản quản trị đang hoạt động")
            name = (body.full_name or t["full_name"]).strip() or t["full_name"]
            c.execute("UPDATE users SET full_name=?, role=?, active=? WHERE id=?", (name, role, active, uid))
            if not active:
                c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            changes = []
            if name != t["full_name"]:
                changes.append(f"Họ tên: {t['full_name']} → {name}")
            if role != t["role"]:
                changes.append(f"Vai trò: {t['role']} → {role}")
            if active != (t.get("active") if t.get("active") is not None else 1):
                changes.append("Mở khóa" if active else "Khóa tài khoản")
            if changes:
                db.admin_log(c, "EDIT_USER", u["username"], t["username"], "; ".join(changes))
        return {"ok": True}

    @r.post("/users/{uid}/password")
    def set_password(uid: int, body: PasswordSet, u=Depends(supervisor)):
        if len(body.new_password) < 6:
            raise HTTPException(400, "Mật khẩu mới phải có ít nhất 6 ký tự")
        with db.tx() as c:
            t = db.row(c, "SELECT username FROM users WHERE id=?", (uid,))
            if not t:
                raise HTTPException(404, "Không tìm thấy tài khoản")
            c.execute("UPDATE users SET password_hash=? WHERE id=?", (db.hash_password(body.new_password), uid))
            if uid != u["id"]:
                c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            db.admin_log(c, "SET_PASSWORD", u["username"], t["username"], "Đặt lại mật khẩu")
        return {"ok": True}

    @r.post("/users/{uid}/logout")
    def force_logout(uid: int, u=Depends(supervisor)):
        if uid == u["id"]:
            raise HTTPException(400, "Dùng nút Đăng xuất để thoát phiên của chính mình")
        with db.tx() as c:
            t = db.row(c, "SELECT username FROM users WHERE id=?", (uid,))
            if not t:
                raise HTTPException(404, "Không tìm thấy tài khoản")
            c.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            db.admin_log(c, "FORCE_LOGOUT", u["username"], t["username"], "Buộc đăng xuất")
        return {"ok": True}

    @r.get("/permissions")
    def permissions(u=Depends(supervisor)):
        return {"roles": ROLES, "matrix": [{"group": g, "action": a, "staff": s, "supervisor": p} for g, a, s, p in PERMISSIONS]}

    # ---------------------------------------------------------------- catalogs
    @r.get("/catalogs")
    def catalogs(u=Depends(supervisor)):
        return [{"name": k, "label": v, "count": len(_catalog(k))} for k, v in CATALOGS.items()]

    @r.get("/catalogs/{name}")
    def catalog(name: str, q: str = "", limit: int = 300, u=Depends(supervisor)):
        if name not in CATALOGS:
            raise HTTPException(404, "Không có danh mục này")
        items = _catalog(name)
        if q.strip():
            k = N.norm_text(q)
            items = [x for x in items if k in N.norm_text(f"{x[0]} {x[1]}")]
        return {"name": name, "label": CATALOGS[name], "total": len(items),
                "items": [{"code": a, "name": b} for a, b in items[:max(1, min(limit, 2000))]]}

    # ---------------------------------------------------------------- NSW template
    @r.get("/template")
    def template(u=Depends(supervisor)):
        info = _template_info()
        info["codes"] = {k: len(v) for k, v in N.CODES.items()}
        with db.tx() as c:
            info["history"] = db.rows(c, "SELECT action, detail, user, at FROM admin_log WHERE action LIKE 'TEMPLATE%' ORDER BY id DESC LIMIT 20")
        return info

    def link_user(token):   # links opened in the browser carry the token in the query string
        return supervisor(current_user("Bearer " + token))

    @r.get("/template/download")
    def template_download(token: str = ""):
        link_user(token)
        return FileResponse(db.TEMPLATE_PATH, filename="TemplateNSW.xlsx")

    @r.post("/template")
    async def template_upload(file: UploadFile = File(...), u=Depends(supervisor)):
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise HTTPException(400, "Mẫu NSW phải là file .xlsx")
        data = await file.read()
        with tempfile.TemporaryDirectory() as td:
            tmp = os.path.join(td, "TemplateNSW.xlsx")
            with open(tmp, "wb") as fh:
                fh.write(data)
            try:
                new = nsw_export.Book(tmp)
            except Exception:
                raise HTTPException(400, "Không đọc được file Excel này")
            need = nsw_export.Book(db.DEFAULT_TEMPLATE).sheet_names
            missing = [s for s in need if s not in new.sheet_names]
            if missing:
                raise HTTPException(400, "Mẫu mới thiếu sheet: " + ", ".join(missing) + ". Hệ thống điền theo đúng tên và vị trí ô của mẫu NSW nên không dùng được mẫu này.")
            try:
                N.load_codes_from_template(tmp)
            except Exception:
                N.load_codes_from_template(db.TEMPLATE_PATH)
                raise HTTPException(400, "Không đọc được danh mục mã trong sheet Declaration list của mẫu mới")
            os.makedirs(os.path.dirname(db.CUSTOM_TEMPLATE), exist_ok=True)
            if os.path.isfile(db.CUSTOM_TEMPLATE):
                old = os.path.join(db.BACKUP_DIR, "templates")
                os.makedirs(old, exist_ok=True)
                shutil.copy2(db.CUSTOM_TEMPLATE, os.path.join(old, f"TemplateNSW-{db.local_now().strftime('%Y%m%d-%H%M%S')}.xlsx"))
            shutil.copy2(tmp, db.CUSTOM_TEMPLATE)
        db.TEMPLATE_PATH = db.active_template()
        with db.tx() as c:
            db.admin_log(c, "TEMPLATE_UPLOAD", u["username"], file.filename, f"Thay mẫu NSW bằng {file.filename}")
        return _template_info()

    @r.delete("/template")
    def template_reset(u=Depends(supervisor)):
        if os.path.isfile(db.CUSTOM_TEMPLATE):
            old = os.path.join(db.BACKUP_DIR, "templates")
            os.makedirs(old, exist_ok=True)
            shutil.move(db.CUSTOM_TEMPLATE, os.path.join(old, f"TemplateNSW-{db.local_now().strftime('%Y%m%d-%H%M%S')}.xlsx"))
        db.TEMPLATE_PATH = db.active_template()
        N.load_codes_from_template(db.TEMPLATE_PATH)
        with db.tx() as c:
            db.admin_log(c, "TEMPLATE_RESET", u["username"], None, "Dùng lại mẫu NSW gốc của hệ thống")
        return _template_info()

    # ---------------------------------------------------------------- monitoring
    @r.get("/access")
    def access_log(user: str = "", action: str = "", limit: int = 300, u=Depends(supervisor)):
        sql, args = "SELECT * FROM access_log WHERE 1=1", []
        if user:
            sql += " AND username=?"
            args.append(user)
        if action:
            sql += " AND action=?"
            args.append(action)
        with db.tx() as c:
            return db.rows(c, sql + " ORDER BY id DESC LIMIT ?", args + [max(1, min(limit, 2000))])

    @r.get("/activity")
    def activity(user: str = "", limit: int = 300, u=Depends(supervisor)):
        lim = max(1, min(limit, 2000))
        with db.tx() as c:
            rows = db.rows(c, """
                SELECT l.at, l.user, l.action, v.voyage_code AS target, COALESCE(l.reason, l.field_key, '') AS detail, 'voyage' AS kind
                  FROM review_log l LEFT JOIN voyages v ON v.id=l.voyage_id
                UNION ALL
                SELECT at, user, action, target, detail, 'admin' FROM admin_log
                ORDER BY at DESC LIMIT ?""", (lim * 3,))
        if user:
            rows = [x for x in rows if x["user"] == user]
        return rows[:lim]

    @r.get("/system")
    def system(u=Depends(supervisor)):
        from . import ingest
        size = 0
        for sub in ("uploads", "exports", "backups", "templates"):
            for root, _, files in os.walk(os.path.join(db.DATA_DIR, sub)):
                size += sum(os.path.getsize(os.path.join(root, f)) for f in files)
        size += os.path.getsize(db.DB_PATH) if os.path.isfile(db.DB_PATH) else 0
        with db.tx() as c:
            n = {k: c.execute(q).fetchone()[0] for k, q in (
                ("voyages", "SELECT COUNT(*) FROM voyages"), ("documents", "SELECT COUNT(*) FROM documents"),
                ("exports", "SELECT COUNT(*) FROM exports"), ("sessions", "SELECT COUNT(*) FROM sessions"))}
        return {"ocr": ingest.ocr_status(), "data_size": size, "counts": n}

    # ---------------------------------------------------------------- backup & restore
    @r.get("/backups")
    def backups(u=Depends(supervisor)):
        out = []
        if os.path.isdir(db.BACKUP_DIR):
            for f in sorted(os.listdir(db.BACKUP_DIR), reverse=True):
                p = os.path.join(db.BACKUP_DIR, f)
                if f.endswith(".zip") and os.path.isfile(p):
                    st = os.stat(p)
                    out.append({"name": f, "size": st.st_size, "created_at": _mtime(p)})
        with db.tx() as c:
            hist = db.rows(c, "SELECT action, target, detail, user, at FROM admin_log WHERE action IN ('BACKUP','RESTORE','BACKUP_UPLOAD','BACKUP_DELETE') ORDER BY id DESC LIMIT 30")
        return {"backups": out, "history": hist}

    @r.post("/backups")
    def backup_now(u=Depends(supervisor)):
        return {"name": _make_backup("", u["username"])}

    @r.post("/backups/upload")
    async def backup_upload(file: UploadFile = File(...), u=Depends(supervisor)):
        base = re.sub(r"[^\w.\-]", "_", os.path.basename(file.filename or "backup.zip"))
        if not base.lower().endswith(".zip"):
            raise HTTPException(400, "Bản sao lưu phải là file .zip do SGCL tạo")
        os.makedirs(db.BACKUP_DIR, exist_ok=True)
        name = f"uploaded-{db.local_now().strftime('%Y%m%d-%H%M%S')}-{base}"
        path = os.path.join(db.BACKUP_DIR, name)
        with open(path, "wb") as fh:
            shutil.copyfileobj(file.file, fh)
        try:
            _check_zip(path)
        except HTTPException:
            os.remove(path)
            raise
        with db.tx() as c:
            db.admin_log(c, "BACKUP_UPLOAD", u["username"], name)
        return {"name": name}

    @r.get("/backups/{name}/download")
    def backup_download(name: str, token: str = ""):
        link_user(token)
        return FileResponse(_backup_path(name), filename=name, media_type="application/zip")

    @r.delete("/backups/{name}")
    def backup_delete(name: str, u=Depends(supervisor)):
        os.remove(_backup_path(name))
        with db.tx() as c:
            db.admin_log(c, "BACKUP_DELETE", u["username"], name)
        return {"ok": True}

    @r.post("/backups/{name}/restore")
    def backup_restore(name: str, u=Depends(supervisor)):
        path = _backup_path(name)
        _check_zip(path)
        safety = _make_backup("truoc-khoi-phuc", u["username"])   # current state is kept before anything is replaced
        with tempfile.TemporaryDirectory(dir=db.DATA_DIR) as td:
            with zipfile.ZipFile(path) as z:
                z.extractall(td)
            src = sqlite3.connect(os.path.join(td, "sgcl.db"))
            dst = sqlite3.connect(db.DB_PATH, timeout=60)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            for sub in ("uploads", "exports", "templates"):
                target = os.path.join(db.DATA_DIR, sub)
                if os.path.isdir(target):
                    shutil.rmtree(target)
                if os.path.isdir(os.path.join(td, sub)):
                    shutil.move(os.path.join(td, sub), target)
        db.init_db()                       # migrations for backups made by older versions
        N.load_codes_from_template(db.TEMPLATE_PATH)
        with db.tx() as c:
            db.admin_log(c, "RESTORE", u["username"], name, f"Khôi phục dữ liệu. Trạng thái trước đó đã lưu thành {safety}")
        return {"ok": True, "safety_backup": safety}

    # ---------------------------------------------------------------- statistics
    @r.get("/stats")
    def stats(days: int = 30, u=Depends(supervisor)):
        days = max(1, min(days, 365))
        since = (db.local_now() - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
        with db.tx() as c:
            users = db.rows(c, "SELECT id, username, full_name, role, COALESCE(active,1) active FROM users ORDER BY id")
            for x in users:
                n = x["username"]
                one = lambda q, a=(): c.execute(q, a).fetchone()[0]  # noqa: E731
                x["logins"] = one("SELECT COUNT(*) FROM access_log WHERE username=? AND action='LOGIN' AND at>=?", (n, since))
                x["failed"] = one("SELECT COUNT(*) FROM access_log WHERE username=? AND action IN ('LOGIN_FAILED','LOCKED') AND at>=?", (n, since))
                x["voyages"] = one("SELECT COUNT(*) FROM voyages WHERE created_by=? AND created_at>=?", (n, since))
                x["documents"] = one("SELECT COUNT(*) FROM documents WHERE uploaded_by=? AND uploaded_at>=? AND parent_id IS NULL", (n, since))
                x["edits"] = one("SELECT COUNT(*) FROM review_log WHERE user=? AND at>=? AND action NOT IN ('UPLOAD','CREATE_VOYAGE','EXPORT_EXCEL')", (n, since))
                x["exports"] = one("SELECT COUNT(*) FROM exports WHERE created_by=? AND created_at>=?", (n, since))
                last = db.row(c, "SELECT MAX(at) t FROM (SELECT at FROM access_log WHERE username=? UNION ALL SELECT at FROM review_log WHERE user=?)", (n, n))
                x["last_active"] = last["t"] if last else None
            daily = {}
            for q, k in (("SELECT substr(at,1,10) d, COUNT(*) FROM access_log WHERE action='LOGIN' AND at>=? GROUP BY d", "logins"),
                         ("SELECT substr(created_at,1,10) d, COUNT(*) FROM voyages WHERE created_at>=? GROUP BY d", "voyages"),
                         ("SELECT substr(uploaded_at,1,10) d, COUNT(*) FROM documents WHERE uploaded_at>=? AND parent_id IS NULL GROUP BY d", "documents"),
                         ("SELECT substr(created_at,1,10) d, COUNT(*) FROM exports WHERE created_at>=? GROUP BY d", "exports")):
                for d, cnt in c.execute(q, (since,)).fetchall():
                    daily.setdefault(d, {"date": d, "logins": 0, "voyages": 0, "documents": 0, "exports": 0})[k] = cnt
        totals = {k: sum(x[k] for x in users) for k in ("logins", "failed", "voyages", "documents", "edits", "exports")}
        return {"days": days, "since": since[:10], "users": users, "totals": totals,
                "daily": sorted(daily.values(), key=lambda x: x["date"], reverse=True)}

    return r
