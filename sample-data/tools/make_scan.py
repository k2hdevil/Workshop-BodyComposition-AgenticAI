#!/usr/bin/env python3
"""
스캔본 시뮬레이터 — 텍스트 레이어 PDF를 이미지 전용 PDF로 변환합니다.

목적:
    실제 체성분 결과지는 기기에서 종이로 출력되는 경우가 많고, 과거 결과지는
    스캔해서 보관합니다. 스캔본에는 텍스트 레이어가 없으므로 pdfplumber 같은
    구조 파서로는 아무 값도 뽑을 수 없습니다.

    이 스크립트는 그 상황을 재현하여, 추출 도구의 폴백 경로
    (구조 파싱 실패 -> 비전 모델로 재시도)를 실제로 검증할 수 있게 합니다.

동작:
    ground-truth JSON에서 source_format == "scanned_image" 인 문서를 찾아,
    대응하는 PDF를 래스터화(그레이스케일 + 미세 회전 + 스캐너 노이즈)합니다.
    어느 문서가 스캔본인지의 판단 기준도 JSON에 두어 단일 원본을 유지합니다.

사용법:
    uv run python make_scan.py            # ground-truth 전체를 훑어 처리
    uv run python make_scan.py <문서ID>    # 특정 문서만 처리
"""

import io
import json
import sys
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageEnhance

DPI = 200
ROTATE_DEG = 0.35  # 스캐너에 비뚤게 올려놓은 정도
NOISE_SIGMA = 24  # 가우시안 노이즈 세기
NOISE_ALPHA = 0.05  # 노이즈 혼합 비율
CONTRAST = 0.94  # 스캔 시 살짝 흐려지는 정도
JPEG_QUALITY = 78

ROOT = Path(__file__).resolve().parent.parent
GT_DIR = ROOT / "ground-truth"
PDF_DIR = ROOT / "pdf"


def rasterize(pdf_path: Path) -> None:
    """PDF를 페이지 이미지로 굽고, 텍스트 없는 PDF로 덮어씁니다."""
    src = fitz.open(pdf_path)
    out = fitz.open()

    for page in src:
        pix = page.get_pixmap(dpi=DPI)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")

        # 스캐너에 비뚤게 올린 효과 (여백은 흰색으로 채움)
        img = img.rotate(ROTATE_DEG, resample=Image.BICUBIC, fillcolor=255)

        # 스캐너 센서 노이즈
        noise = Image.effect_noise(img.size, NOISE_SIGMA)
        img = Image.blend(img, noise, NOISE_ALPHA)

        # 스캔 시 대비 저하
        img = ImageEnhance.Contrast(img).enhance(CONTRAST)

        buf = io.BytesIO()
        img.convert("L").save(buf, format="JPEG", quality=JPEG_QUALITY)

        # 원본과 같은 크기의 빈 페이지에 이미지만 삽입 -> 텍스트 레이어 없음
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
            print(f"  건너뜀  {pdf.name} 없음 — build_samples.sh를 먼저 실행하세요")
            continue
        targets.append(pdf)

    if not targets:
        print("  스캔본 대상 없음 (source_format == 'scanned_image' 문서를 찾지 못함)")
        return 0

    for pdf in targets:
        before = pdf.stat().st_size
        rasterize(pdf)
        after = pdf.stat().st_size
        print(f"  스캔본화  {pdf.name}  {before:,}B -> {after:,}B (텍스트 레이어 제거)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
