"""SQLite persistence layer.

Every business table carries voyage_id so data of different voyages never mixes.
"""
import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("SGCL_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "sgcl.db")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
DEFAULT_TEMPLATE = os.path.join(BASE_DIR, "templates", "TemplateNSW.xlsx")
CUSTOM_TEMPLATE = os.path.join(DATA_DIR, "templates", "TemplateNSW.xlsx")   # uploaded in the admin workspace


def active_template():
    if os.environ.get("SGCL_TEMPLATE"):
        return os.environ["SGCL_TEMPLATE"]
    return CUSTOM_TEMPLATE if os.path.isfile(CUSTOM_TEMPLATE) else DEFAULT_TEMPLATE


TEMPLATE_PATH = active_template()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  full_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'staff',          -- staff | supervisor
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS access_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT, action TEXT NOT NULL,          -- LOGIN | LOGIN_FAILED | LOGOUT | LOCKED
  ip TEXT, user_agent TEXT, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS admin_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  action TEXT NOT NULL, target TEXT, detail TEXT, user TEXT, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vessel_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vessel_name TEXT NOT NULL,
  imo TEXT,
  call_sign TEXT,
  flag TEXT,
  gross_tonnage TEXT,
  net_tonnage TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS voyages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  voyage_code TEXT UNIQUE NOT NULL,
  vessel_profile_id INTEGER REFERENCES vessel_profiles(id),
  vessel_name TEXT, imo TEXT, call_sign TEXT, flag TEXT,
  voyage_no TEXT, port_of_arrival TEXT, last_port TEXT, next_port TEXT,
  eta TEXT, etd TEXT, cargo_type TEXT, notes TEXT,
  status TEXT NOT NULL DEFAULT 'NEW',
  is_sample INTEGER NOT NULL DEFAULT 0,
  created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  voyage_id INTEGER NOT NULL REFERENCES voyages(id) ON DELETE CASCADE,
  original_name TEXT NOT NULL, stored_name TEXT NOT NULL, ext TEXT, size INTEGER, sha256 TEXT,
  doc_type TEXT, doc_type_auto TEXT, doc_type_score REAL, doc_type_confirmed INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'UPLOADED',     -- UPLOADED | PROCESSING | EXTRACTED | ERROR
  error TEXT, page_count INTEGER, extraction_method TEXT, avg_confidence REAL,
  uploaded_by TEXT, uploaded_at TEXT NOT NULL, processed_at TEXT
);
CREATE TABLE IF NOT EXISTS document_pages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  page_no INTEGER NOT NULL, text TEXT, method TEXT, confidence REAL
);
CREATE TABLE IF NOT EXISTS extracted_fields (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  voyage_id INTEGER NOT NULL REFERENCES voyages(id) ON DELETE CASCADE,
  document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
  section TEXT NOT NULL,          -- vessel | cargo | crew | passenger | dg | store | effects | manual
  record_key TEXT NOT NULL,       -- header | bl:<n> | crew:<n> ...
  record_index INTEGER NOT NULL DEFAULT 0,
  field_key TEXT NOT NULL, field_label TEXT,
  original_value TEXT, value TEXT,
  page_no INTEGER, confidence REAL, method TEXT,
  status TEXT NOT NULL DEFAULT 'EXTRACTED',   -- EXTRACTED | EDITED | CONFIRMED
  confirmed_by TEXT, confirmed_at TEXT, updated_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_fields_voyage ON extracted_fields(voyage_id, section);
CREATE TABLE IF NOT EXISTS crosscheck_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  voyage_id INTEGER NOT NULL REFERENCES voyages(id) ON DELETE CASCADE,
  run_at TEXT NOT NULL, run_by TEXT, summary_json TEXT
);
CREATE TABLE IF NOT EXISTS crosscheck_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL REFERENCES crosscheck_runs(id) ON DELETE CASCADE,
  voyage_id INTEGER NOT NULL,
  group_name TEXT, check_key TEXT, field_key TEXT, record_key TEXT, status TEXT,
  doc1_id INTEGER, value1 TEXT, page1 INTEGER, field1_id INTEGER,
  doc2_id INTEGER, value2 TEXT, page2 INTEGER, field2_id INTEGER,
  message TEXT, suggestion TEXT, blocking INTEGER NOT NULL DEFAULT 0,
  acknowledged INTEGER NOT NULL DEFAULT 0, ack_note TEXT
);
CREATE TABLE IF NOT EXISTS crosscheck_acks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  voyage_id INTEGER NOT NULL REFERENCES voyages(id) ON DELETE CASCADE,
  check_key TEXT NOT NULL, value1 TEXT, value2 TEXT, note TEXT, user TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS review_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  voyage_id INTEGER NOT NULL REFERENCES voyages(id) ON DELETE CASCADE,
  field_id INTEGER, action TEXT NOT NULL, field_key TEXT,
  old_value TEXT, new_value TEXT, reason TEXT, user TEXT, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS export_options (
  voyage_id INTEGER NOT NULL REFERENCES voyages(id) ON DELETE CASCADE,
  key TEXT NOT NULL, value TEXT, PRIMARY KEY (voyage_id, key)
);
CREATE TABLE IF NOT EXISTS exports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  voyage_id INTEGER NOT NULL REFERENCES voyages(id) ON DELETE CASCADE,
  file_name TEXT NOT NULL, stored_name TEXT NOT NULL,
  created_by TEXT, created_at TEXT NOT NULL,
  override_used INTEGER NOT NULL DEFAULT 0, override_by TEXT, override_reason TEXT,
  report_json TEXT
);
"""


def local_now():
    """Current time in the company's time zone (servers such as Railway run in UTC)."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(os.environ.get("SGCL_TZ", "Asia/Ho_Chi_Minh"))).replace(tzinfo=None)


def now():
    return local_now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def tx():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def row(conn, sql, args=()):
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def hash_password(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"


def verify_password(pw: str, stored: str) -> bool:
    salt, _ = stored.split("$", 1)
    return secrets.compare_digest(hash_password(pw, salt), stored)


def init_db():
    global TEMPLATE_PATH
    TEMPLATE_PATH = active_template()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(EXPORT_DIR, exist_ok=True)
    with tx() as c:
        c.executescript(SCHEMA)
        # additive migrations for databases created by earlier versions
        for table, col, ddl in (("documents", "voyage_confirmed", "INTEGER NOT NULL DEFAULT 0"),
                                ("documents", "voyage_confirmed_by", "TEXT"),
                                ("extracted_fields", "data_type", "TEXT"),
                                ("extracted_fields", "unit", "TEXT"),
                                ("documents", "parent_id", "INTEGER"),          # child of a combined file that was split
                                ("documents", "pages_cache", "TEXT"),           # JSON pages of a child (no re-reading/OCR)
                                ("documents", "page_from", "INTEGER"),
                                ("documents", "page_to", "INTEGER"),
                                ("documents", "split_disabled", "INTEGER NOT NULL DEFAULT 0"),
                                ("voyages", "deleted_at", "TEXT"), ("voyages", "deleted_by", "TEXT"),       # in the trash (restorable)
                                ("voyages", "archived_at", "TEXT"), ("voyages", "archived_by", "TEXT"),
                                ("users", "active", "INTEGER NOT NULL DEFAULT 1")):    # archived (kept for viewing)
            if col not in [r[1] for r in c.execute(f"PRAGMA table_info({table})")]:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        if not c.execute("SELECT 1 FROM users").fetchone():
            # First start: passwords come from environment variables; otherwise random ones are
            # generated, printed in the server log and saved to <data>/initial_credentials.txt.
            creds = []
            for username, full_name, role, env in (("admin", "Quản trị viên (Supervisor)", "supervisor", "SGCL_ADMIN_PASSWORD"),
                                                   ("staff", "Nhân viên đại lý", "staff", "SGCL_STAFF_PASSWORD")):
                pw = os.environ.get(env) or secrets.token_urlsafe(9)
                c.execute("INSERT INTO users(username,full_name,password_hash,role,created_at) VALUES(?,?,?,?,?)",
                          (username, full_name, hash_password(pw), role, now()))
                creds.append((username, pw, env in os.environ))
            lines = [f"{u} / {p}" + ("" if from_env else "   (tự sinh)") for u, p, from_env in creds]
            if not all(x[2] for x in creds):
                path = os.path.join(DATA_DIR, "initial_credentials.txt")
                with open(path, "w", encoding="utf-8") as f:
                    f.write("Tài khoản khởi tạo SGCL - hãy đổi mật khẩu sau khi đăng nhập rồi xóa file này\n" + "\n".join(lines) + "\n")
                print("=" * 60 + "\nSGCL - TÀI KHOẢN KHỞI TẠO (đổi mật khẩu sau khi đăng nhập):\n" + "\n".join(lines) + "\n" + "=" * 60, flush=True)


def log(conn, voyage_id, action, user, field_id=None, field_key=None, old=None, new=None, reason=None):
    conn.execute(
        "INSERT INTO review_log(voyage_id,field_id,action,field_key,old_value,new_value,reason,user,at) VALUES(?,?,?,?,?,?,?,?,?)",
        (voyage_id, field_id, action, field_key, old, new, reason, user, now()))


def admin_log(conn, action, user, target=None, detail=None):
    conn.execute("INSERT INTO admin_log(action,target,detail,user,at) VALUES(?,?,?,?,?)", (action, target, detail, user, now()))


def dumps(o):
    return json.dumps(o, ensure_ascii=False)
