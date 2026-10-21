"""Optional Chinese -> English translation for image-search queries.

By default translation is DISABLED (Chinese 简笔画 search already works well).
When enabled, we try Google's public gtx endpoint first, fall back to MyMemory,
and reject translations that are obviously wrong (English function words such
as "to"/"a"/"the", or any result still containing CJK).
"""
from __future__ import annotations

import re
import requests

# English function words that are almost never a valid drawing subject.
_STOPWORDS = {
    "a", "an", "the", "to", "of", "in", "on", "at", "by", "for", "with", "from",
    "is", "are", "was", "were", "be", "been", "being", "and", "or", "but", "so",
    "it", "he", "she", "they", "we", "you", "i", "me", "my", "this", "that",
    "there", "here", "what", "who", "which", "do", "does", "did", "have", "has",
    "had", "will", "would", "can", "could", "should", "not", "no", "yes",
}


def _is_good(original: str, translated: str) -> bool:
    t = translated.strip().lower()
    if not t:
        return False
    if t == original.strip().lower():
        return False
    if re.search(r"[一-鿿]", t):  # still contains Chinese -> failed
        return False
    # a single English function word is almost certainly a bad translation
    if len(t.split()) == 1 and t in _STOPWORDS:
        return False
    return True


def _google_gtx(text: str, timeout: float = 5.0) -> str:
    r = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "zh-CN", "tl": "en", "dt": "t", "q": text},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    parts = [seg[0] for seg in data[0] if seg and seg[0]]
    return "".join(parts).strip()


def _mymemory(text: str, timeout: float = 5.0) -> str:
    r = requests.get(
        "https://api.mymemory.translated.net/get",
        params={"q": text, "langpair": "zh-CN|en"},
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    return (data.get("responseData") or {}).get("translatedText") or ""


def translate_zh_to_en(text: str) -> str:
    """Translate Chinese -> English; return the input unchanged on failure/garbage."""
    text = text.strip()
    if not text:
        return text
    if not any("一" <= ch <= "鿿" for ch in text):
        return text

    for fn in (_google_gtx, _mymemory):
        try:
            translated = fn(text)
            if _is_good(text, translated):
                return translated
        except Exception:
            continue
    return text
