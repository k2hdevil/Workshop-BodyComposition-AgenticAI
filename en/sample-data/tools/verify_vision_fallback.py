#!/usr/bin/env python3
"""
Vision fallback path verification

What it checks:
    When a PDF is put into a Bedrock Converse document block, does the service only run
    server-side text extraction (so no value can be read from a scanned copy with 0 characters
    of text layer) unless citations are turned on, and does it analyze the page visually and
    read the values once citations are turned on?

    The result decides the design of the extraction fallback in Lab 1.
      Readable     -> pure Python (pdfplumber) + Converse is enough. No native dependencies
      Not readable -> rasterization is needed (reconsider a PyMuPDF bundle / Lambda / Code Interpreter)

Run:
    python3 tools/verify_vision_fallback.py
"""

import json
import sys
from pathlib import Path

import boto3

REGION = "us-west-2"
MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"

ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "pdf"
GT_DIR = ROOT / "ground-truth"

PROMPT = (
    "From the attached body composition analysis sheet, extract only the values below as JSON.\n"
    "Leave items you cannot find as null. Do not output any text other than the JSON.\n"
    '{"name": Name, "age": Age, "weight_kg": Weight, "bmi": BMI, '
    '"pbf_percent": Percent Body Fat, "body_fat_mass_kg": Body Fat Mass, '
    '"skeletal_muscle_mass_kg": Skeletal Muscle}'
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
    """Compare the extraction result with the ground truth and return (hits, total, details)."""
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
    print(f"  document {doc_id} ({fmt}) · citations={citations}")
    print(f"{'─' * 66}")

    try:
        text, usage = call_converse(client, pdf, citations)
    except Exception as e:
        print(f"  call failed: {type(e).__name__}: {e}")
        return None

    got = parse_json(text)
    if got is None:
        print(f"  JSON parsing failed. Start of the raw text:\n    {text[:300]!r}")
        return 0, len(expected)

    hit, total, rows = compare(got, expected)
    for key, exp, val, ok in rows:
        mark = "O" if ok else "X"
        print(f"    {mark} {key:26s} truth {str(exp):10s} extracted {val}")
    print(f"  matched {hit}/{total}")
    if usage:
        print(
            f"  tokens  input {usage.get('inputTokens')} / output {usage.get('outputTokens')}"
        )
    return hit, total


def main():
    client = boto3.client("bedrock-runtime", region_name=REGION)
    print("=" * 66)
    print("  Vision fallback verification — Converse document block")
    print(f"  Region {REGION} · model {MODEL_ID}")
    print("=" * 66)

    results = {}

    # Control: a document with a text layer. Server-side text extraction alone should read it.
    results["text_pdf_no_citations"] = run_case(
        client, "user-a-session-03", None, "Control — text layer present / citations not set"
    )

    # Test 1: scanned copy + citations not set -> only text extraction is expected to run
    results["scan_no_citations"] = run_case(
        client, "user-a-session-01", None, "Test 1 — scan / citations not set"
    )

    # Test 2: scanned copy + citations enabled -> does vision analysis happen?
    results["scan_with_citations"] = run_case(
        client, "user-a-session-01", True, "Test 2 — scan / citations enabled"
    )

    print("\n" + "=" * 66)
    print("  Summary")
    print("=" * 66)
    for k, v in results.items():
        if v is None:
            print(f"    {k:26s} call failed")
        else:
            print(f"    {k:26s} {v[0]}/{v[1]} matched")

    scan_off = results.get("scan_no_citations")
    scan_on = results.get("scan_with_citations")
    print()
    if scan_on and scan_on[0] >= scan_on[1] - 1:
        print("  Conclusion: the scan is read through the vision path.")
        print("        -> pdfplumber + Converse is enough. No native dependencies needed.")
        if scan_off and scan_off[0] <= 1:
            print("        -> Confirmed: enabling citations is the switch for vision mode.")
        elif scan_off and scan_off[0] >= scan_off[1] - 1:
            print("        -> Readable without citations. This looks like default behavior, not a switch.")
    else:
        print("  Conclusion: the scan cannot be read.")
        print("        -> Rasterization is needed. Reconsider a PyMuPDF bundle / Lambda / Code Interpreter.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
