"""YouTube Shorts upload via the official YouTube Data API v3.
First post per account opens a browser window to log in; the token is saved after that.
Note: unverified Google Cloud projects upload as private until Google audits the project."""
from pathlib import Path
from ..config import ROOT

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _creds(acct: dict):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token = ROOT / acct.get("token_file", f"secrets/youtube_{acct['name']}_token.json")
    secrets = ROOT / acct.get("client_secrets", "secrets/youtube_client.json")
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not secrets.exists():
            raise RuntimeError(f"Missing {secrets.name} - see README (YouTube setup)")
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
    token.parent.mkdir(exist_ok=True)
    token.write_text(creds.to_json())
    return creds


def upload(acct: dict, video: Path, title: str, description: str) -> str:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=_creds(acct), cache_discovery=False)
    if "#shorts" not in (title + description).lower():
        description = f"{description}\n#Shorts"
    body = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "categoryId": "20", "tags": ["gta6", "gta vi", "gaming"]},
        "status": {"privacyStatus": acct.get("privacy", "public"),
                   "selfDeclaredMadeForKids": False},
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(video), chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return f"https://youtube.com/shorts/{resp['id']}"
