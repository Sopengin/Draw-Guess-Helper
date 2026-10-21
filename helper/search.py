"""Pluggable image-search providers.

Each provider implements ``search(query, n) -> list[str]`` returning image
URLs. The query is already a "clipart / line drawing" flavoured string built
by the caller.

``make_provider`` returns a free scraper when no API key is configured, and an
official API provider otherwise — so the helper works out of the box with no
registration.
"""
from __future__ import annotations

import html
import json
import re
import requests


class SearchError(Exception):
    pass


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class BingImageScraper:
    """Free Bing image search via HTML scraping (no API key).

    Bing embeds each image result's media URL in an ``m="..."`` attribute
    (HTML-escaped JSON) on the result anchor. We extract those.
    """

    name = "bing_scrape"

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    def search(self, query: str, n: int = 6) -> list[str]:
        resp = requests.get(
            "https://www.bing.com/images/search",
            params={"q": query, "form": "HDRSC2", "first": 1},
            headers=HEADERS,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        urls = self._extract(resp.text)
        return urls[: max(1, n)]

    @staticmethod
    def _extract(page: str) -> list[str]:
        urls = []
        seen = set()
        for raw in re.findall(r'm="([^"]+)"', page):
            try:
                obj = json.loads(html.unescape(raw))
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            murl = obj.get("murl") or obj.get("turl")
            if isinstance(murl, str) and murl.startswith("http") and murl not in seen:
                seen.add(murl)
                urls.append(murl)
        return urls


class GoogleCustomSearch:
    """Google Custom Search JSON API (requires api_key + cx)."""

    name = "google"

    def __init__(self, api_key: str, cx: str, timeout: float = 10.0):
        self.api_key = api_key
        self.cx = cx
        self.timeout = timeout

    def search(self, query: str, n: int = 5) -> list[str]:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": self.api_key,
                "cx": self.cx,
                "q": query,
                "searchType": "image",
                "num": min(n, 10),
                "safe": "active",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        urls = [it.get("link") for it in items if it.get("link")]
        return [u for u in urls if u]


class BingImageSearch:
    """Bing Image Search API (requires api_key)."""

    name = "bing"

    def __init__(self, api_key: str, timeout: float = 10.0):
        self.api_key = api_key
        self.timeout = timeout

    def search(self, query: str, n: int = 5) -> list[str]:
        resp = requests.get(
            "https://api.bing.microsoft.com/v7.0/images/search",
            params={"q": query, "count": min(n, 50)},
            headers={"Ocp-Apim-Subscription-Key": self.api_key},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        values = resp.json().get("value", [])
        urls = [it.get("contentUrl") for it in values if it.get("contentUrl")]
        return [u for u in urls if u]


def make_provider(config: dict):
    """Return a provider; falls back to free scraping when no key is set."""
    search_cfg = config.get("search") or {}
    provider = search_cfg.get("provider", "").lower()
    api_key = search_cfg.get("api_key", "").strip()
    cx = search_cfg.get("cx", "").strip()

    if api_key:
        if provider == "google":
            return GoogleCustomSearch(api_key, cx)
        if provider == "bing":
            return BingImageSearch(api_key)
        # A key is present but provider unknown -> assume Bing.
        return BingImageSearch(api_key)

    return BingImageScraper()
