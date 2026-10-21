"""Convert a raster image into ordered drawing strokes for the plugin.

Two modes:

* ``fill_enabled`` (default): segment the image into flat-colour regions and
  emit, per region, an outline stroke (dark) followed by a fill stroke (a
  single interior point + the region colour). The plugin draws the outline as
  a line then calls the game's fill tool at the interior point.
* ``fill_enabled=false``: emit coloured outline strokes only (edge detection).

Stroke points are normalised to the unit square (x: left->right, y: bottom->top).
"""
from __future__ import annotations

import numpy as np
import cv2


def _decode(img_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image")
    return img


def _resize(img: np.ndarray, max_dim: int = 512) -> np.ndarray:
    h, w = img.shape[:2]
    scale = max_dim / float(max(h, w))
    if scale >= 1.0:
        return img
    return cv2.resize(img, (int(round(w * scale)), int(round(h * scale))),
                      interpolation=cv2.INTER_AREA)


def _is_line_art(gray: np.ndarray) -> bool:
    total = gray.size
    near_white = int(np.count_nonzero(gray >= 235))
    near_black = int(np.count_nonzero(gray <= 25))
    return (near_white / total) > 0.5 and (near_black / total) < 0.6


def _edge_map(gray: np.ndarray, params: dict) -> np.ndarray:
    if _is_line_art(gray):
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        edges = binary
    else:
        lo = int(params.get("canny_low", 60))
        hi = int(params.get("canny_high", 160))
        edges = cv2.Canny(gray, lo, hi)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)


def _simplify(points: np.ndarray, epsilon: float) -> np.ndarray:
    if len(points) < 3:
        return points
    approx = cv2.approxPolyDP(points, epsilon, False)
    return approx.reshape(-1, 2)


def _norm(pt, w, h):
    return [round(float(pt[0]) / float(w), 4), round(1.0 - float(pt[1]) / float(h), 4)]


def _sample_color(img_bgr, pts, offset_px, light_threshold, fallback):
    pts = pts.astype(np.float32)
    cx, cy = pts.mean(axis=0)
    d = pts - np.array([cx, cy], dtype=np.float32)
    norm = np.linalg.norm(d, axis=1, keepdims=True)
    norm[norm < 1e-6] = 1.0
    inward = pts - offset_px * (d / norm)
    h, w = img_bgr.shape[:2]
    inward[:, 0] = np.clip(inward[:, 0], 0, w - 1)
    inward[:, 1] = np.clip(inward[:, 1], 0, h - 1)
    idx = inward.astype(np.int32)
    b, g, r = img_bgr[idx[:, 1], idx[:, 0]].mean(axis=0)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    if lum > light_threshold:
        return list(fallback)
    return [int(round(r)), int(round(g)), int(round(b))]


def _outline_strokes(img_bgr, gray, w, h, params):
    use_color = bool(params.get("use_color", True))
    min_points = int(params.get("min_points", 3))
    approx_eps = float(params.get("approx_eps", 1.5))
    min_area = float(params.get("min_area", 20.0))
    width = int(params.get("width", 4))
    default_color = params.get("color", [0, 0, 0])
    offset_px = float(params.get("color_offset_px", 5.0))
    light_threshold = int(params.get("color_light_threshold", 215))

    edges = _edge_map(gray, params)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    strokes = []
    for cnt in contours:
        if abs(cv2.contourArea(cnt)) < min_area or len(cnt) < min_points:
            continue
        simplified = _simplify(cnt.reshape(-1, 2), approx_eps)
        if len(simplified) < min_points:
            continue
        pts = [_norm((x, y), w, h) for x, y in simplified]
        color = list(default_color)
        if use_color:
            color = _sample_color(img_bgr, simplified, offset_px, light_threshold, default_color)
        strokes.append({"points": pts, "width": width, "color": color, "fill": False})
    strokes.sort(key=lambda s: len(s["points"]), reverse=True)
    return strokes


def _segment_regions(img_bgr, params):
    k_colors = int(params.get("fill_colors", 8))
    min_area = float(params.get("fill_min_area", 80.0))
    approx_eps = float(params.get("approx_eps", 2.0))
    h, w = img_bgr.shape[:2]
    pixels = img_bgr.reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
    _, labels, centers = cv2.kmeans(pixels, k_colors, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    centers = centers.astype(np.int32)
    labels = labels.reshape(h, w)

    regions = []
    for k in range(k_colors):
        mask = (labels == k).astype(np.uint8)
        n, comps, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        for ci in range(1, n):
            area = int(stats[ci, cv2.CC_STAT_AREA])
            if area < min_area:
                continue
            comp_mask = (comps == ci).astype(np.uint8)
            contours, _ = cv2.findContours(comp_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            if not contours:
                continue
            cnt = max(contours, key=cv2.contourArea)
            simplified = _simplify(cnt.reshape(-1, 2), approx_eps)
            if len(simplified) < 3:
                continue
            b, g, r = centers[k]
            rgb = [int(r), int(g), int(b)]
            cx, cy = float(centroids[ci][0]), float(centroids[ci][1])
            regions.append((simplified, rgb, (cx, cy), area))
    regions.sort(key=lambda x: -x[3])
    return regions


def _fill_strokes(img_bgr, w, h, params):
    light_threshold = int(params.get("color_light_threshold", 215))
    dark_threshold = int(params.get("color_dark_threshold", 45))
    width = int(params.get("width", 4))
    outline_color = params.get("outline_color", [20, 20, 20])
    max_regions = int(params.get("fill_max_regions", 16))

    strokes = []
    count = 0
    for contour, rgb, (cx, cy), _area in _segment_regions(img_bgr, params):
        lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
        if lum > light_threshold:  # skip near-white background regions
            continue
        if lum < dark_threshold:   # skip near-black regions (they're outlines, already drawn)
            continue
        # outline stroke (dark) — close the loop so the game's fill tool can trace it
        pts = [_norm((x, y), w, h) for x, y in contour]
        pts.append(pts[0])
        strokes.append({"points": pts, "width": width, "color": list(outline_color), "fill": False})
        # fill stroke (single interior point)
        strokes.append({"points": [_norm((cx, cy), w, h)], "width": 0, "color": list(rgb), "fill": True})
        count += 1
        if count >= max_regions:
            break
    return strokes


def image_bytes_to_strokes(img_bytes: bytes, params: dict | None = None) -> dict:
    """Return ``{"aspect": float, "strokes": [{points, width, color, fill}]}``."""
    params = params or {}
    fill_enabled = bool(params.get("fill_enabled", True))
    max_dim = int(params.get("max_dim", 512))

    img = _resize(_decode(img_bytes), max_dim)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    strokes = _fill_strokes(img, w, h, params) if fill_enabled else _outline_strokes(img, gray, w, h, params)
    return {"aspect": float(w) / float(h), "strokes": strokes}
