#!/usr/bin/env python3
"""
Body composition analysis sheet renderer (ground-truth JSON -> HTML)

Generates the result sheet HTML with the ground-truth JSON as the single source of truth.
No one types the same value twice, so the PDF and the ground-truth data cannot drift apart.

Usage:
    uv run python render_sheet.py <ground-truth.json> <output.html>
"""

import json
import sys
from pathlib import Path

FLAG_LABEL = {
    "LOW": "Low",
    "NORMAL": "Normal",
    "HIGH": "High",
    "BELOW": "Low",
    "ABOVE": "High",
}
FLAG_CLASS = {
    "LOW": "f-low",
    "NORMAL": "f-normal",
    "HIGH": "f-high",
    "BELOW": "f-low",
    "ABOVE": "f-high",
}

# ──────────────────────────────────────────────
# Graph ticks
#
# A tick label sits at the right edge of an equal-width cell, so the i-th label is at i/n.
# A bar length is value/max, so for the two to agree the tick values must be
#     v(i) = max × i / n
# that is, evenly spaced from max/n up to max.
# If this condition breaks, the ticks and the bars no longer line up.
# ──────────────────────────────────────────────
def linear_ticks(vmax, n):
    """Generate evenly spaced tick values. They are guaranteed to match the bar positions."""
    step = vmax / n
    return [step * i for i in range(1, n + 1)]


MFA_MAX = 200  # Muscle-fat analysis (% of standard)
MFA_TICKS = linear_ticks(MFA_MAX, 8)  # 25 50 75 100 125 150 175 200

BMI_MAX = 40
BMI_TICKS = linear_ticks(BMI_MAX, 8)  # 5 10 15 20 25 30 35 40

PBF_MAX = 50
PBF_TICKS = linear_ticks(PBF_MAX, 5)  # 10 20 30 40 50

SEG_MAX = 160  # Segmental lean analysis (% of standard)

# When a bar is longer than this ratio, draw the value label inside the bar in white
NUM_INSIDE_THRESHOLD = 72.0

CSS = """
@page { size: A4 portrait; margin: 8mm 9mm; }
* { box-sizing: border-box; }
body {
  font-family: 'Helvetica Neue', Helvetica, Arial, 'Segoe UI', sans-serif;
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
/* overflow:hidden is a safeguard that keeps the body-type connector line (SVG) from leaking outside the graph */
.mfa .rows { position: relative; overflow: hidden; }
.mfa .row { display: flex; align-items: center; height: 25px;
            border-bottom: 1px solid #e6ebf1; }
.mfa .row:last-child { border-bottom: none; }
.mfa .lbl { width: 140px; flex: 0 0 140px; padding: 0 7px; font-size: 8pt; font-weight: 600;
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
/* When a long bar pushes the label out, draw it inside the bar in white */
.mfa .num.inside { padding-left: 0; padding-right: 6px; color: #fff; }
.mfa .g100 { position: absolute; top: 0; bottom: 0; width: 1.5px; background: #14417a; }
.mfa .gtick { position: absolute; top: 0; bottom: 0; width: 1px; background: #eaeef3; }
.mfa .stdband { position: absolute; top: 0; bottom: 0; background: rgba(53,163,95,0.08); }
/* If left and right are both set, the width of the SVG (a replaced element) is fixed at its
   intrinsic 300px and no longer matches the bar area. Set width explicitly. */
.mfa svg.link { position: absolute; top: 0; left: 140px; width: calc(100% - 140px); }
/* Tick lines and the standard-range band must be positioned against the bar area, excluding the label column.
   A % applied directly to .rows would include the label column width and misalign ticks and bars. */
.mfa .guides { position: absolute; top: 0; bottom: 0; left: 140px; right: 0; }

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
    """Format a number with fixed decimals. An int is printed without a decimal point."""
    if isinstance(v, int):
        return str(v)
    return f"{v:.{nd}f}"


def clamp_pct(x, scale_max):
    """Convert a value to a percentage (0-100) of the graph width, clamped at the upper limit."""
    return max(0.0, min(float(x), scale_max)) / scale_max * 100.0


def inline_bar(item):
    """Inline bar inside the body composition table: standard-range band + measured bar."""
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
    # Match the decimal places of the measured value and the standard range (e.g. 4.00 and 3.53~4.31)
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
    """Show a tick value. An integer is printed without a decimal point."""
    return str(int(t)) if float(t).is_integer() else f"{t:.1f}"


def scale_row(head, ticks):
    """Tick row. The first cell only reserves the label column width; the rest are equal-width cells."""
    cells = "".join(f"<div>{tick_label(t)}</div>" for t in ticks)
    return (
        f'<div class="scale"><div style="flex:0 0 140px;border-left:none;'
        f'text-align:left;padding-left:7px">{head}</div>{cells}</div>'
    )


def num_span(text, w):
    """Value label. For a long bar, put it inside the bar in white so it is not pushed off the graph."""
    if w > NUM_INSIDE_THRESHOLD:
        return f'<div class="num inside" style="right:{100 - w:.2f}%">{text}</div>'
    return f'<div class="num" style="left:{w:.2f}%">{text}</div>'


ROW_H = 25  # Height of .mfa .row in px. Used to set the SVG height explicitly


def mfa_graph(mfa):
    """Muscle-fat analysis graph. Connects the ends of the 3 bars to show the body type (C/I/D)."""
    rows = [
        ("Weight", "WT", mfa["weight_kg"]),
        ("Skeletal Muscle", "SMM", mfa["skeletal_muscle_mass_kg"]),
        ("Body Fat Mass", "BFM", mfa["body_fat_mass_kg"]),
    ]

    # Standard-range band (90~110%) + tick lines + 100% reference line
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

    # Without an explicit height the SVG grows to the default size of a replaced element and leaks out of the graph.
    polyline = (
        f'<svg class="link" style="height:{ROW_H * n}px" '
        f'viewBox="0 0 100 100" preserveAspectRatio="none">'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="#c0392b" '
        f'stroke-width="0.6" vector-effect="non-scaling-stroke" '
        f'stroke-dasharray="2.5,1.5"/></svg>'
    )
    return (
        f'<div class="mfa">'
        f"{scale_row('% of Standard', MFA_TICKS)}"
        f'<div class="rows">'
        f'<div class="guides">{"".join(guides)}</div>'
        f'{"".join(row_html)}{polyline}'
        f"</div></div>"
    )


def obesity_bar(item, ticks, vmax):
    """Obesity analysis bar. BMI/PBF use an absolute-value scale."""
    unit = item["unit"]
    band_l = item["std_low"] / vmax * 100
    band_w = (item["std_high"] - item["std_low"]) / vmax * 100
    w = clamp_pct(item["value"], vmax)

    if w > NUM_INSIDE_THRESHOLD:
        # Inside the bar the text is white, so omit the status-color span and keep plain text.
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
        f"{scale_row(f'Unit {unit}', ticks)}"
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

    sex_en = "Male" if s["sex"] == "M" else "Female"
    measured = m["measured_at"][:16].replace("T", " ")
    ecw = bca["ecw_tbw_ratio"]

    # 1. Body Composition Analysis
    s1_rows = "".join(
        bca_row(bca[k])
        for k in ("total_body_water_kg", "protein_kg", "minerals_kg", "body_fat_mass_kg")
    )
    s1 = f"""
<section>
  <h2>1. Body Composition Analysis</h2>
  <table class="data">
    <thead><tr><th style="width:17%">Item</th><th style="width:14%">Measured (kg)</th>
      <th style="width:19%">Standard Range (kg)</th><th style="width:9%">Status</th><th>Graph</th></tr></thead>
    <tbody>
      {s1_rows}
      <tr class="sum"><td class="name">Fat-Free Mass (FFM)</td>
        <td class="val">{fmt(bca["fat_free_mass_kg"])}</td>
        <td class="rng" colspan="3" style="text-align:left">Total Body Water + Protein + Minerals
          = {fmt(bca["total_body_water_kg"]["value"])} + {fmt(bca["protein_kg"]["value"])}
          + {fmt(bca["minerals_kg"]["value"])}</td></tr>
      <tr class="sum"><td class="name">Weight</td>
        <td class="val">{fmt(bca["weight_kg"])}</td>
        <td class="rng" colspan="3" style="text-align:left">Fat-Free Mass + Body Fat Mass
          = {fmt(bca["fat_free_mass_kg"])} + {fmt(bca["body_fat_mass_kg"]["value"])}</td></tr>
    </tbody>
  </table>
  <div class="note">
    <b>Body Water Detail</b> &nbsp; Intracellular Water {fmt(bca["intracellular_water_kg"])} kg &nbsp;/&nbsp;
    Extracellular Water {fmt(bca["extracellular_water_kg"])} kg &nbsp;/&nbsp;
    ECW/TBW Ratio {ecw["value"]:.3f}
    (Standard {ecw["std_low"]:.3f} ~ {ecw["std_high"]:.3f},
     <span class="{FLAG_CLASS[ecw["flag"]]}">{FLAG_LABEL[ecw["flag"]]}</span>)
  </div>
</section>"""

    # 2. Muscle-Fat Analysis
    caution = (
        f'<div class="caution">Interpretation note — {mfa["interpretation_caution_ko"]}</div>'
        if mfa.get("interpretation_caution_ko")
        else ""
    )
    s2 = f"""
<section>
  <h2>2. Muscle-Fat Analysis</h2>
  {mfa_graph(mfa)}
  <div class="bodytype">
    <div class="h">Body Type &nbsp;<b>{mfa["body_type_label_ko"]}</b>
      <span style="font-size:7.8pt;font-weight:400;color:#6b7b8f">
      (shape formed by connecting the bar ends · based on standard weight {fmt(r["standard_weight_kg"])} kg)</span></div>
    <div class="d">{mfa["body_type_description_ko"]}</div>
    {caution}
  </div>
</section>"""

    # 3. Obesity Analysis
    s3 = f"""
<section>
  <h2>3. Obesity Analysis</h2>
  {obesity_bar(ob["bmi"], BMI_TICKS, BMI_MAX)}
  {obesity_bar(ob["pbf_percent"], PBF_TICKS, PBF_MAX)}
  <div class="note">
    <b>BMI (Body Mass Index)</b> Apparent obesity index calculated from height and weight only →
    {fmt(ob["bmi"]["value"])} kg/m&sup2;, <b>{ob["bmi_class_ko"]}</b>
    <span style="color:#6b7b8f">({ob["bmi_class_basis"]})</span><br>
    <b>PBF (Percent Body Fat)</b> Actual share of body weight that is fat →
    {fmt(ob["pbf_percent"]["value"])} %,
    {sex_en.lower()} standard {fmt(r["pbf_standard_low"])} ~ {fmt(r["pbf_standard_high"])} %
  </div>
</section>"""

    # 4. Segmental Lean Analysis
    seg_rows = "".join(
        seg_row(seg[k]) for k in ("right_arm", "left_arm", "trunk", "right_leg", "left_leg")
    )
    bal = seg["balance"]
    s4 = f"""
<section>
  <h2>4. Segmental Lean Analysis</h2>
  <table class="data">
    <thead><tr><th style="width:14%">Segment</th><th style="width:13%">Lean Mass (kg)</th>
      <th style="width:12%">Standard (kg)</th><th style="width:13%">% of Standard</th>
      <th style="width:9%">Status</th><th>Graph</th></tr></thead>
    <tbody>{seg_rows}</tbody>
  </table>
  <div class="note">
    <b>Left-Right Balance</b> Upper-limb difference {fmt(bal["upper_limb_asymmetry_percent"])} % /
    Lower-limb difference {fmt(bal["lower_limb_asymmetry_percent"])} % → {bal["left_right_balance_ko"]}<br>
    <b>Upper-Lower Balance</b> {bal["upper_lower_balance_ko"]}
  </div>
</section>"""

    # 5. Additional Metrics + Weight Control Guide
    whr, vfl = add["waist_hip_ratio"], add["visceral_fat_level"]
    bmr, score = add["basal_metabolic_rate_kcal"], add["body_composition_score"]
    s5 = f"""
<section class="cols">
  <div>
    <h2>Additional Metrics</h2>
    <table class="kv">
      <tr><th>{whr["label_ko"]} (WHR)</th><td>{whr["value"]:.2f}
        <span class="{FLAG_CLASS[whr["flag"]]}">{FLAG_LABEL[whr["flag"]]}</span>
        <span class="sub">Standard {whr["std_low"]:.2f}~{whr["std_high"]:.2f}</span></td></tr>
      <tr><th>{vfl["label_ko"]}</th><td>{vfl["value"]}
        <span class="{FLAG_CLASS[vfl["flag"]]}">{FLAG_LABEL[vfl["flag"]]}</span>
        <span class="sub">Standard {vfl["std_low"]}~{vfl["std_high"]}</span></td></tr>
      <tr><th>{bmr["label_ko"]}</th><td>{bmr["value"]:,} kcal
        <span class="sub">{bmr["formula"]}</span></td></tr>
      <tr><th>{score["label_ko"]}</th><td>{score["value"]} / {score["max"]}
        <span class="sub">Standard {score["standard"]}</span></td></tr>
    </table>
  </div>
  <div>
    <h2>Weight Control Guide</h2>
    <table class="kv">
      <tr><th>Target Weight</th><td>{fmt(cg["target_weight_kg"])} kg
        <span class="sub">{cg["target_weight_basis"]}</span></td></tr>
      <tr><th>Weight Change</th><td>{cg["weight_control_kg"]:+.1f} kg</td></tr>
      <tr><th>Muscle Change</th><td>{cg["muscle_control_kg"]:+.1f} kg</td></tr>
      <tr><th>Fat Change</th><td>{cg["fat_control_kg"]:+.1f} kg</td></tr>
    </table>
  </div>
</section>"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Body Composition Analysis Report — {d["document_id"]}</title>
<style>{CSS}</style>
</head>
<body>
<div class="head">
  <div>
    <div class="t1">Body Composition Analysis Report</div>
    <div class="t2">Document No. {d["document_id"].upper()} &nbsp;·&nbsp; Session {m["session_seq"]}</div>
  </div>
  <div class="synth">SYNTHETIC DATA · FOR EDUCATION/TESTING ONLY<br>NOT A REAL MEASUREMENT</div>
</div>
<table class="subj">
  <tr>
    <th>Name</th><td>{s["name"]}</td>
    <th>Age</th><td>{s["age"]} yrs</td>
    <th>Sex</th><td>{sex_en}</td>
    <th>Height</th><td>{fmt(s["height_cm"])} cm</td>
  </tr>
  <tr>
    <th>Date/Time</th><td>{measured}</td>
    <th>Device</th><td>{m["device_model"]}</td>
    <th>Method</th><td colspan="3">{m["method"]}</td>
  </tr>
</table>

{s1}
{s2}
{s3}
{s4}
{s5}

<footer>
  <span class="warn">This sheet is fictitious synthetic data, not an actual measurement result.</span>
  It is for education and software testing only and is unrelated to any real person,
  organization, or device. The name is a pseudonym and the device name is fictitious.<br>
  Results are for general health reference only, not a medical diagnosis; consult a healthcare professional.
  &nbsp;·&nbsp; Standard ranges are reference values derived from the standard weight for the height.
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
    print(f"  Rendered  {src.name} -> {dst.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
