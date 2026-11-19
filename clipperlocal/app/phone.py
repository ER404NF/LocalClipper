"""'Send to phone': a tiny download server on the local Wi-Fi, reached by scanning a QR code.
Used for Instagram's Edits app (phone-only): download the clip, add music in Edits, post.
Only files explicitly shared get a random, expiring link; nothing else is exposed."""
import io
import secrets
import socket
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from . import config

_links: dict[str, tuple[Path, str, float]] = {}
TTL = 3 * 3600
_app = FastAPI()


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the Wi-Fi interface
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _qr_svg(data: str) -> str:
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


def share(path: Path, caption: str) -> dict:
    now = time.time()
    for k in [k for k, v in _links.items() if v[2] < now]:
        _links.pop(k, None)
    token = secrets.token_urlsafe(12)
    _links[token] = (path, caption, now + TTL)
    url = f"http://{lan_ip()}:{config.PHONE_PORT}/p/{token}"
    return {"url": url, "qr_svg": _qr_svg(url), "expires_in_min": TTL // 60}


def _get(token: str):
    v = _links.get(token)
    if not v or v[2] < time.time():
        raise HTTPException(404, "Link expired - make a new QR code in the app")
    return v


@_app.get("/p/{token}", response_class=HTMLResponse)
def page(token: str):
    path, caption, _ = _get(token)
    cap = (caption or "").replace("&", "&amp;").replace("<", "&lt;")
    return f"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>Clip</title><body style="font-family:system-ui;background:#0f1115;color:#eee;padding:16px">
<video src="/f/{token}" controls playsinline style="width:100%;border-radius:12px"></video>
<p><a href="/f/{token}" download="{path.name}" style="display:block;text-align:center;background:#ff2d78;color:#fff;padding:14px;border-radius:10px;text-decoration:none;font-weight:700">Download video</a></p>
<ol style="line-height:1.6"><li>Download, then Save Video / save to gallery</li>
<li>Open <b>Edits</b> → new project → pick the video</li>
<li>Add trending music (keep the clip's audio low/on as you like) → Share to Instagram</li>
<li>Paste the caption below</li></ol>
<textarea style="width:100%;height:140px;background:#161922;color:#eee;border-radius:8px;padding:8px">{cap}</textarea>
<button onclick="navigator.clipboard.writeText(document.querySelector('textarea').value);this.textContent='Copied'"
 style="width:100%;padding:12px;border-radius:10px;border:0;background:#262a36;color:#fff">Copy caption</button></body>"""


@_app.get("/f/{token}")
def file(token: str):
    path, _, _ = _get(token)
    return FileResponse(path, media_type="video/mp4", filename=path.name)


def start():
    import uvicorn

    def run():
        try:
            uvicorn.run(_app, host="0.0.0.0", port=config.PHONE_PORT, log_level="warning")
        except Exception as e:  # port busy / firewall: the rest of the app still works
            print("phone share server not started:", e)

    threading.Thread(target=run, daemon=True).start()
