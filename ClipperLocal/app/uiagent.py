"""The 'hands' of the crew: picks the next action on a screen (browser tab or phone) from a numbered list
of what's on it. Used by browser_ctl.py and android.py."""
import json

from . import team

SYSTEM = """You are {who} from the ClipperLocal production crew, operating {place} that is already signed in.
You see the screen as a numbered list of elements plus some visible text. Pick ONE next action.

Reply with JSON only:
{{"thought": "short reason", "action": "click|type|upload|press|scroll|wait|goto|done|fail|ask",
  "id": <element number for click/type/upload>, "text": "<text to type>", "key": "<key for press, e.g. Enter>",
  "url": "<for goto>", "file": <index of the file to upload, default 0>, "result": "<for done/fail/ask: what happened or the question>"}}

Rules:
- Work toward the goal directly. Don't scroll around or open unrelated pages. Scroll only to reach something you need.
- To put a video file into the page or app, use action "upload" on the file input or the drop area. Never browse the computer's files.
- Never change account settings, passwords, follow/unfollow, like, comment or send messages.
- If something needs a human (login, captcha, verification code, payment, a warning you don't understand), use "ask".
- Use "done" only when the screen clearly shows the goal is complete, and report numbers exactly as shown.
- If the same action failed twice, try a different element or "ask"."""


def decide(who: str, place: str, goal: str, hints: str, elements: list[dict], text: str, history: list[str],
           files: list[str], screenshot_b64: str | None = None) -> dict:
    lines = []
    for e in elements[:160]:
        bits = [f"[{e['id']}] {e.get('kind', e.get('tag', ''))}"]
        if e.get("label"):
            bits.append(json.dumps(e["label"][:80]))
        for k in ("type", "value", "state"):
            if e.get(k):
                bits.append(f"{k}={str(e[k])[:40]}")
        lines.append(" ".join(bits))
    user = (f"GOAL: {goal}\n\nHOW IT USUALLY GOES:\n{hints or '(no hints)'}\n\n"
            f"FILES YOU CAN UPLOAD: {json.dumps([f.split('/')[-1].split(chr(92))[-1] for f in files]) if files else 'none'}\n\n"
            f"WHAT YOU DID SO FAR:\n" + ("\n".join(history[-12:]) or "(nothing yet)") +
            f"\n\nSCREEN ELEMENTS:\n" + "\n".join(lines) + f"\n\nVISIBLE TEXT:\n{text[:2500]}")
    act = team.ask_json(SYSTEM.format(who=who, place=place), user, images=[screenshot_b64] if screenshot_b64 else None)
    act.setdefault("action", "fail")
    return act
