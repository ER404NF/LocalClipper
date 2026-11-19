"""SQLite store: sources, clips, channels, chats, crew rooms, plans, reports, activity logs."""
import json
import sqlite3
import threading
import time
from .config import DATA

_lock = threading.RLock()
_conn = sqlite3.connect(DATA / "clipper.db", check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript(
    """
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT, kind TEXT, streamer TEXT, title TEXT,
  options TEXT DEFAULT '{}',
  status TEXT DEFAULT 'queued', message TEXT DEFAULT '',
  path TEXT, created_at REAL, crew TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS clips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER, start REAL, end REAL, score REAL,
  hook TEXT, title TEXT, description TEXT, reason TEXT,
  status TEXT DEFAULT 'candidate', render_path TEXT,
  posts TEXT DEFAULT '{}', is_compilation INTEGER DEFAULT 0,
  created_at REAL, found_by TEXT DEFAULT '', review TEXT DEFAULT '{}',
  layout TEXT DEFAULT '', variants TEXT DEFAULT '{}', editor TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS channels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT, name TEXT, method TEXT DEFAULT 'browser',
  creds TEXT DEFAULT '{}', created_at REAL, proxy TEXT DEFAULT 'italy',
  UNIQUE(platform, name)
);
CREATE TABLE IF NOT EXISTS chat (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  room TEXT DEFAULT 'agent', role TEXT, author TEXT DEFAULT '',
  content TEXT, data TEXT DEFAULT '{}', created_at REAL
);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT, payload TEXT, summary TEXT,
  status TEXT DEFAULT 'pending', result TEXT DEFAULT '', created_at REAL
);
CREATE TABLE IF NOT EXISTS plan_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT, at TEXT, channel TEXT, clip_id INTEGER, method TEXT, crew TEXT,
  status TEXT DEFAULT 'draft', message TEXT DEFAULT '', link TEXT DEFAULT '', updated_at REAL
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  target TEXT DEFAULT '', text TEXT, status TEXT DEFAULT 'open', result TEXT DEFAULT '', created_at REAL
);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  place TEXT, who TEXT, task TEXT, step TEXT, state TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS reports (
  day TEXT PRIMARY KEY, data TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS trends (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT, title TEXT, body TEXT, sources TEXT DEFAULT '[]', status TEXT DEFAULT 'new', created_at REAL
);
CREATE TABLE IF NOT EXISTS campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT, streamer TEXT, rate REAL DEFAULT 0, views INTEGER DEFAULT 0,
  earned REAL DEFAULT 0, status TEXT DEFAULT 'active', updated_at REAL
);
CREATE TABLE IF NOT EXISTS stats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT, metric TEXT, value REAL, goal REAL, created_at REAL
);
CREATE TABLE IF NOT EXISTS changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request TEXT, status TEXT DEFAULT 'planning', branch TEXT DEFAULT '', plan TEXT DEFAULT '{}',
  concepts TEXT DEFAULT '[]', chosen TEXT DEFAULT '', checks TEXT DEFAULT '[]', files TEXT DEFAULT '[]',
  commit_sha TEXT DEFAULT '', created_at REAL
);
"""
)


def _migrate():
    """Adds columns that older databases don't have yet."""
    want = {
        "sources": {"crew": "TEXT DEFAULT ''"},
        "clips": {"found_by": "TEXT DEFAULT ''", "review": "TEXT DEFAULT '{}'", "layout": "TEXT DEFAULT ''",
                  "variants": "TEXT DEFAULT '{}'", "editor": "TEXT DEFAULT ''"},
        "channels": {"proxy": "TEXT DEFAULT 'italy'"},
        "chat": {"room": "TEXT DEFAULT 'agent'", "author": "TEXT DEFAULT ''"},
    }
    for table, cols in want.items():
        have = {r[1] for r in _conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for col, decl in cols.items():
            if col not in have:
                _conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    _conn.commit()


_migrate()


def q(sql: str, args=()):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        return cur


def rows(sql: str, args=()) -> list[dict]:
    with _lock:
        return [dict(r) for r in _conn.execute(sql, args).fetchall()]


def one(sql: str, args=()) -> dict | None:
    r = rows(sql, args)
    return r[0] if r else None


def _set(table, rid, kw, key="id"):
    if not kw:
        return
    sets = ",".join(f"{k}=?" for k in kw)
    q(f"UPDATE {table} SET {sets} WHERE {key}=?", (*kw.values(), rid))


def add_source(url, kind, streamer, title, options, crew="") -> int:
    return q("INSERT INTO sources(url,kind,streamer,title,options,created_at,crew) VALUES(?,?,?,?,?,?,?)",
             (url, kind, streamer, title, json.dumps(options or {}), time.time(), crew)).lastrowid


def set_source(sid, **kw):
    _set("sources", sid, kw)


def add_clip(**kw) -> int:
    kw.setdefault("created_at", time.time())
    cols = ",".join(kw)
    return q(f"INSERT INTO clips({cols}) VALUES({','.join('?' * len(kw))})", tuple(kw.values())).lastrowid


def set_clip(cid, **kw):
    _set("clips", cid, kw)


def set_channel(cid, **kw):
    _set("channels", cid, kw)


def add_chat(role: str, content: str, data: dict | None = None, room: str = "agent", author: str = "") -> int:
    return q("INSERT INTO chat(room,role,author,content,data,created_at) VALUES(?,?,?,?,?,?)",
             (room, role, author, content or "", json.dumps(data or {}), time.time())).lastrowid


def log(place: str, who: str, task: str, step: str, state: str = "done") -> int:
    """Activity line shown in the Browser / Phone / Autopilot pages."""
    return q("INSERT INTO activity(place,who,task,step,state,created_at) VALUES(?,?,?,?,?,?)",
             (place, who, task, step, state, time.time())).lastrowid
