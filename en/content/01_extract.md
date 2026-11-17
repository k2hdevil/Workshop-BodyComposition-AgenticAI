# Lab 1: Result Sheet Extraction (40 min)

## Learning Objectives

Complete the **extraction tool** that pulls measurements from a body composition result sheet PDF. You parse a
text PDF deterministically with `pdfplumber`, fall back to Bedrock vision for scanned copies, validate the
extracted values with arithmetic, and run an identity check with the name on the result sheet.

> **Code state at the start of this Lab**: The Environment Check in `content/00_setup.md` is finished, the 2
> stacks are deployed, and the access token is saved in `access-token.txt`. The extraction Lambda is still a
> placeholder (`NOT_IMPLEMENTED`). In this Lab you fill it with real code.

---

## Theory: Why Extraction Is a Tool and How the Fallback Is Split (10 min)

Extraction is deterministic work, so you make it a **tool**, not an agent (see 00_setup). Inside the tool
there are two paths.

```
@tool extract_body_composition(s3_key)
 │
 ├─ 1st  pdfplumber structural parsing   Text-layer PDF · no LLM call · deterministic
 │        └─ 0 characters of text → NO_TEXT_LAYER
 │
 ├─ 2nd  Converse document fallback      Scanned copy · Bedrock analyzes the page visually
 │
 └─ Check  composition sum = weight, BMI recompute (code) → VALIDATION_FAILED / OK
```

### The cost difference between the two paths (measured)

If you process the same result sheet through the two paths, the input tokens differ.

| Path | Input tokens | Processing |
|------|----------|-----------|
| Text PDF (pdfplumber → text passed to the model) | 3,181 | Extracted text |
| Scanned copy (Converse document block) | 1,654 | Page image |

(Measured on the Korean-language sheet. Counts for the English sheet differ slightly.)

The key point: **if a text layer exists, you finish with `pdfplumber` without calling the LLM.** You get the
same values every time, cheaper and faster. You call the model only for scanned copies.

### Converse reads scanned copies automatically

In testing, the `document` block of Bedrock Converse reads scanned copies without a text layer **automatically,
with no extra setting** (`citations` is not needed). Bedrock decides whether a text layer exists and splits
the path. So you need no rasterization library (PyMuPDF, poppler) and no Code Interpreter, and the whole
extraction tool is complete in **pure Python**.

### Numbers are accurate, but names cannot be trusted

On a scanned sheet, the measured **numbers** are accurate to two decimal places. **Names** are the weak point.
In testing with the Korean-language edition of the sheet, the vision model misread one syllable of the name in
5 of 5 runs at temperature=0. With Latin letters, a one-character slip such as `Dohyun` → `Dohyum` has the same
effect: an exact string comparison fails for a legitimate user. Do not verify identity from a sheet name with
exact string matching.

| Verdict | Handling |
|------|------|
| Exact match | Pass |
| Edit distance (Levenshtein) of 1 or less | **Warn and continue** |
| Anything else | Block |

Teaching point: **never make a security decision from OCR output.**

### How the tool appears through the Gateway (preview)

The Gateway exposes the Lambda as an MCP tool. The tool name the agent sees gets a prefix:
`{target name}___{tool name}` (three underscores). This time the name is
`bodyCompositionExtractor___extract_body_composition`. You confirm it in Step 1.

---

## Start the Lab

Create a working directory and work inside it.

```bash
mkdir -p lab1 && cd lab1
```

### Step 1: Check the tool the GatewayTarget exposes

First, see for yourself which tools the Gateway exposes and how authentication works.
Use the verification script in the repository as it is.

> The name of the script's second argument is `ID_TOKEN_FILE`, but you actually pass the **access token** file
> (the Gateway requires the access token; see 00_setup Step 6).

```bash
GATEWAY_URL=$(aws cloudformation describe-stacks --stack-name bca-workshop-gateway \
  --region us-west-2 --query 'Stacks[0].Outputs[?OutputKey==`GatewayUrl`].OutputValue' \
  --output text)

uv run python ../sample-data/tools/verify_gateway_mcp.py "$GATEWAY_URL" ../access-token.txt
# Expected output (summary):
#   [0] initialize without auth -> HTTP 401  (blocked)
#   [2] tools/list              -> bodyCompositionExtractor___extract_body_composition
#   [3] tools/call              -> Lambda response: {"status": "NOT_IMPLEMENTED", ...}
```

The output confirms three things. (1) A call without a token is blocked with 401. (2) The tool name gets a
prefix. (3) The Gateway forwards the call even though the Lambda does not implement MCP. For now the Lambda is
a placeholder, so it returns `NOT_IMPLEMENTED`. Next you build the real contents of this Lambda.

> The gateway stack is deployed in `00_setup.md` Step 5, and it must be in the `GatewayStatus=READY` state.
> In this workshop, extraction through the Gateway MCP is the required path.

### Step 2: Extraction tool skeleton — 1st path, pdfplumber parsing

Create `lab1/index.py`. The code below is the skeleton, and you fill in the TODOs.

```python
# lab1/index.py
import json
import logging
import os
import re

# Suppress the warnings that pdfplumber (pdfminer) floods when it reads the FontBBox of Chrome-generated PDFs.
# They are harmless to extraction, but without this the console is buried in warnings and the result is hard to read.
logging.getLogger("pdfminer").setLevel(logging.ERROR)

import boto3
import pdfplumber

REGION = "us-west-2"
MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"

s3 = boto3.client("s3", region_name=REGION)
bedrock = boto3.client("bedrock-runtime", region_name=REGION)


def _read_pdf_bytes(bucket, s3_key):
    obj = s3.get_object(Bucket=bucket, Key=s3_key)
    return obj["Body"].read()


def parse_with_pdfplumber(pdf_bytes):
    """Extract the values from the text layer. Return None if there is no text."""
    import io  # Local import inside the function — reduces the cold start of calls that do not take this path

    # TODO ①: Open the PDF bytes with pdfplumber
    # - pdfplumber accepts a file path or a file-like object. Wrap the bytes in io.BytesIO
    with ________(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)

    if len(text.strip()) == 0:
        return None  # Scanned copy — move on to the 2nd path, the vision fallback

    return _text_to_measurement(text)


def _text_to_measurement(text):
    """Extract the key values with regexes and build the normalized structure (no judgment logic, deterministic)."""
    # Note: these regexes are a simplification for teaching. For labels that overlap, such as "Body Fat Mass" and
    # "Percent Body Fat", or sheets where the same word appears many times, layout-based parsing is recommended in practice.
    def grab(pattern):
        m = re.search(pattern, text)
        return float(m.group(1)) if m else None

    name_m = re.search(r"Name\s+(.+?)\s+Age\b", text)

    return {
        "name": name_m.group(1) if name_m else None,
        "weight_kg": grab(r"Weight[^\d]*([\d.]+)"),
        "total_body_water_kg": grab(r"Total Body Water[^\d]*([\d.]+)"),
        "protein_kg": grab(r"Protein[^\d]*([\d.]+)"),
        "minerals_kg": grab(r"Minerals[^\d]*([\d.]+)"),
        "body_fat_mass_kg": grab(r"Body Fat Mass[^\d]*([\d.]+)"),
        "bmi": grab(r"BMI[^\d]*([\d.]+)"),
        "pbf_percent": grab(r"Percent Body Fat[^\d]*([\d.]+)"),
        "height_cm": grab(r"Height[^\d]*([\d.]+)"),
    }
```

### Step 3: 2nd path, vision fallback — Converse document block

For a scanned copy, `pdfplumber` returns `None`. Then you put the PDF bytes as they are into the `document`
block of Bedrock Converse. You do not rasterize.

```python
# lab1/index.py (continued)

EXTRACT_PROMPT = (
    "From the attached body composition analysis sheet, extract only the values below as JSON.\n"
    "Use null for items you cannot find. Do not output any text other than the JSON.\n"
    '{"name": Name, "height_cm": Height, "weight_kg": Weight, "bmi": BMI, '
    '"pbf_percent": Percent Body Fat, "body_fat_mass_kg": Body Fat Mass, '
    '"total_body_water_kg": Total Body Water, "protein_kg": Protein, "minerals_kg": Minerals}'
)


def parse_with_vision(pdf_bytes):
    """Analyze the scanned copy visually with Converse. Do not turn on citations."""
    # TODO ②: Build the Converse document block
    # - format is "pdf", name is any string (no spaces), source is bytes
    # - The key names must be exact: format / name / source
    document_block = {
        "format": "pdf",
        "name": "sheet",
        "________": {"bytes": pdf_bytes},
    }

    # TODO ③: Call Converse with the bedrock-runtime client
    # - Use temperature=0 to get reproducibility
    resp = bedrock.________(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [
            {"document": document_block},
            {"text": EXTRACT_PROMPT},
        ]}],
        inferenceConfig={"maxTokens": 800, "temperature": 0},
    )

    text = "".join(
        b["text"] for b in resp["output"]["message"]["content"] if "text" in b
    )
    return _parse_json(text)


def _parse_json(text):
    t = text.strip()
    if "```" in t:
        t = t.split("```")[1].replace("json", "", 1).strip()
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(t[start:end + 1])
    except json.JSONDecodeError:
        return None
```

### Step 4: Validation — check the extracted values with arithmetic

The extracted values depend on each other. You validate them with arithmetic invariants to prevent silent
errors. **Code** validates, not the LLM.

```python
# lab1/index.py (continued)

def validate(m):
    """Check the extracted values with arithmetic invariants. Return the list of failed items."""
    errors = []

    # The sum of the four body composition items must equal the weight (display rounding tolerance ±0.3 kg)
    parts = [m.get("total_body_water_kg"), m.get("protein_kg"),
             m.get("minerals_kg"), m.get("body_fat_mass_kg")]
    if all(v is not None for v in parts) and m.get("weight_kg") is not None:
        # TODO ④: Check whether Total Body Water + Protein + Minerals + Body Fat Mass equals the weight (within 0.3)
        # - If they differ, append "sum_mismatch" to errors
        if abs(sum(parts) - m["weight_kg"]) > ________:
            errors.append("sum_mismatch")

    # Recompute BMI as weight / height(m)² and compare (tolerance 0.2)
    if m.get("weight_kg") and m.get("height_cm") and m.get("bmi"):
        # TODO ⑤: Complete the BMI recomputation formula — the height is in cm, so convert it to m
        recomputed = m["weight_kg"] / (________ ** 2)
        if abs(recomputed - m["bmi"]) > 0.2:
            errors.append("bmi_mismatch")

    return errors
```

### Step 5: Identity check — decide with edit distance

Compare the logged-in user's name with the name extracted from the result sheet. Because scans are misread,
you must not block on exact match.

```python
# lab1/index.py (continued)

def _edit_distance(a, b):
    """Levenshtein edit distance (standard DP)."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def verify_identity(login_name, sheet_name):
    """Exact match passes / edit distance of 1 or less warns and continues / anything else blocks."""
    if not sheet_name:
        return "WARN"  # If the name could not be extracted, continue with a warning
    d = _edit_distance(login_name, sheet_name)
    # TODO ⑥: Split the three cases by the edit distance d
    # - "PASS" if 0, "WARN" if 1 or less, otherwise "BLOCK"
    if d == 0:
        return "PASS"
    elif d <= ________:
        return "WARN"
    return "BLOCK"


def handler(event, context):
    """Gateway → Lambda event. The tool arguments arrive as the event as they are (no envelope)."""
    bucket = event.get("bucket") or os.environ["DATA_BUCKET"]
    s3_key = event["s3_key"]

    pdf_bytes = _read_pdf_bytes(bucket, s3_key)

    measurement = parse_with_pdfplumber(pdf_bytes)
    source = "pdfplumber"
    if measurement is None:
        measurement = parse_with_vision(pdf_bytes)  # Scanned copy fallback
        source = "vision"
    if measurement is None:
        return {"status": "NO_TEXT_LAYER", "s3_key": s3_key}

    errors = validate(measurement)
    status = "VALIDATION_FAILED" if errors else "OK"
    return {
        "status": status,
        "source": source,
        "s3_key": s3_key,
        "measurement": measurement,
        "validation_errors": errors,
    }
```

### Run the tool locally

Before you upload it to Lambda, run three cases locally (scanned copy, digital export, someone else).

`index.py` runs `import pdfplumber` at the top, so first install the packages the local lab environment needs
(if you skip the install, the `uv run` below fails with `ModuleNotFoundError: pdfplumber`). This repository is
not a `uv` project, so use `uv pip install` instead of `uv add` — if you have no virtual environment, create
one first.

```bash
# (Only once, if you have no virtual environment) uv venv && source .venv/bin/activate
uv pip install pdfplumber boto3
```

Now run it with the bucket name in the environment variable `DATA_BUCKET`.

```bash
BUCKET=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-west-2 --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)

DATA_BUCKET=$BUCKET uv run python -c "
import index
# Digital export — pdfplumber path
print(index.handler({'s3_key':'measurements/user-a-session-03.pdf'}, None)['source'])   # pdfplumber
# Scanned copy — vision fallback path
print(index.handler({'s3_key':'measurements/user-a-session-01.pdf'}, None)['source'])   # vision
# The three identity check cases
print(index.verify_identity('Dohyun Kim','Dohyun Kim'))   # PASS
print(index.verify_identity('Dohyun Kim','Dohyum Kim'))   # WARN  (misread in a scan)
print(index.verify_identity('Dohyun Kim','Jieun Park'))   # BLOCK (someone else)
"
```

**Expected result**: The digital copy takes the `pdfplumber` path, the scanned copy takes the `vision` path, and
the identity check returns the three values `PASS / WARN / BLOCK`.

### Step 6: Deploy to Lambda

Replace the placeholder Lambda with the code you wrote. Extraction in this workshop must go through the Gateway
MCP (see Step 1), so replacing the Lambda is a **required step** that finishes the Lab — only after the
replacement does a Gateway call return real measurements instead of `NOT_IMPLEMENTED`.
The packaging commands below are letter-for-letter the same as the stack output `BuildZipCommand` of
`02-gateway.yaml` (that is why they use `pip`, so that you can copy the output value).

```bash
pip install pdfplumber -t build/ \
  --platform manylinux2014_aarch64 --only-binary=:all: --python-version 3.13
cp index.py build/
(cd build && zip -qr ../extractor.zip .)

aws lambda update-function-code \
  --function-name bca-workshop-extractor \
  --zip-file fileb://extractor.zip \
  --region us-west-2
```

After the replacement, run `verify_gateway_mcp.py` from Step 1 again, and real measurements come back instead of
`NOT_IMPLEMENTED`. Run it as it is from the `lab1/` directory (the path is the same as in Step 1).

```bash
# If $GATEWAY_URL no longer exists in your shell, look it up again
GATEWAY_URL=$(aws cloudformation describe-stacks --stack-name bca-workshop-gateway \
  --region us-west-2 --query 'Stacks[0].Outputs[?OutputKey==`GatewayUrl`].OutputValue' \
  --output text)

uv run python ../sample-data/tools/verify_gateway_mcp.py "$GATEWAY_URL" ../access-token.txt
# Expected output (summary) — [3] tools/call now returns the real measurements:
#   [2] tools/list  -> bodyCompositionExtractor___extract_body_composition
#   [3] tools/call  -> Lambda response: {"status": "OK", "source": "pdfplumber",
#                       "s3_key": "measurements/user-a-session-03.pdf",
#                       "measurement": {"name": "...", "weight_kg": ..., "bmi": ..., ...},
#                       "validation_errors": []}
```

**Expected result**: The `status` in the `[3] tools/call` response is `OK` (or `VALIDATION_FAILED` if validation
fails), not `NOT_IMPLEMENTED`, and `source=pdfplumber` and the `measurement` object come back with it. If the
Lambda replacement does not take effect right away, run it again after a few seconds.

---

## Verification

- [ ] `verify_gateway_mcp.py` exposes the tool name `bodyCompositionExtractor___extract_body_composition`
- [ ] A call without authentication is blocked with HTTP 401
- [ ] `user-a-session-03.pdf` (digital) is extracted with `source=pdfplumber`
- [ ] `user-a-session-01.pdf` (scanned copy) is extracted with `source=vision`
- [ ] Both cases return `status=OK` (validation passed)
- [ ] The identity check returns `Dohyun Kim/Dohyun Kim→PASS`, `Dohyun Kim/Dohyum Kim→WARN`, `Dohyun Kim/Jieun Park→BLOCK`
- [ ] After the Lambda replacement, `verify_gateway_mcp.py` returns real measurements

---

## Troubleshooting

| Symptom | Cause | Fix |
|------|------|------|
| `verify_gateway_mcp.py` fails with CERTIFICATE_VERIFY_FAILED | macOS Python does not use the system keychain | Install `certifi` and the script uses it automatically (it is often already installed with boto3) |
| tools/call returns HTTP 403 | You passed the ID token | Use the **access token**. Regenerate `access-token.txt` (00_setup Step 6) |
| tools/call returns HTTP 401 | The token expired (8 hours) | Get a new token with `admin-initiate-auth` |
| A scanned copy ends with `NO_TEXT_LAYER` | The vision fallback is not called | Check that `parse_with_pdfplumber` returns `None` when there are 0 characters of text |
| Converse raises `ValidationException` | Typo in a document block key | Check the key names `format`/`name`/`source`. No spaces in name |
| The BMI validation always fails | Height unit confusion (cm↔m) | Check that you divided the height by 100 to convert it to m |
| A legitimate user gets `BLOCK` | The decision uses exact match | An edit distance of 1 or less must be `WARN` (TODO ⑥) |
| Local `uv run` fails with `ModuleNotFoundError: pdfplumber` | The package is not installed locally | Run the `uv pip install pdfplumber boto3` before the local run first |
| `pip install pdfplumber` installs an x86 wheel | No platform specified | `--platform manylinux2014_aarch64 --only-binary=:all:` is required (Lambda arm64) |
| Flood of `Could not get FontBBox` warnings | pdfminer warns while reading the PDF font metadata | Harmless. Suppress it with `logging.getLogger("pdfminer").setLevel(logging.ERROR)` (included at the top of the code) |

---

## 🏆 Challenge Task

1. **Add segmental lean mass table extraction**: Add parsing of the 5 segments (Right Arm / Left Arm / Trunk /
   Right Leg / Left Leg) to `_text_to_measurement`, and add the invariant "sum of segments < fat-free mass" to
   `validate`.
2. **Log the fallback**: Record in CloudWatch which path (pdfplumber/vision) handled the sheet, but **do not put
   the name in the log** (privacy boundary). Record only `source` and `s3_key`.

---

When you finish, go to [Lab 2: Specialist Agents + Supervisor](./02_agents.md).

---

## Appendix: Answer Code

<details>
<summary>index.py TODO ①–⑥ answers (click to expand)</summary>

This is the cumulative snapshot of `lab1/index.py` up to this point. If you fell behind, match only the TODO parts to the code below.

**TODO ① — pdfplumber entry point**

```python
with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
```

`pdfplumber.open()` is the parsing entry point. When you work with bytes instead of a file path, wrap them in
`io.BytesIO` and pass them as a file-like object.

**TODO ② — The source key of the Converse document block**

```python
document_block = {
    "format": "pdf",
    "name": "sheet",
    "source": {"bytes": pdf_bytes},
}
```

Put the original in `source` as `{"bytes": ...}`. Do not add `citations` — scanned copies are analyzed visually
without any setting.

**TODO ③ — Converse call**

```python
resp = bedrock.converse(
```

This is the `converse` method of the `bedrock-runtime` client. `temperature=0` gives reproducibility.

**TODO ④ — Tolerance of the body composition sum check**

```python
if abs(sum(parts) - m["weight_kg"]) > 0.3:
    errors.append("sum_mismatch")
```

Total Body Water + Protein + Minerals + Body Fat Mass = Weight is the invariant. Display rounding means the
values are not exactly equal, so you allow ±0.3 kg.

**TODO ⑤ — BMI recomputation**

```python
recomputed = m["weight_kg"] / ((m["height_cm"] / 100) ** 2)
```

BMI = weight (kg) / height (m)². The height is in cm, so divide by 100 to convert it to m, then square it.

**TODO ⑥ — Edit distance threshold for the identity check**

```python
elif d <= 1:
    return "WARN"
```

An edit distance of 1 or less is probably a misreading, so do not block: warn and continue. `Dohyun Kim` ↔ `Dohyum Kim` has edit distance 1. This implements the principle that OCR output alone must not decide a security question.

### Summary

| # | Answer | Explanation |
|---|------|------|
| ① | `pdfplumber.open` | Entry point of structural parsing of the text layer |
| ② | `source` | The key that holds the original bytes in the Converse document block |
| ③ | `converse` | The vision fallback call of bedrock-runtime |
| ④ | `0.3` | Tolerance (kg) for the sum of the 4 body composition items = weight |
| ⑤ | `m["height_cm"] / 100` | The cm→m conversion in the BMI recomputation |
| ⑥ | `1` | Edit distance threshold — tolerates misreading (warn and continue) |

</details>
