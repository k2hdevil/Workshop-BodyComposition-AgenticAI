#!/usr/bin/env python3
"""
Sample result sheet verification

It checks two things.

  A. Arithmetic consistency of the ground-truth JSON
     The values on a sheet depend on each other. If one value is changed and the others are
     not, the Ground Truth silently drifts apart, and that is a bug, not an answer key.
     The invariants below prevent it.

       Total Body Water + Protein + Minerals + Body Fat Mass = Weight
       Fat-Free Mass = Total Body Water + Protein + Minerals
       Intracellular Water + Extracellular Water = Total Body Water
       ECW/TBW ratio = Extracellular Water / Total Body Water
       BMI = Weight / Height(m)²
       Basal Metabolic Rate = 21.6 × Fat-Free Mass + 370
       percent of standard (%) = measured / standard × 100
       Muscle Change + Fat Change = Weight Change
       Target Weight = Weight + Weight Change

  B. Compare the PDF with the ground truth
     For a document whose source_format is digital_export, the key values must be extractable
     from the text layer. For a document whose source_format is scanned_image, no text may be
     extractable. The latter is the basis for testing the vision fallback path of the
     extraction tool.

Usage:
    python3 tools/verify_samples.py
"""

import json
import logging
import sys
from pathlib import Path

# Suppress the warnings pdfplumber emits when it reads FontBBox in Chrome-generated PDFs (harmless)
logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfplumber").setLevel(logging.ERROR)

import pdfplumber  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GT_DIR = ROOT / "ground-truth"
PDF_DIR = ROOT / "pdf"

TOL = 0.06  # Absolute tolerance that allows for display rounding
PCT_TOL = 0.1  # Tolerance for percentage items (shown with 1 decimal)


class Report:
    def __init__(self):
        self.passed = 0
        self.failures: list[str] = []

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        if ok:
            self.passed += 1
        else:
            self.failures.append(f"{label}{(' — ' + detail) if detail else ''}")

    def near(self, actual, expected, label, tol=TOL) -> None:
        ok = abs(actual - expected) <= tol
        self.check(ok, label, f"expected {expected:.4f}, actual {actual:.4f} (tolerance ±{tol})")


def verify_arithmetic(d: dict, rep: Report) -> None:
    doc = d["document_id"]
    s, r = d["subject"], d["reference"]
    bca, mfa = d["body_composition_analysis"], d["muscle_fat_analysis"]
    ob, seg, add = d["obesity_analysis"], d["segmental_lean_analysis"], d["additional_metrics"]
    cg = d["control_guide"]

    tbw = bca["total_body_water_kg"]["value"]
    pro = bca["protein_kg"]["value"]
    mnr = bca["minerals_kg"]["value"]
    bfm = bca["body_fat_mass_kg"]["value"]
    ffm = bca["fat_free_mass_kg"]
    wt = bca["weight_kg"]

    p = f"[{doc}]"
    rep.near(tbw + pro + mnr + bfm, wt, f"{p} sum of the four composition items = weight")
    rep.near(tbw + pro + mnr, ffm, f"{p} fat-free mass = body water + protein + minerals")
    rep.near(wt - bfm, ffm, f"{p} fat-free mass = weight - body fat mass")
    rep.near(
        bca["intracellular_water_kg"] + bca["extracellular_water_kg"],
        tbw,
        f"{p} intracellular + extracellular water = total body water",
    )
    rep.near(
        bca["ecw_tbw_ratio"]["value"],
        bca["extracellular_water_kg"] / tbw,
        f"{p} ECW/TBW ratio",
        tol=0.001,
    )

    # Obesity analysis
    h_m = s["height_cm"] / 100.0
    rep.near(ob["bmi"]["value"], wt / (h_m**2), f"{p} BMI = weight / height²")
    rep.near(ob["pbf_percent"]["value"], bfm / wt * 100, f"{p} percent body fat = body fat mass / weight")

    # Percent of standard in the muscle-fat analysis
    rep.near(
        mfa["weight_kg"]["percent_of_standard"],
        wt / r["standard_weight_kg"] * 100,
        f"{p} weight percent of standard",
        tol=PCT_TOL,
    )
    rep.near(
        mfa["skeletal_muscle_mass_kg"]["percent_of_standard"],
        mfa["skeletal_muscle_mass_kg"]["value"] / r["standard_smm_kg"] * 100,
        f"{p} skeletal muscle percent of standard",
        tol=PCT_TOL,
    )
    rep.near(
        mfa["body_fat_mass_kg"]["percent_of_standard"],
        bfm / r["standard_bfm_kg"] * 100,
        f"{p} body fat mass percent of standard",
        tol=PCT_TOL,
    )
    # Body fat mass appears in three sections; check that all copies hold the same value
    rep.near(mfa["body_fat_mass_kg"]["value"], bfm, f"{p} body fat mass matches across sections")
    rep.near(mfa["weight_kg"]["value"], wt, f"{p} weight matches across sections")

    # Segmental lean mass
    for key in ("right_arm", "left_arm", "trunk", "right_leg", "left_leg"):
        it = seg[key]
        rep.near(
            it["percent_of_standard"],
            it["mass_kg"] / it["std_kg"] * 100,
            f"{p} segment {it['label_ko']} percent of standard",
            tol=PCT_TOL,
        )
    # The segment sum leaves out non-segmental parts such as the head, so it must be below fat-free mass
    seg_sum = sum(seg[k]["mass_kg"] for k in ("right_arm", "left_arm", "trunk", "right_leg", "left_leg"))
    rep.check(
        seg_sum < ffm,
        f"{p} segment sum < fat-free mass",
        f"sum {seg_sum:.2f} vs fat-free mass {ffm:.2f}",
    )

    # Basal metabolic rate
    rep.near(
        float(add["basal_metabolic_rate_kcal"]["value"]),
        21.6 * ffm + 370,
        f"{p} BMR = 21.6 × fat-free mass + 370",
        tol=0.5,
    )

    # Weight control guide
    rep.near(
        cg["muscle_control_kg"] + cg["fat_control_kg"],
        cg["weight_control_kg"],
        f"{p} muscle change + fat change = weight change",
    )
    rep.near(
        cg["target_weight_kg"],
        wt + cg["weight_control_kg"],
        f"{p} target weight = weight + weight change",
    )

    # Check that the status flags do not contradict the standard range
    for sect, keys in (
        (bca, ("total_body_water_kg", "protein_kg", "minerals_kg", "body_fat_mass_kg")),
        (ob, ("bmi", "pbf_percent")),
    ):
        for k in keys:
            it = sect[k]
            v, lo, hi, flag = it["value"], it["std_low"], it["std_high"], it["flag"]
            expect = "LOW" if v < lo else ("HIGH" if v > hi else "NORMAL")
            rep.check(flag == expect, f"{p} {it['label_ko']} status", f"expected {expect}, actual {flag}")

    for key in ("right_arm", "left_arm", "trunk", "right_leg", "left_leg"):
        it = seg[key]
        pos = it["percent_of_standard"]
        expect = "BELOW" if pos < 95 else ("ABOVE" if pos > 105 else "NORMAL")
        rep.check(
            it["flag"] == expect,
            f"{p} segment {it['label_ko']} status",
            f"{pos}% -> expected {expect}, actual {it['flag']}",
        )

    # Check that the body type matches the shape of the three bars
    w_p = mfa["weight_kg"]["percent_of_standard"]
    m_p = mfa["skeletal_muscle_mass_kg"]["percent_of_standard"]
    f_p = mfa["body_fat_mass_kg"]["percent_of_standard"]
    if m_p < w_p and f_p > w_p:
        expect_type = "C"
    elif m_p > w_p and f_p < w_p:
        expect_type = "D"
    else:
        expect_type = "I"
    rep.check(
        mfa["body_type"] == expect_type,
        f"{p} body type",
        f"weight {w_p} / muscle {m_p} / fat {f_p} -> expected {expect_type}, actual {mfa['body_type']}",
    )


def verify_trend(docs: dict, rep: Report) -> None:
    """Check that the trend block matches the real differences between sessions."""
    for doc_id, d in docs.items():
        trend = d.get("expected_trend_vs_session_01")
        if not trend:
            continue
        base_id = f"{d['subject']['subject_id']}-session-01"
        base = docs.get(base_id)
        rep.check(base is not None, f"[{doc_id}] trend baseline document {base_id} exists")
        if base is None:
            continue
        p = f"[{doc_id}] trend"
        cur_b, base_b = d["body_composition_analysis"], base["body_composition_analysis"]
        rep.near(trend["weight_delta_kg"], cur_b["weight_kg"] - base_b["weight_kg"], f"{p} weight delta")
        rep.near(
            trend["body_fat_mass_delta_kg"],
            cur_b["body_fat_mass_kg"]["value"] - base_b["body_fat_mass_kg"]["value"],
            f"{p} body fat mass delta",
        )
        rep.near(
            trend["skeletal_muscle_mass_delta_kg"],
            d["muscle_fat_analysis"]["skeletal_muscle_mass_kg"]["value"]
            - base["muscle_fat_analysis"]["skeletal_muscle_mass_kg"]["value"],
            f"{p} skeletal muscle mass delta",
        )
        rep.near(
            trend["pbf_delta_pp"],
            d["obesity_analysis"]["pbf_percent"]["value"]
            - base["obesity_analysis"]["pbf_percent"]["value"],
            f"{p} percent body fat delta",
        )
        rep.near(
            trend["bmi_delta"],
            d["obesity_analysis"]["bmi"]["value"] - base["obesity_analysis"]["bmi"]["value"],
            f"{p} BMI delta",
        )
        rep.check(
            trend["visceral_fat_level_delta"]
            == d["additional_metrics"]["visceral_fat_level"]["value"]
            - base["additional_metrics"]["visceral_fat_level"]["value"],
            f"{p} visceral fat level delta",
        )
        rep.check(
            trend["score_delta"]
            == d["additional_metrics"]["body_composition_score"]["value"]
            - base["additional_metrics"]["body_composition_score"]["value"],
            f"{p} body composition score delta",
        )


def verify_pdf(d: dict, rep: Report) -> None:
    doc = d["document_id"]
    pdf_path = PDF_DIR / f"{doc}.pdf"
    p = f"[{doc}] PDF"

    if not pdf_path.exists():
        rep.check(False, f"{p} file exists", "run build_samples.sh first")
        return
    rep.check(True, f"{p} file exists")

    with pdfplumber.open(pdf_path) as pdf:
        # A real body composition sheet is one page. If the layout overflows it silently becomes
        # 2 pages, so catch it here. (The overflow page is almost empty and unfit as a result sheet.)
        rep.check(
            len(pdf.pages) == 1,
            f"{p} fits on 1 page",
            f"{len(pdf.pages)} pages — the layout overflowed",
        )
        text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)

    if d["source_format"] == "scanned_image":
        # A scanned copy must have no text layer (the basis for testing the vision fallback path)
        rep.check(
            len(text.strip()) == 0,
            f"{p} scan has no text layer",
            f"{len(text.strip())} characters extracted — not image-only",
        )
        return

    # A digital export must yield the key values as text
    bca = d["body_composition_analysis"]
    ob = d["obesity_analysis"]
    mfa = d["muscle_fat_analysis"]
    seg = d["segmental_lean_analysis"]
    expected = [
        d["subject"]["name"],
        f"{d['subject']['age']}",
        f"{bca['weight_kg']:.1f}",
        f"{bca['body_fat_mass_kg']['value']:.1f}",
        f"{bca['total_body_water_kg']['value']:.1f}",
        f"{ob['bmi']['value']:.1f}",
        f"{ob['pbf_percent']['value']:.1f}",
        mfa["body_type_label_ko"],
        f"{seg['trunk']['mass_kg']:.2f}",
        f"{seg['right_arm']['mass_kg']:.2f}",
        f"{d['additional_metrics']['basal_metabolic_rate_kcal']['value']:,}",
    ]
    missing = [e for e in expected if e not in text]
    rep.check(
        not missing,
        f"{p} {len(expected)} ground-truth values extracted as text",
        f"missing: {missing}",
    )
    # Check that all 4 section titles are present
    sections = ["1. Body Composition Analysis", "2. Muscle-Fat Analysis", "3. Obesity Analysis", "4. Segmental Lean Analysis"]
    missing_s = [s for s in sections if s not in text]
    rep.check(not missing_s, f"{p} 4 section titles present", f"missing: {missing_s}")
    # Check that the synthetic data disclaimer is present
    rep.check("SYNTHETIC DATA" in text, f"{p} synthetic data disclaimer present")


def main() -> int:
    rep = Report()
    docs = {}

    files = sorted(GT_DIR.glob("*.json"))
    if not files:
        print("No ground-truth JSON found.", file=sys.stderr)
        return 1

    print("=" * 68)
    print("  Body composition result sheet sample verification")
    print("=" * 68)

    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        docs[d["document_id"]] = d
        verify_arithmetic(d, rep)
        verify_pdf(d, rep)

    verify_trend(docs, rep)

    print(f"\n  {len(docs)} documents / {rep.passed + len(rep.failures)} checks")
    print(f"  {rep.passed} passed · {len(rep.failures)} failed")

    if rep.failures:
        print("\n  Failures:")
        for fail in rep.failures:
            print(f"    X {fail}")
        print()
        return 1

    print("\n  All checks passed\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
