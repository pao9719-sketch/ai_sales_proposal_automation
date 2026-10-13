"""SQLite 저장소 (단일 PC 운영 가정)."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "sales.db"

STATUSES = ["작성중", "검토요청", "승인", "반려"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  customer TEXT NOT NULL,
  contact TEXT DEFAULT '',
  gas TEXT DEFAULT '',
  annual_volume REAL DEFAULT 0,
  unit TEXT DEFAULT 'Nm3',
  supply_price REAL DEFAULT 0,
  unit_cost REAL DEFAULT 0,
  annual_opex REAL DEFAULT 0,
  contract_years INTEGER DEFAULT 5,
  site_note TEXT DEFAULT '',
  status TEXT DEFAULT '작성중',
  approved_snapshot TEXT,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL,
  category TEXT, name TEXT, qty REAL, unit_price REAL, source TEXT DEFAULT '수동'
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER, ts TEXT, actor TEXT, action TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER, kind TEXT, filename TEXT, path TEXT, uploaded_at TEXT
);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def conn():
    DATA_DIR.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        c.executescript(SCHEMA)
        yield c
        c.commit()
    finally:
        c.close()


def log(c, project_id: int, actor: str, action: str, detail: str = ""):
    c.execute("INSERT INTO audit(project_id, ts, actor, action, detail) VALUES (?,?,?,?,?)",
              (project_id, _now(), actor, action, detail))


def create_project(name: str, customer: str, actor: str, **fields) -> int:
    with conn() as c:
        cols = ["name", "customer", "created_at", "updated_at"] + list(fields)
        vals = [name, customer, _now(), _now()] + list(fields.values())
        cur = c.execute(f"INSERT INTO projects({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
        log(c, cur.lastrowid, actor, "생성", f"{name} / {customer}")
        return cur.lastrowid


def list_projects() -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM projects ORDER BY updated_at DESC")]


def get_project(pid: int) -> dict | None:
    with conn() as c:
        r = c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return dict(r) if r else None


_EDITABLE = {"name", "customer", "contact", "gas", "annual_volume", "unit", "supply_price",
             "unit_cost", "annual_opex", "contract_years", "site_note"}


def update_project(pid: int, actor: str, **fields):
    fields = {k: v for k, v in fields.items() if k in _EDITABLE}
    with conn() as c:
        old = dict(c.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
        changed = {k: (old[k], v) for k, v in fields.items() if old[k] != v}
        if not changed:
            return
        sets = ", ".join(f"{k}=?" for k in changed) + ", updated_at=?"
        c.execute(f"UPDATE projects SET {sets} WHERE id=?",
                  [v for _, v in changed.values()] + [_now(), pid])
        log(c, pid, actor, "수정", "; ".join(f"{k}: {a}→{b}" for k, (a, b) in changed.items()))


def get_items(pid: int) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT category, name, qty, unit_price, source FROM items WHERE project_id=? ORDER BY id", (pid,))]


def save_items(pid: int, actor: str, items: list[dict]):
    with conn() as c:
        c.execute("DELETE FROM items WHERE project_id=?", (pid,))
        c.executemany(
            "INSERT INTO items(project_id, category, name, qty, unit_price, source) VALUES (?,?,?,?,?,?)",
            [(pid, i.get("category"), i.get("name"), i.get("qty") or 0, i.get("unit_price") or 0,
              i.get("source") or "수동") for i in items])
        c.execute("UPDATE projects SET updated_at=? WHERE id=?", (_now(), pid))
        log(c, pid, actor, "투자비 항목 저장", f"{len(items)}개 항목")


def set_status(pid: int, actor: str, status: str, detail: str = "", snapshot: dict | None = None):
    assert status in STATUSES
    with conn() as c:
        if status == "승인":
            snap = json.dumps(snapshot, ensure_ascii=False) if snapshot is not None else None
            c.execute("UPDATE projects SET status=?, approved_snapshot=?, updated_at=? WHERE id=?",
                      (status, snap, _now(), pid))
        else:
            c.execute("UPDATE projects SET status=?, approved_snapshot=NULL, updated_at=? WHERE id=?",
                      (status, _now(), pid))
        log(c, pid, actor, f"상태변경 → {status}", detail)


def get_audit(pid: int) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT ts, actor, action, detail FROM audit WHERE project_id=? ORDER BY id DESC", (pid,))]


def add_file(pid: int, kind: str, filename: str, path: str, actor: str):
    with conn() as c:
        c.execute("INSERT INTO files(project_id, kind, filename, path, uploaded_at) VALUES (?,?,?,?,?)",
                  (pid, kind, filename, path, _now()))
        log(c, pid, actor, "자료 업로드", f"{kind}: {filename}")


def get_files(pid: int) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT kind, filename, path, uploaded_at FROM files WHERE project_id=? ORDER BY id DESC", (pid,))]
