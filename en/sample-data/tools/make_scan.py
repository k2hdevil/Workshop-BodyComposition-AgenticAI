#!/usr/bin/env python3
"""
Scan simulator — converts a text-layer PDF into an image-only PDF.

Purpose:
    Real body composition result sheets are often printed on paper by the device, and
    past sheets are kept as scans. A scanned copy has no text layer, so a structural
    parser such as pdfplumber cannot extract any value from it.

    This script reproduces that situation so that the fallback path of the extraction
    tool (structural parsing fails -> retry with a vision model) can be tested for real.

Behavior:
    Finds the documents with source_format == "scanned_image" in the ground-truth JSON
    and rasterizes the matching PDFs (grayscale + slight rotation + scanner noise).
    The rule for which document is a scan also lives in the JSON, which keeps a single
    source of truth.

Usage:
    uv run python make_scan.py                  # scan all of ground-truth
    uv run python make_scan.py <document-id>    # process one document only
"""

import io
import json
import sys
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageEnhance

DPI = 200
ROTATE_DEG = 0.35  # How crooked the sheet sits on the scanner
NOISE_SIGMA = 24  # Gaussian noise strength
NOISE_ALPHA = 0.05  # Noise blend ratio
CONTRAST = 0.94  # Slight loss of contrast from scanning
JPEG_QUALITY = 78

ROOT = Path(__file__).resolve().parent.parent
GT_DIR = ROOT / "ground-truth"
PDF_DIR = ROOT / "pdf"


def rasterize(pdf_path: Path) -> None:
    """Render the PDF to page images and overwrite it with a PDF that has no text."""
    src = fitz.open(pdf_path)
    out = fitz.open()

    for page in src:
        pix = page.get_pixmap(dpi=DPI)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")

        # Crooked-placement effect (margins are filled with white)
        img = img.rotate(ROTATE_DEG, resample=Image.BICUBIC, fillcolor=255)

        # Scanner sensor noise
        noise = Image.effect_noise(img.size, NOISE_SIGMA)
        img = Image.blend(img, noise, NOISE_ALPHA)

        # Contrast loss from scanning
        img = ImageEnhance.Contrast(img).enhance(CONTRAST)

        buf = io.BytesIO()
        img.convert("L").save(buf, format="JPEG", quality=JPEG_QUALITY)

        # Insert only the image into a blank page of the same size -> no text layer
        new_page = out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, stream=buf.getvalue())

    src.close()
    tmp = pdf_path.with_suffix(".scan.tmp.pdf")
    out.save(tmp, deflate=True)
    out.close()
    tmp.replace(pdf_path)


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    targets = []

    for gt in sorted(GT_DIR.glob("*.json")):
        data = json.loads(gt.read_text(encoding="utf-8"))
        if data.get("source_format") != "scanned_image":
            continue
        if only and data["document_id"] != only:
            continue
        pdf = PDF_DIR / f"{data['document_id']}.pdf"
        if not pdf.exists():
            print(f"  skipped  {pdf.name} not found — run build_samples.sh first")
            continue
        targets.append(pdf)

    if not targets:
        print("  No scan targets (no document with source_format == 'scanned_image' found)")
        return 0

    for pdf in targets:
        before = pdf.stat().st_size
        rasterize(pdf)
        after = pdf.stat().st_size
        print(f"  scanned  {pdf.name}  {before:,}B -> {after:,}B (text layer removed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
