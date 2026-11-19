"""One local model, six agents. Each agent = the same model + its own job, tools and brain rights.

Rooms (chat threads in the app):
  agent       -> the Agent (manager) talks with the operator
  production  -> Clipper A + Clipper B + operator
  coding      -> Planner + Coder + Designer + operator
Job boundaries are enforced twice: the prompt tells each agent its job, and the tool layer
refuses any tool outside that agent's job."""
import json
import re
import threading
from datetime import datetime

import requests

from . import brain, config, db

ROLES = {
    "agent": {"name": "Agent", "team": "manager", "room": "agent",
              "job": "Talk with the operator, answer questions about the whole operation, and hand work to the right crew.",
              "refuses": "Clipping, editing, posting (production crew) and changing the app (coding crew)."},
    "clipper_a": {"name": "Clipper A", "team": "production", "room": "production",
                  "job": "Hunt GTA 6 streams, pick and clip moments, review Clipper B's clips, edit clips for each platform, "
                         "research trends, and post/schedule in the account tabs and on the phone.",
                  "refuses": "Changing the app's code or design (that's the coding crew)."},
    "clipper_b": {"name": "Clipper B", "team": "production", "room": "production",
                  "job": "Same job as Clipper A, working in parallel, and review Clipper A's clips.",
                  "refuses": "Changing the app's code or design (that's the coding crew)."},
    "planner": {"name": "Planner", "team": "coding", "room": "coding",
                "job": "Turn the operator's app change requests into a clear plan, coordinate Designer and Coder, recommend options.",
                "refuses": "Clipping, editing, posting, or managing accounts (that's the production crew)."},
    "coder": {"name": "Coder", "team": "coding", "room": "coding",
              "job": "Answer questions about how the app works by reading its code (with file:line facts), and write and "
                     "test changes to the app's Python engine and screens on a safe copy.",
              "refuses": "Clipping, editing, posting, or design decisions without the Designer."},
    "designer": {"name": "Designer", "team": "coding", "room": "coding",
                 "job": "Make screen mockups and concepts for app changes and check the result matches the app's style.",
                 "refuses": "Writing code, clipping, editing or posting."},
}
BY_NAME = {r["name"].lower(): k for k, r in ROLES.items()}
TEAM_OF_ROOM = {"agent": ["agent"], "production": ["clipper_a", "clipper_b"], "coding": ["planner", "coder", "designer"]}
_room_locks = {room: threading.Lock() for room in TEAM_OF_ROOM}

SYSTEM = """You are {name}, one agent in the ClipperLocal team (a GTA 6 stream-clipping business run from a desktop app).
The whole team is ONE local AI model playing six agents: Agent (manager), Clipper A and Clipper B (production crew),
Planner, Coder and Designer (coding crew). You share one brain (memory notes) with everyone, but you only do YOUR job.

Your job: {job}
Not your job: {refuses}
If the operator asks you for something that isn't your job, say plainly that it isn't your job, name who does it, and
use the handoff tool so they get the request. Never pretend to do another agent's job.

Rules:
- Never invent facts, numbers, clips, posts or results. Only report what tools returned. If unsure, say so or check.
- Ask one short question when a request is unclear instead of guessing.
- Keep messages short and practical, like a teammate in a group chat. Answer in the operator's language.
- When you learn something useful for the future, save it with brain_learn.
- The operator is the manager. Accounts and money belong to the owner (his older brother) in Italy.

{extra_rules}
Now: {now}
From the brain:
{brain}"""


CODE_FACTS = """
Questions about the app ("can the production crew do X?", "where is Y?", "how does Z work?"):
- You can read the app's real code. ALWAYS check it with app_overview, search_code and read_file BEFORE answering.
- Answer only with what the code shows, and name the file and line, e.g. (app/crew.py:42). If the code doesn't show it,
  say "the app can't do that yet" and offer to build it with start_change. Never guess how the app works.
- To change the app, use start_change: it plans, shows concepts, builds on a safe copy and waits for Apply."""

QUESTION = re.compile(r"\?\s*$|^(what|how|why|where|which|who|when|can|could|does|do|is|are|will|would|should|explain|tell me|show me)\b",
                      re.I)


def is_question(text: str) -> bool:
    return bool(QUESTION.search((text or "").strip()))


def _history(room: str, me: str, limit: int = 30) -> list[dict]:
    rows = db.rows("SELECT * FROM (SELECT * FROM chat WHERE room=? ORDER BY id DESC LIMIT ?) ORDER BY id", (room, limit))
    msgs = []
    for r in rows:
        data = json.loads(r["data"] or "{}")
        author = r["author"] or ""
        if r["role"] == "user":
            msgs.append({"role": "user", "content": r["content"]})
        elif r["role"] == "assistant":
            if author == ROLES[me]["name"] or (not author and room == "agent"):
                m = {"role": "assistant", "content": r["content"]}
                if data.get("tool_calls"):
                    m["tool_calls"] = data["tool_calls"]
                msgs.append(m)
            elif r["content"]:  # a teammate speaking: shown as context, not as "me"
                msgs.append({"role": "user", "content": f"[{author}]: {r['content']}"})
        elif r["role"] == "tool" and author == ROLES[me]["name"]:
            cap = 16000 if ROLES[me]["team"] == "coding" else 4000
            msgs.append({"role": "tool", "content": r["content"][:cap], "tool_name": data.get("name", "")})
        elif r["role"] == "event":
            msgs.append({"role": "user", "content": f"[app] {r['content']}"})
    while msgs and msgs[0]["role"] == "tool":
        msgs.pop(0)
    return msgs


def model_for(role: str | None, cfg: dict | None = None) -> tuple[str, int]:
    """Production crew + Agent use the team model; the coding crew uses the coding model (if one is set)."""
    t = (cfg or config.load())["team"]
    if role and ROLES.get(role, {}).get("team") == "coding" and t.get("coding_model"):
        return t["coding_model"], int(t.get("coding_ctx") or 32768)
    return t["model"], int(t.get("ctx") or 12288)


def call_model(messages: list, tools: list | None = None, json_mode: bool = False, temperature: float = 0.3,
               images: list | None = None, role: str | None = None) -> dict:
    cfg = config.load()
    url = (cfg.get("llm") or {}).get("ollama_url", "http://127.0.0.1:11434")
    model, ctx = model_for(role, cfg)
    body = {"model": model, "messages": messages, "stream": False, "think": False, "keep_alive": "10m",
            "options": {"temperature": temperature, "num_ctx": ctx}}
    if tools:
        body["tools"] = [{"type": "function", "function": t} for t in tools]
    if json_mode:
        body["format"] = "json"
    if images:
        body["messages"] = messages[:-1] + [{**messages[-1], "images": images}]
    r = requests.post(f"{url}/api/chat", json=body, timeout=900)
    if r.status_code == 400 and "think" in r.text:
        body.pop("think")
        r = requests.post(f"{url}/api/chat", json=body, timeout=900)
    if r.status_code == 404 and "not found" in r.text:
        raise RuntimeError(f"The AI model '{model}' isn't downloaded yet. Open Models and press Download.")
    if r.status_code >= 400:
        raise RuntimeError(f"Ollama error {r.status_code}: {r.text[:300]}")
    m = r.json()["message"]
    m["content"] = re.sub(r"<think>.*?</think>", "", m.get("content") or "", flags=re.S).strip()
    return m


def ask_json(system: str, user: str, images: list | None = None, role: str | None = None) -> dict:
    m = call_model([{"role": "system", "content": system}, {"role": "user", "content": user}], json_mode=True,
                   temperature=0.4, images=images, role=role)
    text = m["content"]
    found = re.search(r"\{.*\}", text, flags=re.S)
    return json.loads(found.group(0) if found else text)


def run(role: str, user_text: str | None = None, room: str | None = None, max_steps: int = 8) -> None:
    """One turn for one agent: reads the room, may call tools, posts its answer in the room."""
    from . import tools  # late import: tools import crews which import team
    r = ROLES[role]
    room = room or r["room"]
    if user_text is not None:
        db.add_chat("user", user_text, room=room)
    schemas = tools.schemas_for(role)
    checked_code, nudged = False, False
    last_user = (db.one("SELECT content FROM chat WHERE room=? AND role='user' ORDER BY id DESC LIMIT 1", (room,)) or {})
    asks_question = r["team"] == "coding" and is_question(last_user.get("content", ""))
    for _ in range(max_steps):
        query = user_text or (db.one("SELECT content FROM chat WHERE room=? ORDER BY id DESC LIMIT 1", (room,)) or {}).get("content", "")
        sys = SYSTEM.format(name=r["name"], job=r["job"], refuses=r["refuses"],
                            extra_rules=CODE_FACTS if r["team"] == "coding" else "",
                            now=datetime.now().strftime("%Y-%m-%d %H:%M"), brain=brain.context_for(query or r["job"]))
        extra = tools.context_for(role)
        msgs = [{"role": "system", "content": sys + ("\n\nCurrent state:\n" + extra if extra else "")}] + _history(room, role)
        try:
            if asks_question and not checked_code and nudged:
                msgs.append({"role": "user", "content": "[app] You haven't looked at the code yet. Call app_overview or "
                                                        "search_code first, then answer with file:line references."})
            m = call_model(msgs, schemas, role=role)
        except requests.ConnectionError:
            db.add_chat("assistant", "I can't reach the local AI. Open the Ollama app and try again.", {"error": True},
                        room=room, author=r["name"])
            return
        except Exception as e:
            db.add_chat("assistant", f"AI error: {e}", {"error": True}, room=room, author=r["name"])
            return
        calls = m.get("tool_calls") or []
        if not calls and asks_question and not checked_code and not nudged:
            nudged = True  # one retry: make it read the code instead of answering from memory
            continue
        if not calls:
            db.add_chat("assistant", m["content"] or "(no answer)", room=room, author=r["name"])
            return
        db.add_chat("assistant", m["content"], {"tool_calls": calls}, room=room, author=r["name"])
        for tc in calls:
            fn = tc.get("function", {})
            name, args = fn.get("name", ""), fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if name in ("app_overview", "search_code", "read_file", "list_files"):
                checked_code = True
            result, extra_data = tools.run(role, name, dict(args))
            db.add_chat("tool", json.dumps(result, default=str), {"name": name, "args": args, **extra_data},
                        room=room, author=r["name"])
    db.add_chat("assistant", "I stopped after several steps. Tell me what to do next.", room=room, author=r["name"])


def pick_responder(room: str, text: str) -> str:
    """Who answers a message in a crew room: @mentions win, otherwise the lead."""
    low = text.lower()
    for k in TEAM_OF_ROOM[room]:
        n = ROLES[k]["name"].lower()
        short = n.split()[-1]
        if f"@{n.replace(' ', '')}" in low.replace(" ", "") or f"@{short}" in low:
            return k
    if room == "coding" and is_question(text):
        return "coder"
    return TEAM_OF_ROOM[room][0]


def say(room: str, text: str) -> int:
    """Operator message in a room; the right agent answers (in a background thread)."""
    first = db.add_chat("user", text, room=room)
    role = pick_responder(room, text)

    def go():
        with _room_locks[room]:
            run(role, None, room=room)
    threading.Thread(target=go, daemon=True).start()
    return first


def post(role: str, text: str, data: dict | None = None, room: str | None = None) -> int:
    """An agent posting without a model call (workflow updates, cards)."""
    return db.add_chat("assistant", text, data or {}, room=room or ROLES[role]["room"], author=ROLES[role]["name"])
