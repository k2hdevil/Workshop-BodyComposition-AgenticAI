#!/usr/bin/env python3
"""
체성분 분석 결과지 렌더러 (Ground Truth JSON -> HTML)

정답 JSON을 단일 원본으로 삼아 결과지 HTML을 생성합니다.
PDF와 정답 데이터가 어긋날 수 없도록, 사람이 같은 값을 두 번 입력하는 지점을 없앤 구조입니다.

사용법:
    uv run python render_sheet.py <ground-truth.json> <출력.html>
"""

import json
import sys
from pathlib import Path

FLAG_LABEL = {
    "LOW": "표준이하",
    "NORMAL": "표준",
    "HIGH": "표준이상",
    "BELOW": "표준이하",
    "ABOVE": "표준이상",
}
FLAG_CLASS = {
    "LOW": "f-low",
    "NORMAL": "f-normal",
    "HIGH": "f-high",
    "BELOW": "f-low",
    "ABOVE": "f-high",
}

# ──────────────────────────────────────────────
# 그래프 눈금
#
# 눈금 레이블은 균등 폭 셀의 오른쪽 끝에 표시되므로, i번째 레이블의 위치는 i/n 입니다.
# 막대 길이는 값/최대값으로 계산되므로, 둘이 일치하려면 눈금 값이
#     v(i) = 최대값 × i / n
# 즉 최대값/n 부터 최대값까지 등간격이어야 합니다.
# 이 조건을 깨면 눈금과 막대가 어긋납니다.
# ──────────────────────────────────────────────
def linear_ticks(vmax, n):
    """등간격 눈금 값 생성. 막대 위치와 정확히 일치함이 보장됩니다."""
    step = vmax / n
    return [step * i for i in range(1, n + 1)]


MFA_MAX = 200  # 골격근·지방 분석 (표준 대비 %)
MFA_TICKS = linear_ticks(MFA_MAX, 8)  # 25 50 75 100 125 150 175 200

BMI_MAX = 40
BMI_TICKS = linear_ticks(BMI_MAX, 8)  # 5 10 15 20 25 30 35 40

PBF_MAX = 50
PBF_TICKS = linear_ticks(PBF_MAX, 5)  # 10 20 30 40 50

SEG_MAX = 160  # 부위별 근육 분석 (표준 대비 %)

# 막대가 이 비율을 넘으면 수치 레이블을 막대 안쪽에 흰 글자로 표시
NUM_INSIDE_THRESHOLD = 72.0

CSS = """
@page { size: A4 portrait; margin: 10mm 9mm; }
* { box-sizing: border-box; }
body {
  font-family: 'Apple SD Gothic Neo', 'AppleGothic', 'Malgun Gothic', sans-serif;
  color: #1a1a1a; margin: 0; font-size: 8.6pt; line-height: 1.35;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
.head { border-bottom: 2.5px solid #14417a; padding-bottom: 4px; margin-bottom: 6px;
        display: flex; align-items: flex-end; justify-content: space-between; }
.head .t1 { font-size: 14pt; font-weight: 700; color: #14417a; letter-spacing: -0.4px; }
.head .t2 { font-size: 7.8pt; color: #5a6b80; margin-top: 1px; }
.synth { border: 1px solid #c0392b; color: #c0392b; font-size: 7pt; font-weight: 700;
         padding: 3px 7px; border-radius: 3px; white-space: nowrap; text-align: center; }

table.subj { width: 100%; border-collapse: collapse; margin-bottom: 6px; font-size: 8.2pt; }
table.subj th { background: #eef2f7; color: #14417a; font-weight: 700; text-align: left;
                padding: 2.5px 7px; border: 1px solid #c9d4e2; width: 9%; white-space: nowrap; }
table.subj td { padding: 2.5px 7px; border: 1px solid #c9d4e2; width: 16%; }

section { margin-bottom: 6px; break-inside: avoid; }
h2 { font-size: 9.8pt; font-weight: 700; color: #fff; background: #14417a;
     margin: 0 0 4px 0; padding: 2.5px 9px; border-radius: 2px; }
h2 .en { font-size: 7.6pt; font-weight: 400; color: #b9cbe3; margin-left: 6px; }

table.data { width: 100%; border-collapse: collapse; font-size: 8.2pt; }
table.data thead th { background: #e9eef5; color: #24405f; font-weight: 700;
                      padding: 2.5px 5px; border: 1px solid #c9d4e2; text-align: center; }
table.data td { padding: 2px 5px; border: 1px solid #d6dee8; text-align: center; }
table.data td.name { text-align: left; font-weight: 600; }
table.data td.val  { text-align: right; font-weight: 700; font-variant-numeric: tabular-nums; }
table.data td.rng  { text-align: center; color: #4a5a6e; font-variant-numeric: tabular-nums; }
table.data tr.sum td { background: #f6f8fb; font-weight: 700; }

.f-low    { color: #1257a8; font-weight: 700; }
.f-normal { color: #1a7f42; font-weight: 700; }
.f-high   { color: #c0392b; font-weight: 700; }

.track { position: relative; height: 10px; background: #f0f3f7;
         border: 1px solid #d6dee8; border-radius: 1px; }
.band  { position: absolute; top: 0; bottom: 0; background: #dbe7d8; }
.fill  { position: absolute; top: 1px; bottom: 1px; left: 0; border-radius: 1px; }
.fill.f-low    { background: #3b82c4; }
.fill.f-normal { background: #35a35f; }
.fill.f-high   { background: #d9534f; }
.mark { position: absolute; top: -1px; bottom: -1px; width: 1px; background: #8f9fb2; }

.mfa { position: relative; border: 1px solid #c9d4e2; }
.mfa .scale { display: flex; background: #e9eef5; border-bottom: 1px solid #c9d4e2;
              font-size: 6.4pt; color: #46586e; }
.mfa .scale div { flex: 1; text-align: right; padding: 2px 2px 1px 0;
                  border-left: 1px solid #d6dee8; }
/* overflow:hidden 은 체형 연결선(SVG)이 그래프 밖으로 새는 것을 막는 안전장치 */
.mfa .rows { position: relative; overflow: hidden; }
.mfa .row { display: flex; align-items: center; height: 25px;
            border-bottom: 1px solid #e6ebf1; }
.mfa .row:last-child { border-bottom: none; }
.mfa .lbl { width: 104px; flex: 0 0 104px; padding: 0 7px; font-size: 8pt; font-weight: 600;
            border-right: 1px solid #c9d4e2; }
.mfa .lbl .u { font-weight: 400; color: #6b7b8f; font-size: 7pt; }
.mfa .barwrap { position: relative; flex: 1; height: 100%; }
.mfa .bar { position: absolute; top: 5px; height: 14px; left: 0; }
.mfa .bar.f-low    { background: #3b82c4; }
.mfa .bar.f-normal { background: #35a35f; }
.mfa .bar.f-high   { background: #d9534f; }
.mfa .num { position: absolute; top: 6px; font-size: 7.8pt; font-weight: 700;
            color: #24405f; white-space: nowrap; padding-left: 4px;
            font-variant-numeric: tabular-nums; }
/* 막대가 길어 레이블이 밖으로 밀릴 때는 막대 안쪽에 흰 글자로 표시 */
.mfa .num.inside { padding-left: 0; padding-right: 6px; color: #fff; }
.mfa .g100 { position: absolute; top: 0; bottom: 0; width: 1.5px; background: #14417a; }
.mfa .gtick { position: absolute; top: 0; bottom: 0; width: 1px; background: #eaeef3; }
.mfa .stdband { position: absolute; top: 0; bottom: 0; background: rgba(53,163,95,0.08); }
/* left 와 right 를 함께 지정하면 SVG(대체 요소)의 폭이 고유 크기 300px로 고정되어
   막대 영역과 어긋납니다. width 를 명시적으로 계산해 주어야 합니다. */
.mfa svg.link { position: absolute; top: 0; left: 104px; width: calc(100% - 104px); }
/* 눈금선·표준범위 밴드는 라벨 열을 제외한 막대 영역 기준으로 배치해야 합니다.
   .rows 에 직접 %를 주면 라벨 열 폭까지 포함되어 눈금과 막대가 어긋납니다. */
.mfa .guides { position: absolute; top: 0; bottom: 0; left: 104px; right: 0; }

.bodytype { margin-top: 4px; border: 1px solid #c9d4e2; background: #f6f8fb; padding: 4px 9px; }
.bodytype .h { font-size: 9.4pt; font-weight: 700; color: #14417a; }
.bodytype .h b { font-size: 11.5pt; color: #c0392b; margin: 0 3px; }
.bodytype .d { font-size: 8pt; color: #33475e; margin-top: 2px; }
.bodytype .caution { font-size: 8pt; color: #a8321f; margin-top: 3px;
                     border-top: 1px dashed #d8c2be; padding-top: 3px; }

.cols { display: flex; gap: 8px; }
.cols > * { flex: 1; }

table.kv { width: 100%; border-collapse: collapse; font-size: 8.2pt; }
table.kv th { background: #eef2f7; color: #24405f; text-align: left; font-weight: 600;
              padding: 2px 7px; border: 1px solid #c9d4e2; white-space: nowrap; }
table.kv td { padding: 2px 7px; border: 1px solid #d6dee8; text-align: right;
              font-weight: 700; font-variant-numeric: tabular-nums; }
table.kv td .sub { font-weight: 400; color: #6b7b8f; font-size: 7.2pt; }

.note { margin-top: 3px; font-size: 7.8pt; color: #33475e;
        border: 1px solid #d6dee8; background: #f9fafc; padding: 4px 8px; }
.note b { color: #14417a; }

footer { margin-top: 6px; border-top: 1px solid #c9d4e2; padding-top: 3px;
         font-size: 6.8pt; color: #6b7b8f; line-height: 1.5; }
footer .warn { color: #a8321f; font-weight: 700; }
"""


def fmt(v, nd=1):
    """숫자를 고정 소수점 문자열로. int는 소수점 없이."""
    if isinstance(v, int):
        return str(v)
    return f"{v:.{nd}f}"


def clamp_pct(x, scale_max):
    """값을 그래프 폭 대비 백분율(0~100)로 변환. 상한 클램프."""
    return max(0.0, min(float(x), scale_max)) / scale_max * 100.0


def inline_bar(item):
    """체성분 표 안의 인라인 막대. 표준범위 밴드 + 실측 막대."""
    lo, hi = item["std_low"], item["std_high"]
    smax = max(hi * 1.6, item["value"] * 1.12)
    band_l, band_w = lo / smax * 100, (hi - lo) / smax * 100
    fill_w = clamp_pct(item["value"], smax)
    return (
        f'<div class="track">'
        f'<div class="band" style="left:{band_l:.2f}%;width:{band_w:.2f}%"></div>'
        f'<div class="fill {FLAG_CLASS[item["flag"]]}" style="width:{fill_w:.2f}%"></div>'
        f'<div class="mark" style="left:{band_l:.2f}%"></div>'
        f'<div class="mark" style="left:{band_l + band_w:.2f}%"></div>'
        f"</div>"
    )


def bca_row(item):
    # 측정값과 표준범위의 소수 자리수를 맞춥니다 (예: 4.00 과 3.53~4.31)
    nd = 1 if item["value"] >= 10 else 2
    return (
        f'<tr><td class="name">{item["label_ko"]}</td>'
        f'<td class="val">{fmt(item["value"], nd)}</td>'
        f'<td class="rng">{fmt(item["std_low"], nd)} ~ {fmt(item["std_high"], nd)}</td>'
        f'<td class="{FLAG_CLASS[item["flag"]]}">{FLAG_LABEL[item["flag"]]}</td>'
        f"<td>{inline_bar(item)}</td></tr>"
    )


def seg_row(item):
    fill_w = clamp_pct(item["percent_of_standard"], SEG_MAX)
    band_l = 95 / SEG_MAX * 100
    band_w = 10 / SEG_MAX * 100
    bar = (
        f'<div class="track">'
        f'<div class="band" style="left:{band_l:.2f}%;width:{band_w:.2f}%"></div>'
        f'<div class="fill {FLAG_CLASS[item["flag"]]}" style="width:{fill_w:.2f}%"></div>'
        f'<div class="mark" style="left:{100 / SEG_MAX * 100:.2f}%"></div>'
        f"</div>"
    )
    return (
        f'<tr><td class="name">{item["label_ko"]}</td>'
        f'<td class="val">{fmt(item["mass_kg"], 2)}</td>'
        f'<td class="rng">{fmt(item["std_kg"], 2)}</td>'
        f'<td class="val">{fmt(item["percent_of_standard"], 1)}</td>'
        f'<td class="{FLAG_CLASS[item["flag"]]}">{FLAG_LABEL[item["flag"]]}</td>'
        f"<td>{bar}</td></tr>"
    )


def tick_label(t):
    """눈금 값 표시. 정수면 소수점 없이."""
    return str(int(t)) if float(t).is_integer() else f"{t:.1f}"


def scale_row(head, ticks):
    """눈금 행. 첫 칸은 라벨 열 폭을 맞추기 위한 자리이며, 나머지는 균등 폭 셀입니다."""
    cells = "".join(f"<div>{tick_label(t)}</div>" for t in ticks)
    return (
        f'<div class="scale"><div style="flex:0 0 104px;border-left:none;'
        f'text-align:left;padding-left:7px">{head}</div>{cells}</div>'
    )


def num_span(text, w):
    """수치 레이블. 막대가 길면 막대 안쪽 흰 글자로 붙여 화면 밖으로 밀리지 않게 합니다."""
    if w > NUM_INSIDE_THRESHOLD:
        return f'<div class="num inside" style="right:{100 - w:.2f}%">{text}</div>'
    return f'<div class="num" style="left:{w:.2f}%">{text}</div>'


ROW_H = 25  # .mfa .row 높이(px). SVG 높이를 명시하는 데 사용


def mfa_graph(mfa):
    """골격근·지방 분석 그래프. 3개 막대 끝점을 연결해 체형(C/I/D)을 시각화."""
    rows = [
        ("체중", "Weight", mfa["weight_kg"]),
        ("골격근량", "SMM", mfa["skeletal_muscle_mass_kg"]),
        ("체지방량", "BFM", mfa["body_fat_mass_kg"]),
    ]

    # 표준범위 밴드(90~110%) + 눈금선 + 100% 기준선
    guides = [
        f'<div class="stdband" style="left:{90 / MFA_MAX * 100:.2f}%;'
        f'width:{20 / MFA_MAX * 100:.2f}%"></div>'
    ]
    for t in MFA_TICKS:
        cls = "g100" if t == 100 else "gtick"
        guides.append(f'<div class="{cls}" style="left:{t / MFA_MAX * 100:.2f}%"></div>')

    row_html, points = [], []
    n = len(rows)
    for i, (ko, en, item) in enumerate(rows):
        p = item["percent_of_standard"]
        w = clamp_pct(p, MFA_MAX)
        arrow = "▶ " if p > MFA_MAX else ""
        label = f'{arrow}{fmt(item["value"], 1)} kg ({fmt(p, 1)}%)'
        row_html.append(
            f'<div class="row">'
            f'<div class="lbl">{ko}<span class="u"> {en}</span></div>'
            f'<div class="barwrap">'
            f'<div class="bar {FLAG_CLASS[item["flag"]]}" style="width:{w:.2f}%"></div>'
            f"{num_span(label, w)}"
            f"</div></div>"
        )
        points.append(f"{w:.2f},{(i + 0.5) / n * 100:.2f}")

    # 높이를 명시하지 않으면 SVG가 대체 요소 기본 크기로 늘어나 그래프 밖으로 새어 나갑니다.
    polyline = (
        f'<svg class="link" style="height:{ROW_H * n}px" '
        f'viewBox="0 0 100 100" preserveAspectRatio="none">'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="#c0392b" '
        f'stroke-width="0.6" vector-effect="non-scaling-stroke" '
        f'stroke-dasharray="2.5,1.5"/></svg>'
    )
    return (
        f'<div class="mfa">'
        f"{scale_row('표준 대비 (%)', MFA_TICKS)}"
        f'<div class="rows">'
        f'<div class="guides">{"".join(guides)}</div>'
        f'{"".join(row_html)}{polyline}'
        f"</div></div>"
    )


def obesity_bar(item, ticks, vmax):
    """비만 분석 막대. BMI/PBF는 절대값 눈금을 사용."""
    unit = item["unit"]
    band_l = item["std_low"] / vmax * 100
    band_w = (item["std_high"] - item["std_low"]) / vmax * 100
    w = clamp_pct(item["value"], vmax)

    if w > NUM_INSIDE_THRESHOLD:
        # 막대 안쪽은 흰 글자이므로 판정 색상 span을 빼고 텍스트만 둡니다.
        label = f'{fmt(item["value"], 1)} {unit} &nbsp;{FLAG_LABEL[item["flag"]]}'
    else:
        label = (
            f'{fmt(item["value"], 1)} {unit}&nbsp; '
            f'<span class="{FLAG_CLASS[item["flag"]]}">{FLAG_LABEL[item["flag"]]}</span>'
        )

    guides = (
        f'<div class="stdband" style="left:{band_l:.2f}%;width:{band_w:.2f}%"></div>'
        + "".join(f'<div class="gtick" style="left:{t / vmax * 100:.2f}%"></div>' for t in ticks)
    )
    return (
        f'<div class="mfa" style="margin-bottom:5px">'
        f"{scale_row(f'단위 {unit}', ticks)}"
        f'<div class="rows">'
        f'<div class="guides">{guides}</div>'
        f'<div class="row" style="height:23px">'
        f'<div class="lbl">{item["label_ko"]}<span class="u"> {unit}</span></div>'
        f'<div class="barwrap">'
        f'<div class="bar {FLAG_CLASS[item["flag"]]}" style="width:{w:.2f}%"></div>'
        f"{num_span(label, w)}"
        f"</div></div></div></div>"
    )


def render(d):
    s, m, r = d["subject"], d["measurement"], d["reference"]
    bca, mfa = d["body_composition_analysis"], d["muscle_fat_analysis"]
    ob, seg = d["obesity_analysis"], d["segmental_lean_analysis"]
    add, cg = d["additional_metrics"], d["control_guide"]

    sex_ko = "남성" if s["sex"] == "M" else "여성"
    measured = m["measured_at"][:16].replace("T", " ")
    ecw = bca["ecw_tbw_ratio"]

    # 1. 체성분 분석
    s1_rows = "".join(
        bca_row(bca[k])
        for k in ("total_body_water_kg", "protein_kg", "minerals_kg", "body_fat_mass_kg")
    )
    s1 = f"""
<section>
  <h2>1. 체성분 분석<span class="en">Body Composition Analysis</span></h2>
  <table class="data">
    <thead><tr><th style="width:14%">항목</th><th style="width:11%">측정값 (kg)</th>
      <th style="width:16%">표준범위 (kg)</th><th style="width:11%">판정</th><th>그래프</th></tr></thead>
    <tbody>
      {s1_rows}
      <tr class="sum"><td class="name">제지방량 (FFM)</td>
        <td class="val">{fmt(bca["fat_free_mass_kg"])}</td>
        <td class="rng" colspan="3" style="text-align:left">체수분 + 단백질 + 무기질
          = {fmt(bca["total_body_water_kg"]["value"])} + {fmt(bca["protein_kg"]["value"])}
          + {fmt(bca["minerals_kg"]["value"])}</td></tr>
      <tr class="sum"><td class="name">체중 (Weight)</td>
        <td class="val">{fmt(bca["weight_kg"])}</td>
        <td class="rng" colspan="3" style="text-align:left">제지방량 + 체지방량
          = {fmt(bca["fat_free_mass_kg"])} + {fmt(bca["body_fat_mass_kg"]["value"])}</td></tr>
    </tbody>
  </table>
  <div class="note">
    <b>체수분 상세</b> &nbsp; 세포내수분 {fmt(bca["intracellular_water_kg"])} kg &nbsp;/&nbsp;
    세포외수분 {fmt(bca["extracellular_water_kg"])} kg &nbsp;/&nbsp;
    세포외수분비 {ecw["value"]:.3f}
    (표준 {ecw["std_low"]:.3f} ~ {ecw["std_high"]:.3f},
     <span class="{FLAG_CLASS[ecw["flag"]]}">{FLAG_LABEL[ecw["flag"]]}</span>)
  </div>
</section>"""

    # 2. 골격근·지방 분석
    caution = (
        f'<div class="caution">해석 주의 — {mfa["interpretation_caution_ko"]}</div>'
        if mfa.get("interpretation_caution_ko")
        else ""
    )
    s2 = f"""
<section>
  <h2>2. 골격근·지방 분석<span class="en">Muscle-Fat Analysis</span></h2>
  {mfa_graph(mfa)}
  <div class="bodytype">
    <div class="h">체형 판정 &nbsp;<b>{mfa["body_type_label_ko"]}</b>
      <span style="font-size:7.8pt;font-weight:400;color:#6b7b8f">
      (막대 끝점 연결 형태 · 표준체중 {fmt(r["standard_weight_kg"])} kg 기준)</span></div>
    <div class="d">{mfa["body_type_description_ko"]}</div>
    {caution}
  </div>
</section>"""

    # 3. 비만 분석
    s3 = f"""
<section>
  <h2>3. 비만 분석<span class="en">Obesity Analysis</span></h2>
  {obesity_bar(ob["bmi"], BMI_TICKS, BMI_MAX)}
  {obesity_bar(ob["pbf_percent"], PBF_TICKS, PBF_MAX)}
  <div class="note">
    <b>BMI (체질량지수)</b> 키와 체중만으로 산출하는 겉보기 비만도 지표 →
    {fmt(ob["bmi"]["value"])} kg/m&sup2;, <b>{ob["bmi_class_ko"]}</b>
    <span style="color:#6b7b8f">({ob["bmi_class_basis"]})</span><br>
    <b>PBF (체지방률)</b> 체중에서 체지방이 차지하는 실제 비율 →
    {fmt(ob["pbf_percent"]["value"])} %,
    {sex_ko} 표준 {fmt(r["pbf_standard_low"])} ~ {fmt(r["pbf_standard_high"])} %
  </div>
</section>"""

    # 4. 부위별 근육 분석
    seg_rows = "".join(
        seg_row(seg[k]) for k in ("right_arm", "left_arm", "trunk", "right_leg", "left_leg")
    )
    bal = seg["balance"]
    s4 = f"""
<section>
  <h2>4. 부위별 근육 분석<span class="en">Segmental Lean Analysis</span></h2>
  <table class="data">
    <thead><tr><th style="width:14%">부위</th><th style="width:12%">근육량 (kg)</th>
      <th style="width:12%">표준 (kg)</th><th style="width:12%">표준대비 (%)</th>
      <th style="width:11%">판정</th><th>그래프</th></tr></thead>
    <tbody>{seg_rows}</tbody>
  </table>
  <div class="note">
    <b>좌우 균형</b> 상지 편차 {fmt(bal["upper_limb_asymmetry_percent"])} % /
    하지 편차 {fmt(bal["lower_limb_asymmetry_percent"])} % → {bal["left_right_balance_ko"]}<br>
    <b>상하 균형</b> {bal["upper_lower_balance_ko"]}
  </div>
</section>"""

    # 5. 부가 지표 + 체중 조절 가이드
    whr, vfl = add["waist_hip_ratio"], add["visceral_fat_level"]
    bmr, score = add["basal_metabolic_rate_kcal"], add["body_composition_score"]
    s5 = f"""
<section class="cols">
  <div>
    <h2>부가 지표<span class="en">Additional Metrics</span></h2>
    <table class="kv">
      <tr><th>{whr["label_ko"]} (WHR)</th><td>{whr["value"]:.2f}
        <span class="{FLAG_CLASS[whr["flag"]]}">{FLAG_LABEL[whr["flag"]]}</span>
        <span class="sub">표준 {whr["std_low"]:.2f}~{whr["std_high"]:.2f}</span></td></tr>
      <tr><th>{vfl["label_ko"]}</th><td>{vfl["value"]}
        <span class="{FLAG_CLASS[vfl["flag"]]}">{FLAG_LABEL[vfl["flag"]]}</span>
        <span class="sub">표준 {vfl["std_low"]}~{vfl["std_high"]}</span></td></tr>
      <tr><th>{bmr["label_ko"]}</th><td>{bmr["value"]:,} kcal
        <span class="sub">{bmr["formula"]}</span></td></tr>
      <tr><th>{score["label_ko"]}</th><td>{score["value"]} / {score["max"]}
        <span class="sub">표준 {score["standard"]}점</span></td></tr>
    </table>
  </div>
  <div>
    <h2>체중 조절 가이드<span class="en">Weight Control</span></h2>
    <table class="kv">
      <tr><th>적정체중</th><td>{fmt(cg["target_weight_kg"])} kg
        <span class="sub">{cg["target_weight_basis"]}</span></td></tr>
      <tr><th>체중조절</th><td>{cg["weight_control_kg"]:+.1f} kg</td></tr>
      <tr><th>근육조절</th><td>{cg["muscle_control_kg"]:+.1f} kg</td></tr>
      <tr><th>지방조절</th><td>{cg["fat_control_kg"]:+.1f} kg</td></tr>
    </table>
  </div>
</section>"""

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>체성분 분석 결과지 — {d["document_id"]}</title>
<style>{CSS}</style>
</head>
<body>
<div class="head">
  <div>
    <div class="t1">체성분 분석 결과지</div>
    <div class="t2">Body Composition Analysis Report &nbsp;·&nbsp;
      문서번호 {d["document_id"].upper()} &nbsp;·&nbsp; {m["session_seq"]}회차</div>
  </div>
  <div class="synth">합성 데이터 · 교육/테스트 전용<br>SYNTHETIC — NOT A REAL MEASUREMENT</div>
</div>

<table class="subj">
  <tr>
    <th>성명</th><td>{s["name"]}</td>
    <th>나이</th><td>{s["age"]} 세</td>
    <th>성별</th><td>{sex_ko}</td>
    <th>신장</th><td>{fmt(s["height_cm"])} cm</td>
  </tr>
  <tr>
    <th>측정일시</th><td>{measured}</td>
    <th>측정기기</th><td>{m["device_model"]}</td>
    <th>측정방식</th><td colspan="3">{m["method"]}</td>
  </tr>
</table>

{s1}
{s2}
{s3}
{s4}
{s5}

<footer>
  <span class="warn">본 결과지는 실제 측정 결과가 아닌 가상의 합성 데이터입니다.</span>
  교육 및 소프트웨어 테스트 목적으로만 사용하며, 실제 인물·기관·측정기기와 무관합니다.
  기재된 성명은 가명이고 측정기기명은 가상의 모델명입니다.<br>
  체성분 분석 결과는 건강 상태 참고용 정보이며 의학적 진단이 아닙니다.
  정확한 진단과 치료는 의료 전문가와 상담하시기 바랍니다.
  &nbsp;·&nbsp; 표준범위는 신장 기준 표준체중에서 산출한 참고값입니다.
</footer>
</body>
</html>
"""


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    data = json.loads(src.read_text(encoding="utf-8"))
    dst.write_text(render(data), encoding="utf-8")
    print(f"  렌더링  {src.name} -> {dst.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
