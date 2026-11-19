"""TikTok via the official Content Posting API.
mode "inbox": video lands in the TikTok app's inbox/drafts -> add a trending sound and post (recommended).
mode "direct": posts directly. Until TikTok audits your developer app, only SELF_ONLY privacy works."""
import math
from pathlib import Path
import requests

API = "https://open.tiktokapis.com/v2/post/publish"
CHUNK = 10 * 1024 * 1024


def upload(acct: dict, video: Path, caption: str) -> str:
    size = video.stat().st_size
    if size <= 64 * 1024 * 1024:
        chunk, count = size, 1
    else:
        chunk, count = CHUNK, math.floor(size / CHUNK)  # last chunk absorbs the remainder
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk,
              "total_chunk_count": count}
    headers = {"Authorization": f"Bearer {acct['access_token']}",
               "Content-Type": "application/json; charset=UTF-8"}

    if acct.get("mode", "inbox") == "direct":
        body = {"post_info": {"title": caption[:2200],
                              "privacy_level": acct.get("privacy_level", "SELF_ONLY"),
                              "disable_comment": False, "disable_duet": False,
                              "disable_stitch": False},
                "source_info": source}
        url = f"{API}/video/init/"
    else:
        body, url = {"source_info": source}, f"{API}/inbox/video/init/"

    r = requests.post(url, headers=headers, json=body, timeout=60)
    j = r.json()
    if j.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok: {j['error']}")
    upload_url, publish_id = j["data"]["upload_url"], j["data"]["publish_id"]

    with open(video, "rb") as f:
        for i in range(count):
            start = i * chunk
            end = size - 1 if i == count - 1 else start + chunk - 1
            f.seek(start)
            data = f.read(end - start + 1)
            put = requests.put(upload_url, data=data, timeout=600, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(data)),
                "Content-Range": f"bytes {start}-{end}/{size}"})
            if put.status_code not in (200, 201, 206):
                raise RuntimeError(f"TikTok upload failed: {put.status_code} {put.text[:200]}")

    where = "TikTok inbox (open the app to finish posting)" if acct.get("mode", "inbox") != "direct" else "TikTok"
    return f"sent to {where}, publish_id {publish_id}"
