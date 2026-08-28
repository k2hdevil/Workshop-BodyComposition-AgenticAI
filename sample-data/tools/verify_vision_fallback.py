#!/usr/bin/env python3
"""
비전 폴백 경로 검증

확인하려는 것:
    Bedrock Converse 의 document 블록에 PDF 를 넣을 때, citations 를 켜지 않으면
    서버 측 텍스트 추출만 수행되어 스캔본(텍스트 레이어 0자)에서는 값을 얻을 수 없고,
    citations 를 켜면 페이지를 시각적으로 분석해 값을 읽어내는지.

    이 결과에 따라 Lab 1 의 추출 폴백 설계가 갈립니다.
      읽힘  -> 순수 Python(pdfplumber) + Converse 만으로 완결. 네이티브 의존성 없음
      안 읽힘 -> 래스터화가 필요 (PyMuPDF 번들 / Lambda / Code Interpreter 재검토)

실행:
    python3 tools/verify_vision_fallback.py
"""

import json
import sys
from pathlib import Path

import boto3

REGION = "us-east-1"
MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "pdf"
GT_DIR = ROOT / "ground-truth"

PROMPT = (
    "첨부한 체성분 분석 결과지에서 아래 항목의 값만 JSON 으로 추출하세요.\n"
    "찾을 수 없는 항목은 null 로 두세요. JSON 외의 텍스트는 출력하지 마세요.\n"
    '{"name": 성명, "age": 나이, "weight_kg": 체중, "bmi": BMI, '
    '"pbf_percent": 체지방률, "body_fat_mass_kg": 체지방량, '
    '"skeletal_muscle_mass_kg": 골격근량}'
)


def load_expected(doc_id):
    d = json.loads((GT_DIR / f"{doc_id}.json").read_text(encoding="utf-8"))
    return {
        "name": d["subject"]["name"],
        "age": d["subject"]["age"],
        "weight_kg": d["body_composition_analysis"]["weight_kg"],
        "bmi": d["obesity_analysis"]["bmi"]["value"],
        "pbf_percent": d["obesity_analysis"]["pbf_percent"]["value"],
        "body_fat_mass_kg": d["body_composition_analysis"]["body_fat_mass_kg"]["value"],
        "skeletal_muscle_mass_kg": d["muscle_fat_analysis"]["skeletal_muscle_mass_kg"]["value"],
    }, d["source_format"]


def call_converse(client, pdf_bytes, citations):
    doc = {
        "format": "pdf",
        "name": "sheet",
        "source": {"bytes": pdf_bytes},
    }
    if citations is not None:
        doc["citations"] = {"enabled": citations}

    resp = client.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"document": doc}, {"text": PROMPT}]}],
        inferenceConfig={"maxTokens": 800, "temperature": 0},
    )
    parts = []
    for block in resp["output"]["message"]["content"]:
        if "text" in block:
            parts.append(block["text"])
        elif "citationsContent" in block:
            for c in block["citationsContent"].get("content", []):
                if "text" in c:
                    parts.append(c["text"])
    return "".join(parts), resp.get("usage", {})


def parse_json(text):
    t = text.strip()
    if "```" in t:
        t = t.split("```")[1].replace("json", "", 1).strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return None


def num_eq(a, b, tol=0.05):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def compare(got, expected):
    """추출 결과를 정답과 대조하여 (맞은 개수, 전체, 상세) 를 반환합니다."""
    rows = []
    hit = 0
    for key, exp in expected.items():
        val = got.get(key) if isinstance(got, dict) else None
        if key == "name":
            ok = isinstance(val, str) and val.strip() == exp
        elif key == "age":
            ok = num_eq(val, exp, tol=0)
        else:
            ok = num_eq(val, exp)
        hit += ok
        rows.append((key, exp, val, ok))
    return hit, len(expected), rows


def run_case(client, doc_id, citations, label):
    pdf = (PDF_DIR / f"{doc_id}.pdf").read_bytes()
    expected, fmt = load_expected(doc_id)

    print(f"\n{'─' * 66}")
    print(f"  {label}")
    print(f"  문서 {doc_id} ({fmt}) · citations={citations}")
    print(f"{'─' * 66}")

    try:
        text, usage = call_converse(client, pdf, citations)
    except Exception as e:
        print(f"  호출 실패: {type(e).__name__}: {e}")
        return None

    got = parse_json(text)
    if got is None:
        print(f"  JSON 파싱 실패. 원문 앞부분:\n    {text[:300]!r}")
        return 0, len(expected)

    hit, total, rows = compare(got, expected)
    for key, exp, val, ok in rows:
        mark = "O" if ok else "X"
        print(f"    {mark} {key:26s} 정답 {str(exp):10s} 추출 {val}")
    print(f"  일치 {hit}/{total}")
    if usage:
        print(
            f"  토큰  입력 {usage.get('inputTokens')} / 출력 {usage.get('outputTokens')}"
        )
    return hit, total


def main():
    client = boto3.client("bedrock-runtime", region_name=REGION)
    print("=" * 66)
    print("  비전 폴백 검증 — Converse document 블록")
    print(f"  리전 {REGION} · 모델 {MODEL_ID}")
    print("=" * 66)

    results = {}

    # 대조군: 텍스트 레이어가 있는 문서. 서버 측 텍스트 추출만으로도 읽혀야 합니다.
    results["text_pdf_no_citations"] = run_case(
        client, "user-a-session-03", None, "대조군 — 텍스트 레이어 있음 / citations 미지정"
    )

    # 본 검증 1: 스캔본 + citations 미지정 -> 텍스트 추출만 수행될 것으로 예상
    results["scan_no_citations"] = run_case(
        client, "user-a-session-01", None, "검증 1 — 스캔본 / citations 미지정"
    )

    # 본 검증 2: 스캔본 + citations 활성 -> 비전 분석이 일어나는지
    results["scan_with_citations"] = run_case(
        client, "user-a-session-01", True, "검증 2 — 스캔본 / citations 활성"
    )

    print("\n" + "=" * 66)
    print("  요약")
    print("=" * 66)
    for k, v in results.items():
        if v is None:
            print(f"    {k:26s} 호출 실패")
        else:
            print(f"    {k:26s} {v[0]}/{v[1]} 일치")

    scan_off = results.get("scan_no_citations")
    scan_on = results.get("scan_with_citations")
    print()
    if scan_on and scan_on[0] >= scan_on[1] - 1:
        print("  결론: 스캔본이 비전 경로로 읽힙니다.")
        print("        -> pdfplumber + Converse 만으로 완결. 네이티브 의존성 불필요.")
        if scan_off and scan_off[0] <= 1:
            print("        -> citations 활성화가 비전 모드 스위치임이 확인됨.")
        elif scan_off and scan_off[0] >= scan_off[1] - 1:
            print("        -> citations 없이도 읽힘. 스위치가 아니라 기본 동작인 듯.")
    else:
        print("  결론: 스캔본이 읽히지 않습니다.")
        print("        -> 래스터화 필요. PyMuPDF 번들 / Lambda / Code Interpreter 재검토.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
