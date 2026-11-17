# Lab 7: Evaluations (12 min)

## Learning Objectives

Run a regression check on the result sheet **extraction accuracy** against the Ground Truth. You build an
evaluation loop that automatically confirms that the values on the same samples do not drift when you change
the extraction tool.

> **Code state at the start of this Lab**: The whole app (extraction, agents, Memory, Guardrail, deployment,
> frontend) works. This Lab guards against regressions in the most deterministic part, **extraction**, by
> comparing it with the correct answers.

---

## Theory: Why Start with Extraction Accuracy (5 min)

### Deterministic work comes first in regression checks

Extraction is deterministic (Lab 1). Deterministic means **a correct answer exists**, and when a correct answer
exists, automatic scoring is possible. Interpretation and suggestions (the agents) have no single correct
answer, so they are hard to score. That is why the evaluation starts with one axis: extraction accuracy.

| Axis | Correct answer exists? | This Lab |
|----|-----------|--------|
| **Extraction accuracy** | Yes (Ground Truth) | **Adopted** |
| Safety / routing / exercise↔meal contradiction | Needs judgment rules | Action Items |

### The Ground Truth already exists

`sample-data/ground-truth/*.json` is the single source of truth. The `expected_*` fields, which are not printed
on the result sheet, are for evaluation only. You compare the output of the extraction tool with these values.

```
Extraction tool output ─┐
                        ├─▶  Compare (numeric tolerance)  ─▶  Accuracy score
Ground Truth           ─┘
```

Numbers must match exactly (only display rounding is allowed). Names are misread on scanned sheets, so
**exclude them from the score or keep them as a separate axis** (the lesson of Lab 1).

---

## Start the Lab

```bash
mkdir -p lab7 && cd lab7
uv init --python 3.13 .
uv add boto3
```

### Step 1: Evaluation harness

Create `lab7/evaluate.py`. It compares the extraction result with the correct answers.

```python
# lab7/evaluate.py
import json
from pathlib import Path

GT_DIR = Path("../sample-data/ground-truth")

# Only numeric fields are scored. The name is excluded from this axis because scans misread it.
SCORED_FIELDS = {
    "weight_kg": lambda d: d["body_composition_analysis"]["weight_kg"],
    "bmi": lambda d: d["obesity_analysis"]["bmi"]["value"],
    "pbf_percent": lambda d: d["obesity_analysis"]["pbf_percent"]["value"],
    "body_fat_mass_kg": lambda d: d["body_composition_analysis"]["body_fat_mass_kg"]["value"],
    "skeletal_muscle_mass_kg": lambda d: d["muscle_fat_analysis"]["skeletal_muscle_mass_kg"]["value"],
}


def load_expected(doc_id):
    d = json.loads((GT_DIR / f"{doc_id}.json").read_text(encoding="utf-8"))
    return {k: fn(d) for k, fn in SCORED_FIELDS.items()}


def num_eq(a, b, tol=0.05):
    # TODO ①: Decide whether the two numbers are equal within the tolerance tol
    try:
        return abs(float(a) - float(b)) <= ________
    except (TypeError, ValueError):
        return False


def score_one(doc_id, extracted):
    """Compare the extraction result dict with the correct answers and return (hits, total)."""
    expected = load_expected(doc_id)
    hit = 0
    for key, exp in expected.items():
        # TODO ②: If the extracted value extracted[key] equals the correct answer exp, increment hit
        if num_eq(extracted.get(key), ________):
            hit += 1
    return hit, len(expected)
```

### Step 2: Run the regression

Run the extraction tool (Lab 1) on the 4 documents and score them. Here, assume the extraction results are
ready and run only the part that compares them with the correct answers (the extraction reuses the Lab 1 tool).

```python
# lab7/evaluate.py (continued)

DOC_IDS = [
    "user-a-session-01",  # Scanned copy (vision path)
    "user-a-session-02",
    "user-a-session-03",
    "user-b-session-01",
]


def run_regression(extract_fn):
    """extract_fn(doc_id) -> extraction dict. Aggregate the accuracy over all documents."""
    total_hit, total = 0, 0
    rows = []
    for doc_id in DOC_IDS:
        extracted = extract_fn(doc_id)
        hit, n = score_one(doc_id, extracted)
        rows.append((doc_id, hit, n))
        total_hit += hit
        total += n
    # TODO ③: Calculate the overall accuracy (percentage)
    accuracy = ________ / total * 100
    return accuracy, rows
```

### Step 3: Self-check against the correct answers

Before you attach the extraction tool, verify the harness itself: if the correct answers are "extracted"
as they are, the result must be 100%.

```bash
uv run python -c "
import evaluate as e
# The ground truth itself is passed as the extraction result. If the harness works, the result is 100%
acc, rows = e.run_regression(lambda doc_id: e.load_expected(doc_id))
for doc, hit, n in rows:
    print(f'{doc}: {hit}/{n}')
print(f'Accuracy: {acc:.1f}%')
# Expected: 5/5 each, accuracy 100.0%
"
```

**Expected result**: When you give the correct answers as input, the accuracy is 100.0%. After that, when you
pass the real extraction tool (Lab 1) as `extract_fn`, the regression confirms that the numbers match the
correct answers, scanned copy included.

---

## Verification

- [ ] `load_expected` returns 5 numeric fields per document
- [ ] `num_eq` allows display rounding (±0.05)
- [ ] In the ground-truth self-check, each document scores 5/5 and the accuracy is 100.0%
- [ ] The name field is excluded from the scoring axis (the basis is scan misreading)
- [ ] The numeric accuracy holds when you switch to the real extraction tool (regression)

---

## Troubleshooting

| Symptom | Cause | Fix |
|------|------|------|
| The self-check is below 100% | Error in the scoring formula | Check what `num_eq` and `score_one` compare (TODO ①②) |
| `FileNotFoundError` (ground-truth) | Path mismatch | Adjust the relative path `GT_DIR` to match where you run the script |
| Only the scanned copy scores low | Vision extraction failed | Check that the Lab 1 vision fallback works |
| The name lowers the score | The name is included in the scoring | Do not put the name in `SCORED_FIELDS` |
| The accuracy is 0% | Mismatch between the expected and extracted comparison keys | Make the `SCORED_FIELDS` keys match the extraction dict keys |

---

## 🏆 Challenge Task

1. **Add a segmental lean mass axis**: Add the lean mass of the 5 segments to the scored fields and check that
   they match to 2 decimal places (the ground-truth JSON has 2 decimals).
2. **Separate the name axis**: Keep the name as a separate axis and score an edit distance of 1 or less as a
   "partial match". Design how the regression should treat scan misreading.

---

When you finish, go to [Action Items · Resource Cleanup](./99_cleanup.md).

---

## Appendix: Answer Code

<details>
<summary>evaluate.py TODO ①–③ answers (click to expand)</summary>

**TODO ① — Comparison within a tolerance**

```python
return abs(float(a) - float(b)) <= tol
```

Display rounding (truncated decimal places) means the values are not exactly equal, so you allow an absolute tolerance `tol`.

**TODO ② — Scoring comparison**

```python
if num_eq(extracted.get(key), exp):
    hit += 1
```

Compare the extracted value with the correct value and increment hit when they match. `extracted.get(key)` also handles missing keys safely.

**TODO ③ — Accuracy calculation**

```python
accuracy = total_hit / total * 100
```

Divide the number of hits by the total to get a percentage.

### Summary

| # | Answer | Explanation |
|---|------|------|
| ① | `tol` | Tolerance for display rounding |
| ② | `exp` | The correct value to compare with the extracted value |
| ③ | `total_hit` | Accuracy = hits / total |

</details>
