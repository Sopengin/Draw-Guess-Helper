#!/usr/bin/env python3
"""Local OCR helper — extracts text from an image (screenshot).

Uses RapidOCR (ONNX Runtime, PaddleOCR models) which handles Chinese + English
well with no GPU / heavy framework required.

Usage:
    python tools/ocr.py <image_path> [--raw]
      default: prints text lines in reading order (top-to-bottom, left-to-right)
      --raw  : prints one "text<TAB>score<TAB>x0,y0,x1,y1" per line
"""
import sys
import argparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def _sort_key(item):
    box, text, score = item
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    y = min(ys)
    x = min(xs)
    # Group by vertical band (~10px) so lines are read in natural order.
    band = int(y // 12)
    return (band, x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--raw", action="store_true")
    args = ap.parse_args()

    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    result, _ = engine(args.image)

    if not result:
        print("(no text recognized)", file=sys.stderr)
        return 1

    if args.raw:
        for box, text, score in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            print("%s\t%.3f\t%.0f,%.0f,%.0f,%.0f" % (text, float(score), min(xs), min(ys), max(xs), max(ys)))
    else:
        for box, text, score in sorted(result, key=_sort_key):
            print(text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
