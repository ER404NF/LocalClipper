"""The team's shared memory: a folder of Markdown notes (opens in Obsidian too).

Everyone can READ every note (hive mind). Each team only WRITES its own notes:
  shared     -> Agent (manager)
  production -> Clipper A / Clipper B
  coding     -> Planner / Coder / Designer
  learning   -> anyone (lessons learned, tagged with who learned it)
Links between notes are Obsidian-style [[wikilinks]]."""
import re
import threading
import time
from pathlib import Path

from . import config

TEAMS = ("shared", "production", "coding", "learning")
_lock = threading.Lock()
LINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "note"


def _path(team: str, slug: str) -> Path:
    return config.BRAIN_DIR / team / f"{slug}.md"


def _parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta, body = {}, text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            for line in text[3:end].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = text[end + 4:].lstrip("\n")
    team = meta.get("team") or path.parent.name
    return {"slug": path.stem, "title": meta.get("title", path.stem), "team": team, "type": meta.get("type", "note"),
            "by": meta.get("by", ""), "updated": meta.get("updated", ""), "pinned": meta.get("pinned") == "true",
            "body": body, "links": sorted({slugify(m) for m in LINK.findall(body)})}


def all_notes() -> list[dict]:
    seed()
    out = []
    for team in TEAMS:
        for p in sorted((config.BRAIN_DIR / team).glob("*.md")):
            try:
                out.append(_parse(p))
            except Exception:
                pass
    return out


def get(slug: str) -> dict | None:
    for team in TEAMS:
        p = _path(team, slug)
        if p.exists():
            return _parse(p)
    return None


def can_write(role_team: str, note_team: str) -> bool:
    return note_team == "learning" or role_team == note_team or (role_team == "manager" and note_team == "shared")


def write(title: str, body: str, team: str, by: str, role_team: str, type_: str = "note", pinned: bool = False) -> dict:
    """Creates or replaces a note. Raises PermissionError when a team writes outside its area."""
    if team not in TEAMS:
        raise ValueError(f"team must be one of {TEAMS}")
    if not can_write(role_team, team):
        raise PermissionError(f"{by} can read {team} notes but only that team can change them")
    slug = slugify(title)
    with _lock:
        for t in TEAMS:  # one note per slug
            other = _path(t, slug)
            if t != team and other.exists():
                raise PermissionError(f"a note called '{title}' already belongs to the {t} team")
        path = _path(team, slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M")
        path.write_text(f"---\ntitle: {title}\nteam: {team}\ntype: {type_}\nby: {by}\nupdated: {stamp}\n"
                        f"pinned: {'true' if pinned else 'false'}\n---\n{body.strip()}\n", encoding="utf-8")
    return _parse(path)


def append(title: str, line: str, team: str, by: str, role_team: str):
    note = get(slugify(title))
    body = (note["body"].rstrip() + "\n" if note else "") + f"- {line}"
    return write(title, body, team, by, role_team, note["type"] if note else "log")


def forget(slug: str):
    for team in TEAMS:
        p = _path(team, slug)
        if p.exists():
            p.unlink()


def pin(slug: str, pinned: bool = True):
    n = get(slug)
    if n:
        p = _path(n["team"], slug)
        text = p.read_text(encoding="utf-8")
        p.write_text(re.sub(r"pinned: (true|false)", f"pinned: {'true' if pinned else 'false'}", text, count=1), encoding="utf-8")


def search(query: str, k: int = 5, teams: tuple = TEAMS) -> list[dict]:
    words = [w for w in re.findall(r"[a-z0-9]{3,}", query.lower())]
    scored = []
    for n in all_notes():
        if n["team"] not in teams:
            continue
        hay = (n["title"] + " " + n["body"]).lower()
        s = sum(hay.count(w) for w in words) + (3 if n["pinned"] else 0)
        if s:
            scored.append((s, n))
    scored.sort(key=lambda x: -x[0])
    return [n for _, n in scored[:k]]


def context_for(query: str, k: int = 4) -> str:
    """Short brain extract placed in an agent's prompt."""
    notes = search(query, k)
    pinned = [n for n in all_notes() if n["pinned"] and n not in notes][:3]
    parts = [f"### {n['title']} ({n['team']})\n{n['body'][:600]}" for n in pinned + notes]
    return "\n\n".join(parts) or "(nothing relevant in the brain yet)"


def graph() -> dict:
    notes = all_notes()
    ids = {n["slug"] for n in notes}
    edges = [(n["slug"], l) for n in notes for l in n["links"] if l in ids and l != n["slug"]]
    degree = {}
    for a, b in edges:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    nodes = [{"id": n["slug"], "title": n["title"], "team": n["team"], "by": n["by"], "updated": n["updated"],
              "pinned": n["pinned"], "degree": degree.get(n["slug"], 0)} for n in notes]
    return {"nodes": nodes, "edges": [{"from": a, "to": b} for a, b in edges]}


def seed():
    """First run: a few starting notes so the brain isn't empty."""
    marker = config.BRAIN_DIR / ".seeded"
    if marker.exists():
        return
    marker.write_text("1")
    cfg = config.load()
    streamers = cfg.get("streamers") or []
    w = lambda *a, **k: write(*a, **k)
    w("Team rules", "How this team works.\n\n- One model, six agents. Each agent only does its own job.\n"
      "- Production: [[Formats]], [[Hooks that worked]], campaign notes.\n- Coding: [[App code map]], [[Past changes]].\n"
      "- Accounts and money are in the owner's name. See [[Accounts]].\n- Never post if the Italy box is offline.",
      "shared", "Agent", "manager", "rules", True)
    w("Accounts", "All accounts are owned by the owner in Italy; the manager (his brother) runs them.\n"
      "Every account tab and the phone go through the Italy box.\n\n" +
      "".join(f"- [[{s.get('name')} campaign]]\n" for s in streamers), "shared", "Agent", "manager", "accounts")
    for s in streamers:
        w(f"{s.get('name')} campaign", f"Campaign: {s.get('campaign', '')}\nCredit line: {s.get('credit', '')}\n"
          f"Pays on: {', '.join(s.get('allowed') or [])}\n\nSee [[Formats]] and [[Hooks that worked]].",
          "production", "Clipper A", "production", "campaign")
    w("Formats", "Layouts: blur, facecam, split-screen with our own filler, zoomed crop, reaction bubble.\n"
      "All exports 1080x1920. Keep text out of each app's button areas. See [[Hooks that worked]].",
      "production", "Clipper A", "production", "format")
    w("Hooks that worked", "Lessons from posted clips (the crew adds to this).", "learning", "Clipper B", "production", "learning")
    w("App code map", "- app/: Python engine (pipeline, crews, brain, browser, phone, autopilot)\n"
      "- desktop/ui/: the app's screens (HTML/CSS/JS)\n- desktop/src-tauri/: Rust shell (not changed by the crew)\n"
      "See [[Past changes]].", "coding", "Planner", "coding", "code")
    w("Past changes", "Changes the coding crew applied (newest last).", "coding", "Coder", "coding", "log")
