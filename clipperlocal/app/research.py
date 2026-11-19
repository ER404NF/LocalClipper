"""Web research for the crew: search (DuckDuckGo via ddgs, or Brave with a key) and page reading."""
import requests

from . import config


def search(query: str, n: int = 8) -> list[dict]:
    cfg = config.load()
    r = cfg.get("research") or {}
    if r.get("provider") == "brave" and r.get("brave_key"):
        res = requests.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": n},
                           headers={"X-Subscription-Token": r["brave_key"], "Accept": "application/json"}, timeout=20)
        res.raise_for_status()
        return [{"title": x.get("title"), "url": x.get("url"), "snippet": x.get("description", "")}
                for x in res.json().get("web", {}).get("results", [])[:n]]
    from ddgs import DDGS
    with DDGS() as d:
        return [{"title": x.get("title"), "url": x.get("href"), "snippet": x.get("body", "")} for x in d.text(query, max_results=n)]


def read(url: str, limit: int = 6000) -> str:
    import trafilatura
    html = requests.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0 ClipperLocal research"}).text
    text = trafilatura.extract(html) or ""
    return text[:limit] or "(no readable text on this page)"
