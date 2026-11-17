# Sample Body Composition Analysis Result Sheets

> **All of this data is fictional synthetic data.**
> It is unrelated to any real person, organization, or measurement device, and is used only for education and software testing.
> The names are pseudonyms, and the device name (`BodyScan Pro 970`) is a fictitious model name.

## Trademark Note

"InBody" is a registered trademark of InBody Co., Ltd. This repository does not use that trademark in the
course material, code, file names, or app name. It uses the generic name **body composition analysis**.
When you handle result sheets from a real manufacturer, note only that the manufacturer's name appears in the device-name field.

---

## Structure

```
sample-data/
├── ground-truth/           Ground truth data (single source of truth, tracked by git)
│   ├── user-a-session-01.json
│   ├── user-a-session-02.json
│   ├── user-a-session-03.json
│   ├── user-a-session-04.json
│   └── user-b-session-01.json
├── pdf/                    Result sheets distributed to participants (tracked by git)
│   └── (5 PDFs with the same names)
├── html/                   Intermediate output (not tracked by git, can be regenerated)
└── tools/
    ├── render_sheet.py     JSON -> HTML result sheet
    ├── make_scan.py        Text PDF -> image-only scanned copy
    ├── build_samples.sh     Full build
    └── verify_samples.py    Arithmetic consistency + PDF comparison check
```

### The JSON is the single source of truth

If the PDF and the ground-truth data are written by hand separately, they will drift apart, and then the
Ground Truth is a bug, not an answer key. In this repository **a person writes only `ground-truth/*.json`**
and the PDFs are rendered from it. To change a value, edit only the JSON and run the build again.

---

## 5 Documents

| Document | Person | Measured | Format | Role |
|------|------|--------|------|------|
| `user-a-session-01` | Dohyun Kim, 44, male | 2026-02-14 | **Scanned copy (image only)** | Trend baseline. Worst obesity state |
| `user-a-session-02` | Dohyun Kim | 2026-05-16 | Digital export | Improving |
| `user-a-session-03` | Dohyun Kim | 2026-08-14 | Digital export | Latest. Target of the delta analysis |
| `user-a-session-04` | Dohyun Kim | 2026-11-13 | Digital export | Extra. BMI 29.8 enters Obesity Stage 1 |
| `user-b-session-01` | Jieun Park, 32, female | 2026-08-18 | Digital export | **A different user.** Underweight, D-shape trap |

### user-a — 6-month trend

| Metric | Session 1 | Session 2 | Session 3 | Change |
|------|-------|-------|-------|------|
| Weight (kg) | 96.6 | 94.2 | 92.4 | **−4.2** |
| Body Fat Mass (kg) | 34.0 | 31.8 | 30.0 | **−4.0** |
| Skeletal Muscle Mass (kg) | 34.9 | 34.8 | 34.8 | **−0.1** |
| Percent Body Fat (%) | 35.2 | 33.8 | 32.5 | −2.7 pp |
| BMI | 31.7 | 30.9 | 30.3 | −1.4 |
| Visceral Fat Level | 18 | 17 | 15 | −3 |
| Body Composition Score | 62 | 65 | 68 | +6 |

Of the 4.2 kg lost, 4.0 kg is body fat and the skeletal muscle loss is 0.1 kg. This is **high-quality weight loss with no muscle loss**,
so it is a case where the exercise and meal agents should judge "keep the current direction." Still, 19.0 kg
remain to the target, and at the current pace (−0.7 kg per month) that takes about 27 months.

---

## Test Points Built into Each Document

### 1. Scanned copy — extraction fallback path (`user-a-session-01`)

The text layer has **0 characters**. A structural parser such as `pdfplumber` returns no values, so if the
extraction tool does not fall back to the vision path, it fails on this document.
It reproduces grayscale + a 0.35-degree tilt + scanner noise.

**Measured results** (Korean-language sheet, `tools/verify_vision_fallback.py`, us-west-2):

| Item | Result |
|------|------|
| Can it be read through a Bedrock Converse document block? | **Yes. No `citations` setting needed** |
| Processing path | Page image (1,654 input tokens / 3,181 tokens for the text PDF) |
| Accuracy of measured values | 6/6 correct. The segmental lean table is also 5/5 correct to 2 decimals |
| Name | **Korean-language sheet: one syllable misread in 5 of 5 runs at temperature=0.** Not yet measured on the English sheet. |

Two things were confirmed here.

1. **No rasterization library is needed.** You can process a scanned copy with pure Python + Converse only,
   without PyMuPDF, poppler, or Code Interpreter.
2. **Names are unreliable.** Digits have distinctive shapes and are read correctly, but names are read letter by letter: on the Korean-language sheet two syllables that differ by a single stroke were confused, and with Latin letters a comparable slip is `n` read as `m`. So never verify identity from a sheet name with exact string matching (see 4 below).

### 2. D-shape trap (`user-b-session-01`)

The body type classification is **D-shape**. The textbook description of a D-shape is "an ideal state with high muscle and low fat."
But on this document the percent-of-standard values are **all below 100%**.

```
Weight                  81.6 %
Skeletal Muscle Mass    86.5 %   <- higher than weight -> D-shape by form
Body Fat Mass           62.8 %
```

Answering "this is an ideal body type" from the shape alone is a misjudgment. The real finding is underweight + low whole-body muscle mass,
and the recommended direction must be the **opposite (weight gain)** of user-a. This checks whether the agent is fooled by the shape pattern.

### 3. Upper-lower imbalance (`user-a`, all sessions)

In the segmental lean data the trunk is above standard (110.8%) while the legs are at the low end of standard (average 98.3%).
The exercise agent should read this and suggest **lower-body strengthening**.

### 4. A different user (`user-b`)

`subject_id` is `user-b`, which differs from user-a. It is used to verify Memory isolation, the identity check (comparing the logged-in user
with the name on the sheet), and access control.

The identity check is **not decided by exact string matching.** As confirmed in 1 above, names on a scanned copy
are systematically misread, so blocking on exact match would lock out legitimate users.

| Verdict | Handling | Case reproduced with these samples |
|------|------|------------------------|
| Exact match | Pass | log in as user-a + `user-a-session-02` or `-03` |
| Edit distance 1 or less | Warn and continue | log in as user-a + `user-a-session-01` (scan; the name may be misread, for example as `Dohyum Kim`) |
| Anything else | Block | log in as user-a + `user-b-session-01` (Jieun Park) |

All three cases can be reproduced with the sample documents (the warn case needs the scan to be misread, or use a simulated misreading in Lab 1).

---

## Data Schema

Each measurement item has this form. It is also the target structure that the extraction tool must produce.

```json
{ "value": 30.0, "std_low": 6.7, "std_high": 13.4, "flag": "HIGH", "label_ko": "Body Fat Mass" }
```

Field names that end in `_ko` are kept from the Korean edition. In this edition they contain English text.

`flag` is the result of comparing against the standard range.

| Value | Meaning | Used in |
|----|------|--------|
| `LOW` / `NORMAL` / `HIGH` | Low / Normal / High | Body composition and obesity analysis |
| `BELOW` / `NORMAL` / `ABOVE` | Low / Normal / High | Segmental lean mass (95~105% is treated as standard) |

The top-level keys are as follows.

| Key | Contents |
|----|------|
| `subject` | `subject_id`, name, age, sex, height |
| `measurement` | `session_seq`, measurement date/time, device, method |
| `reference` | Standard weight / standard skeletal muscle mass / standard body fat mass / standard percent body fat by sex |
| `body_composition_analysis` | Total Body Water, Protein, Minerals, Body Fat Mass + intracellular/extracellular water + Fat-Free Mass |
| `muscle_fat_analysis` | Percent of standard for Weight, Skeletal Muscle Mass, and Body Fat Mass + body type classification |
| `obesity_analysis` | BMI, PBF + obesity stage |
| `segmental_lean_analysis` | 5 segments + left-right/upper-lower balance |
| `additional_metrics` | Waist-Hip Ratio, Visceral Fat Level, Basal Metabolic Rate, Body Composition Score |
| `control_guide` | Target Weight, Weight/Muscle/Fat Change |
| `expected_analysis_findings` | Findings the analysis agent should reach (evaluation criteria) |
| `expected_trend_vs_session_01` | Ground-truth trend deltas (present only in Sessions 3 and 4) |

The `expected_*` fields are not printed on the result sheet. They are **answers used only in the Lab 7 evaluation**.

---

## Regeneration

```bash
cd sample-data
./tools/build_samples.sh      # JSON -> HTML -> PDF -> scanned copy
python3 tools/verify_samples.py
```

`build_samples.sh` uses headless Chrome on macOS. Chrome sometimes does not exit after it finishes a `--print-to-pdf` job
(observed with Chrome 151), so the script treats the moment the output file size becomes stable as success and then cleans up
**only that instance**. It uses a dedicated temporary profile, so any Chrome you have open is not affected.

Required packages: `pdfplumber`, `PyMuPDF`, `Pillow`

---

## Verification Checks

`verify_samples.py` runs **204 checks** on 5 documents.

**Arithmetic consistency** — The values on a result sheet depend on each other. Changing only one silently breaks them, so invariants guard against it.

```
Total Body Water + Protein + Minerals + Body Fat Mass = Weight
Fat-Free Mass = Total Body Water + Protein + Minerals
Intracellular Water + Extracellular Water = Total Body Water
ECW/TBW ratio = Extracellular Water / Total Body Water
BMI = Weight / Height(m)²
Percent Body Fat = Body Fat Mass / Weight × 100
percent of standard (%) = measured / standard × 100
Basal Metabolic Rate = 21.6 × Fat-Free Mass + 370
Muscle Change + Fat Change = Weight Change
Target Weight = Weight + Weight Change
segment sum < Fat-Free Mass        (excludes non-segmental parts such as the head)
```

**Status consistency** — It recalculates to confirm that each `flag` does not contradict the standard range and that the body type
classification (C/I/D) matches the shape of the three bars.

**Trend consistency** — It confirms that the deltas in `expected_trend_vs_session_01` match the real differences between sessions.

**PDF comparison** — For a digital export, the 11 ground-truth values and the 4 section titles must be extractable as text.
For the scanned copy, the extractable text must be **0 characters**. Every document must also be **1 page**.
