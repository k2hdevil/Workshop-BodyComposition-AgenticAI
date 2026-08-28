#!/usr/bin/env python3
"""
샘플 결과지 검증

두 가지를 검사합니다.

  A. 정답 JSON의 산수 정합성
     결과지 수치는 서로 종속됩니다. 하나를 고치고 나머지를 안 고치면 조용히 어긋난
     Ground Truth가 만들어지고, 그건 정답이 아니라 버그입니다. 아래 불변식으로 막습니다.

       체수분 + 단백질 + 무기질 + 체지방량 = 체중
       제지방량 = 체수분 + 단백질 + 무기질
       세포내수분 + 세포외수분 = 체수분
       세포외수분비 = 세포외수분 / 체수분
       BMI = 체중 / 신장(m)²
       기초대사량 = 21.6 × 제지방량 + 370
       표준대비(%) = 측정값 / 표준값 × 100
       근육조절 + 지방조절 = 체중조절
       적정체중 = 체중 + 체중조절

  B. PDF와 정답의 대조
     source_format 이 digital_export 인 문서는 텍스트 레이어에서 핵심 값이 추출되어야
     하고, scanned_image 인 문서는 추출되는 텍스트가 없어야 합니다. 후자가 추출 도구의
     비전 폴백 경로를 검증하는 근거입니다.

사용법:
    python3 tools/verify_samples.py
"""

import json
import logging
import sys
from pathlib import Path

# pdfplumber가 Chrome 생성 PDF의 FontBBox를 읽으며 쏟아내는 경고 억제 (동작에 무해)
logging.getLogger("pdfminer").setLevel(logging.ERROR)
logging.getLogger("pdfplumber").setLevel(logging.ERROR)

import pdfplumber  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GT_DIR = ROOT / "ground-truth"
PDF_DIR = ROOT / "pdf"

TOL = 0.06  # 표시 반올림을 허용하는 절대 오차
PCT_TOL = 0.1  # 백분율 항목 허용 오차 (소수 1자리 표시)


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
        self.check(ok, label, f"기대 {expected:.4f}, 실제 {actual:.4f} (허용 ±{tol})")


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
    rep.near(tbw + pro + mnr + bfm, wt, f"{p} 체성분 4항목 합 = 체중")
    rep.near(tbw + pro + mnr, ffm, f"{p} 제지방량 = 체수분+단백질+무기질")
    rep.near(wt - bfm, ffm, f"{p} 제지방량 = 체중 - 체지방량")
    rep.near(
        bca["intracellular_water_kg"] + bca["extracellular_water_kg"],
        tbw,
        f"{p} 세포내수분 + 세포외수분 = 체수분",
    )
    rep.near(
        bca["ecw_tbw_ratio"]["value"],
        bca["extracellular_water_kg"] / tbw,
        f"{p} 세포외수분비",
        tol=0.001,
    )

    # 비만 분석
    h_m = s["height_cm"] / 100.0
    rep.near(ob["bmi"]["value"], wt / (h_m**2), f"{p} BMI = 체중 / 신장²")
    rep.near(ob["pbf_percent"]["value"], bfm / wt * 100, f"{p} 체지방률 = 체지방량 / 체중")

    # 골격근·지방 분석의 표준 대비 백분율
    rep.near(
        mfa["weight_kg"]["percent_of_standard"],
        wt / r["standard_weight_kg"] * 100,
        f"{p} 체중 표준대비%",
        tol=PCT_TOL,
    )
    rep.near(
        mfa["skeletal_muscle_mass_kg"]["percent_of_standard"],
        mfa["skeletal_muscle_mass_kg"]["value"] / r["standard_smm_kg"] * 100,
        f"{p} 골격근량 표준대비%",
        tol=PCT_TOL,
    )
    rep.near(
        mfa["body_fat_mass_kg"]["percent_of_standard"],
        bfm / r["standard_bfm_kg"] * 100,
        f"{p} 체지방량 표준대비%",
        tol=PCT_TOL,
    )
    # 세 섹션에 중복 등장하는 체지방량이 서로 같은 값인지
    rep.near(mfa["body_fat_mass_kg"]["value"], bfm, f"{p} 체지방량 섹션 간 일치")
    rep.near(mfa["weight_kg"]["value"], wt, f"{p} 체중 섹션 간 일치")

    # 부위별 근육
    for key in ("right_arm", "left_arm", "trunk", "right_leg", "left_leg"):
        it = seg[key]
        rep.near(
            it["percent_of_standard"],
            it["mass_kg"] / it["std_kg"] * 100,
            f"{p} 부위별 {it['label_ko']} 표준대비%",
            tol=PCT_TOL,
        )
    # 부위 합은 머리 등 비분절 부위가 빠지므로 제지방량보다 작아야 함
    seg_sum = sum(seg[k]["mass_kg"] for k in ("right_arm", "left_arm", "trunk", "right_leg", "left_leg"))
    rep.check(
        seg_sum < ffm,
        f"{p} 부위별 합 < 제지방량",
        f"합 {seg_sum:.2f} vs 제지방량 {ffm:.2f}",
    )

    # 기초대사량
    rep.near(
        float(add["basal_metabolic_rate_kcal"]["value"]),
        21.6 * ffm + 370,
        f"{p} 기초대사량 = 21.6 × 제지방량 + 370",
        tol=0.5,
    )

    # 체중 조절 가이드
    rep.near(
        cg["muscle_control_kg"] + cg["fat_control_kg"],
        cg["weight_control_kg"],
        f"{p} 근육조절 + 지방조절 = 체중조절",
    )
    rep.near(
        cg["target_weight_kg"],
        wt + cg["weight_control_kg"],
        f"{p} 적정체중 = 체중 + 체중조절",
    )

    # 판정 플래그가 표준범위와 모순되지 않는지
    for sect, keys in (
        (bca, ("total_body_water_kg", "protein_kg", "minerals_kg", "body_fat_mass_kg")),
        (ob, ("bmi", "pbf_percent")),
    ):
        for k in keys:
            it = sect[k]
            v, lo, hi, flag = it["value"], it["std_low"], it["std_high"], it["flag"]
            expect = "LOW" if v < lo else ("HIGH" if v > hi else "NORMAL")
            rep.check(flag == expect, f"{p} {it['label_ko']} 판정", f"기대 {expect}, 실제 {flag}")

    for key in ("right_arm", "left_arm", "trunk", "right_leg", "left_leg"):
        it = seg[key]
        pos = it["percent_of_standard"]
        expect = "BELOW" if pos < 95 else ("ABOVE" if pos > 105 else "NORMAL")
        rep.check(
            it["flag"] == expect,
            f"{p} 부위별 {it['label_ko']} 판정",
            f"{pos}% -> 기대 {expect}, 실제 {it['flag']}",
        )

    # 체형 판정이 세 막대의 형태와 맞는지
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
        f"{p} 체형 판정",
        f"체중 {w_p} / 근육 {m_p} / 지방 {f_p} -> 기대 {expect_type}, 실제 {mfa['body_type']}",
    )


def verify_trend(docs: dict, rep: Report) -> None:
    """추이 블록이 실제 회차 간 차이와 일치하는지 확인합니다."""
    for doc_id, d in docs.items():
        trend = d.get("expected_trend_vs_session_01")
        if not trend:
            continue
        base_id = f"{d['subject']['subject_id']}-session-01"
        base = docs.get(base_id)
        rep.check(base is not None, f"[{doc_id}] 추이 기준 문서 {base_id} 존재")
        if base is None:
            continue
        p = f"[{doc_id}] 추이"
        cur_b, base_b = d["body_composition_analysis"], base["body_composition_analysis"]
        rep.near(trend["weight_delta_kg"], cur_b["weight_kg"] - base_b["weight_kg"], f"{p} 체중 델타")
        rep.near(
            trend["body_fat_mass_delta_kg"],
            cur_b["body_fat_mass_kg"]["value"] - base_b["body_fat_mass_kg"]["value"],
            f"{p} 체지방량 델타",
        )
        rep.near(
            trend["skeletal_muscle_mass_delta_kg"],
            d["muscle_fat_analysis"]["skeletal_muscle_mass_kg"]["value"]
            - base["muscle_fat_analysis"]["skeletal_muscle_mass_kg"]["value"],
            f"{p} 골격근량 델타",
        )
        rep.near(
            trend["pbf_delta_pp"],
            d["obesity_analysis"]["pbf_percent"]["value"]
            - base["obesity_analysis"]["pbf_percent"]["value"],
            f"{p} 체지방률 델타",
        )
        rep.near(
            trend["bmi_delta"],
            d["obesity_analysis"]["bmi"]["value"] - base["obesity_analysis"]["bmi"]["value"],
            f"{p} BMI 델타",
        )
        rep.check(
            trend["visceral_fat_level_delta"]
            == d["additional_metrics"]["visceral_fat_level"]["value"]
            - base["additional_metrics"]["visceral_fat_level"]["value"],
            f"{p} 내장지방레벨 델타",
        )
        rep.check(
            trend["score_delta"]
            == d["additional_metrics"]["body_composition_score"]["value"]
            - base["additional_metrics"]["body_composition_score"]["value"],
            f"{p} 체성분점수 델타",
        )


def verify_pdf(d: dict, rep: Report) -> None:
    doc = d["document_id"]
    pdf_path = PDF_DIR / f"{doc}.pdf"
    p = f"[{doc}] PDF"

    if not pdf_path.exists():
        rep.check(False, f"{p} 파일 존재", "build_samples.sh를 먼저 실행하세요")
        return
    rep.check(True, f"{p} 파일 존재")

    with pdfplumber.open(pdf_path) as pdf:
        # 실제 체성분 결과지는 1페이지입니다. 레이아웃이 넘치면 조용히 2페이지가 되므로
        # 여기서 막습니다. (넘친 페이지는 거의 비어 있어 결과지로서 부적합)
        rep.check(
            len(pdf.pages) == 1,
            f"{p} 1페이지로 수납",
            f"{len(pdf.pages)}페이지 — 레이아웃이 넘쳤습니다",
        )
        text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)

    if d["source_format"] == "scanned_image":
        # 스캔본은 텍스트 레이어가 없어야 함 (비전 폴백 경로 검증의 근거)
        rep.check(
            len(text.strip()) == 0,
            f"{p} 스캔본 텍스트 레이어 없음",
            f"{len(text.strip())}자가 추출됨 — 이미지 전용이 아닙니다",
        )
        return

    # 디지털 출력본은 핵심 값이 텍스트로 추출되어야 함
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
        f"{p} 정답 값 {len(expected)}개 텍스트 추출",
        f"누락: {missing}",
    )
    # 4개 섹션 제목이 모두 있는지
    sections = ["체성분 분석", "골격근·지방 분석", "비만 분석", "부위별 근육 분석"]
    missing_s = [s for s in sections if s not in text]
    rep.check(not missing_s, f"{p} 4개 섹션 제목 존재", f"누락: {missing_s}")
    # 합성 데이터 면책이 들어 있는지
    rep.check("합성 데이터" in text, f"{p} 합성 데이터 면책 문구 존재")


def main() -> int:
    rep = Report()
    docs = {}

    files = sorted(GT_DIR.glob("*.json"))
    if not files:
        print("ground-truth JSON을 찾을 수 없습니다.", file=sys.stderr)
        return 1

    print("=" * 68)
    print("  체성분 결과지 샘플 검증")
    print("=" * 68)

    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        docs[d["document_id"]] = d
        verify_arithmetic(d, rep)
        verify_pdf(d, rep)

    verify_trend(docs, rep)

    print(f"\n  문서 {len(docs)}건 / 검사 {rep.passed + len(rep.failures)}건")
    print(f"  통과 {rep.passed}건 · 실패 {len(rep.failures)}건")

    if rep.failures:
        print("\n  실패 목록:")
        for fail in rep.failures:
            print(f"    X {fail}")
        print()
        return 1

    print("\n  전 항목 통과\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
