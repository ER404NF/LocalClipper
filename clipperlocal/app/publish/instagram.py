"""Instagram Reels via the official Instagram Graph API (professional accounts only).
Uses the resumable upload so the video can come straight from this computer."""
import time
from pathlib import Path
import requests


def upload(acct: dict, video: Path, caption: str) -> str:
    base = acct.get("graph_url", "https://graph.facebook.com/v21.0").rstrip("/")
    version = base.rsplit("/", 1)[-1]
    token, uid = acct["access_token"], acct["ig_user_id"]

    r = requests.post(f"{base}/{uid}/media", data={
        "media_type": "REELS", "upload_type": "resumable", "caption": caption[:2200],
        "share_to_feed": "true", "access_token": token}, timeout=60)
    r.raise_for_status()
    container = r.json()["id"]

    size = video.stat().st_size
    with open(video, "rb") as f:
        up = requests.post(
            f"https://rupload.facebook.com/ig-api-upload/{version}/{container}",
            headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
            data=f, timeout=600)
    up.raise_for_status()

    for _ in range(60):  # wait for Instagram to process the video (up to ~5 min)
        st = requests.get(f"{base}/{container}", params={
            "fields": "status_code,status", "access_token": token}, timeout=30).json()
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code == "ERROR":
            raise RuntimeError(f"Instagram processing error: {st.get('status')}")
        time.sleep(5)
    else:
        raise RuntimeError("Instagram processing timed out")

    pub = requests.post(f"{base}/{uid}/media_publish",
                        data={"creation_id": container, "access_token": token}, timeout=60)
    pub.raise_for_status()
    return f"published media id {pub.json().get('id')}"
