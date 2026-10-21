"""Draw & Guess assistant — helper side.

Watches ``<runtime_dir>/word.txt`` for a new word written by the injected
plugin, searches for clipart / line drawings of it, then:

* with preview enabled (default): saves candidate images as PNG + writes
  ``candidates.json`` for the in-game plugin UI; when the player picks one the
  plugin writes ``choice.txt`` and we convert that image to ``strokes.json``;
* with preview disabled (``--no-preview``): auto-draws the first result.

Run:  python helper/main.py --config config.json
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from PIL import Image

import search
import translate
from image_to_strokes import image_bytes_to_strokes

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def query_variants(word: str, en: str) -> list[str]:
    """Produce a list of search queries, best (cleanest line art) first."""
    variants = []
    if en and en != word:
        variants += [f"{en} clipart", f"{en} line drawing", f"{en} black and white"]
        if any("一" <= c <= "鿿" for c in word):
            variants += [f"{word} {en}"]
        variants.append(en)
    if any("一" <= c <= "鿿" for c in word):
        variants += [f"{word} 简笔画", f"{word} 线稿", f"{word} 白描"]
    variants.append(word)
    seen = set()
    out = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def download(url: str, timeout: float = 10.0) -> bytes | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        if r.content and len(r.content) > 500:
            return r.content
    except Exception:
        pass
    return None


def find_images(provider, word: str, en: str, n: int) -> list[tuple[str, bytes]]:
    """Return up to ``n`` (query, image_bytes) candidates, downloaded in parallel."""
    candidates: list[tuple[str, str]] = []
    seen = set()
    for query in query_variants(word, en):
        try:
            urls = provider.search(query, n=n)
        except Exception as e:
            print(f"[search] query '{query}' failed: {e}", flush=True)
            continue
        for u in urls:
            if u not in seen:
                seen.add(u)
                candidates.append((query, u))

    results: list[tuple[str, bytes]] = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        fut = {ex.submit(download, u): (q, u) for q, u in candidates}
        for f in as_completed(fut):
            data = f.result()
            if data:
                q, _ = fut[f]
                results.append((q, data))
                if len(results) >= n:
                    break
    return results


def to_png(img_bytes: bytes) -> bytes:
    """Re-encode an image to PNG so Unity's ImageConversion can load it."""
    im = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def write_strokes(runtime_dir: str, word: str, query: str, img_bytes: bytes, draw_params: dict) -> str:
    result = image_bytes_to_strokes(img_bytes, draw_params)
    result["word"] = word
    result["query"] = query
    dst = os.path.join(runtime_dir, "strokes.json")
    tmp = dst + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    os.replace(tmp, dst)
    return dst


def clear_dir(d: str):
    if not os.path.isdir(d):
        return
    for name in os.listdir(d):
        try:
            os.remove(os.path.join(d, name))
        except OSError:
            pass


def read_settings(runtime_dir: str) -> dict:
    """Read the shared runtime/settings.json (written by the in-game UI)."""
    path = os.path.join(runtime_dir, "settings.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def current_draw_params(draw_params: dict, runtime_dir: str) -> dict:
    """draw_params with any in-game settings (e.g. fill_enabled) applied."""
    p = dict(draw_params)
    settings = read_settings(runtime_dir)
    if "fill_enabled" in settings:
        p["fill_enabled"] = bool(settings["fill_enabled"])
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--once", action="store_true", help="process the current word.txt once and exit")
    ap.add_argument("--no-preview", action="store_true", help="disable preview, auto-draw the first result")
    args = ap.parse_args()

    cfg = load_config(args.config)
    runtime_dir = os.path.abspath(cfg.get("runtime_dir", "runtime"))
    os.makedirs(runtime_dir, exist_ok=True)

    provider = search.make_provider(cfg)
    search_n = int(cfg.get("search", {}).get("num_results", 6))
    do_translate = bool(cfg.get("translate", {}).get("enabled", True))
    draw_params = cfg.get("draw", {})
    poll_interval = float(cfg.get("poll_interval_seconds", 0.2))

    preview_cfg = cfg.get("preview", {})
    preview_enabled = (not args.no_preview) and bool(preview_cfg.get("enabled", True))
    num_candidates = int(preview_cfg.get("num_candidates", 4))

    word_file = os.path.join(runtime_dir, "word.txt")
    strokes_file = os.path.join(runtime_dir, "strokes.json")
    candidates_file = os.path.join(runtime_dir, "candidates.json")
    choice_file = os.path.join(runtime_dir, "choice.txt")
    preview_dir = os.path.join(runtime_dir, "preview")

    # state for the current preview round
    pending_word = ""
    pending_queries: list[str] = []

    last_mtime = None
    print(f"[assistant] watching {word_file} (preview={'on' if preview_enabled else 'off'})", flush=True)

    while True:
        # --- 1. new word ---
        if os.path.exists(word_file):
            try:
                st = os.stat(word_file)
            except OSError:
                st = None
            if st is not None and st.st_mtime_ns != last_mtime:
                last_mtime = st.st_mtime_ns
                with open(word_file, "r", encoding="utf-8") as f:
                    word = f.read().strip()
                if word:
                    print(f"[assistant] word: {word}", flush=True)
                    try:
                        en = translate.translate_zh_to_en(word) if do_translate else word
                        if en != word:
                            print(f"[assistant] translated -> {en}", flush=True)
                        results = find_images(provider, word, en, num_candidates if preview_enabled else 1)
                        if results:
                            if preview_enabled:
                                os.makedirs(preview_dir, exist_ok=True)
                                clear_dir(preview_dir)
                                pending_word = word
                                pending_queries = []
                                pending_candidates = []
                                for i, (q, data) in enumerate(results):
                                    pending_queries.append(q)
                                    with open(os.path.join(preview_dir, f"{i}.png"), "wb") as f:
                                        f.write(to_png(data))
                                manifest = {"word": word, "count": len(results), "queries": pending_queries}
                                with open(candidates_file, "w", encoding="utf-8") as f:
                                    json.dump(manifest, f, ensure_ascii=False)
                                print(f"[assistant] 已在游戏内展示 {len(results)} 张候选，等待选择", flush=True)
                            else:
                                query, img_bytes = results[0]
                                write_strokes(runtime_dir, word, query, img_bytes, current_draw_params(draw_params, runtime_dir))
                                print(f"[assistant] wrote {strokes_file} (query='{query}')", flush=True)
                        else:
                            print(f"[assistant] 没有找到 '{word}' 的图片", flush=True)
                    except Exception as e:
                        print(f"[assistant] error processing '{word}': {e}", flush=True)
        else:
            last_mtime = None

        # --- 2. player choice ---
        if os.path.exists(choice_file):
            try:
                with open(choice_file, "r", encoding="utf-8") as f:
                    choice = f.read().strip()
                os.remove(choice_file)
                if choice != "skip":
                    try:
                        idx = int(choice)
                    except ValueError:
                        idx = -1
                    png_path = os.path.join(preview_dir, f"{idx}.png")
                    if idx >= 0 and os.path.exists(png_path):
                        with open(png_path, "rb") as f:
                            png_bytes = f.read()
                        query = pending_queries[idx] if idx < len(pending_queries) else ""
                        write_strokes(runtime_dir, pending_word, query, png_bytes, current_draw_params(draw_params, runtime_dir))
                        print(f"[assistant] 玩家选择图 {idx + 1}，已写入 strokes.json", flush=True)
                else:
                    print(f"[assistant] 玩家跳过，不自动作画", flush=True)
                # cleanup after conversion
                if os.path.exists(candidates_file):
                    os.remove(candidates_file)
                clear_dir(preview_dir)
                pending_queries = []
            except Exception as e:
                print(f"[assistant] choice error: {e}", flush=True)

        if args.once:
            return 0
        time.sleep(poll_interval)


if __name__ == "__main__":
    sys.exit(main())
