# Lab 1: 결과지 추출 (40분)

## 학습 목표

체성분 결과지 PDF 에서 측정값을 뽑는 **추출 도구**를 완성합니다. 텍스트 PDF 는 `pdfplumber`
로 결정적으로 파싱하고, 스캔본은 Bedrock 비전으로 폴백하며, 뽑은 값을 산수로 검증하고
결과지 이름으로 본인 확인까지 수행합니다.

> **이 Lab 시작 시점의 코드 상태**: `content/00_setup.md` 의 환경 확인이 끝나 스택 2개가
> 배포되어 있고, `access-token.txt` 에 액세스 토큰이 저장되어 있습니다. 추출 Lambda 는
> 아직 자리표시자(`NOT_IMPLEMENTED`) 상태입니다. 이 Lab 에서 실제 코드로 채웁니다.

---

## 이론: 추출은 왜 도구이고, 폴백은 어떻게 나뉘는가 (10분)

추출은 결정적 작업이라 에이전트가 아니라 **도구**로 둡니다(00_setup 참고). 도구 내부는
두 경로로 나뉩니다.

```
@tool extract_body_composition(s3_key)
 │
 ├─ 1차  pdfplumber 구조 파싱      텍스트 레이어 PDF · LLM 호출 없음 · 결정적
 │        └─ 텍스트 0자 → NO_TEXT_LAYER
 │
 ├─ 2차  Converse document 폴백    스캔본 · Bedrock 이 페이지를 시각 분석
 │
 └─ 검증  체성분 합 = 체중, BMI 재계산 (코드) → VALIDATION_FAILED / OK
```

### 두 경로의 비용 차이 — 실측

같은 결과지를 두 경로로 처리하면 입력 토큰이 다릅니다.

| 경로 | 입력 토큰 | 처리 방식 |
|------|----------|-----------|
| 텍스트 PDF (pdfplumber → 텍스트를 모델에 전달) | 3,181 | 추출된 텍스트 |
| 스캔본 (Converse document 블록) | 1,654 | 페이지 이미지 |

핵심은 **텍스트 레이어가 있으면 LLM 을 부르지 않고 `pdfplumber` 로 끝낸다**는 것입니다.
같은 값을 매번 같게, 더 싸게, 더 빠르게 얻습니다. 스캔본일 때만 모델을 부릅니다.

### Converse 는 스캔본을 자동으로 읽습니다

실측 결과, Bedrock Converse 의 `document` 블록은 텍스트 레이어가 없는 스캔본도 **별도 설정
없이 자동으로** 읽습니다(`citations` 불필요). Bedrock 이 텍스트 레이어 유무를 판단해 경로를
나눕니다. 그래서 래스터화 라이브러리(PyMuPDF·poppler)나 Code Interpreter 가 필요 없고,
추출 도구 전체가 **순수 Python** 으로 완결됩니다.

### 수치는 정확하지만 이름은 신뢰할 수 없습니다

스캔본에서 측정 **수치**는 소수 2자리까지 정확합니다. 그러나 한글 **이름**은 체계적으로
오독됩니다 — `김도현` 이 `김도원` 으로 temperature=0 에서 5/5회 재현됐습니다. 획 하나 차이인
음절이 특히 취약합니다.

그래서 결과지 이름으로 본인 확인을 할 때 **문자열 완전일치를 쓰면 안 됩니다.**

| 판정 | 처리 |
|------|------|
| 완전일치 | 통과 |
| 편집거리(Levenshtein) 1 이하 | **경고 후 진행** |
| 그 외 | 차단 |

교육 포인트: **OCR 결과로 보안 판단을 하면 안 됩니다.**

### Gateway 를 통해 도구가 보이는 방식 (미리 보기)

Gateway 는 Lambda 를 MCP 도구로 노출합니다. 에이전트에게 보이는 도구 이름에는 접두사가
붙습니다: `{타겟명}___{도구명}`(밑줄 3개). 이번 타겟은 `bodyCompositionExtractor___extract_body_composition`
입니다. Step 1 에서 실제로 확인합니다.

---

## 실습 시작

작업 디렉터리를 하나 만들고 그 안에서 진행합니다.

```bash
mkdir -p lab1 && cd lab1
```

### Step 1: GatewayTarget 이 노출한 도구 확인

먼저 Gateway 가 어떤 도구를 노출하는지, 인증이 어떻게 동작하는지 눈으로 봅니다.
저장소에 있는 검증 스크립트를 그대로 씁니다.

> 스크립트의 두 번째 인자 이름은 `ID_TOKEN_FILE` 이지만, 실제로는 **액세스 토큰** 파일을
> 넣습니다(Gateway 는 액세스 토큰을 요구합니다 — 00_setup Step 5 참고).

```bash
GATEWAY_URL=$(aws cloudformation describe-stacks --stack-name bca-workshop-gateway \
  --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`GatewayUrl`].OutputValue' \
  --output text)

uv run python ../sample-data/tools/verify_gateway_mcp.py "$GATEWAY_URL" ../access-token.txt
# 예상 출력(요약):
#   [0] 인증 없이 initialize   -> HTTP 401  (차단됨)
#   [2] tools/list            -> bodyCompositionExtractor___extract_body_composition
#   [3] tools/call            -> Lambda 응답: {"status": "NOT_IMPLEMENTED", ...}
```

세 가지가 확인됩니다. (1) 토큰 없는 호출은 401 로 차단, (2) 도구 이름에 접두사가 붙음,
(3) Lambda 가 MCP 를 구현하지 않았는데도 Gateway 가 호출을 전달함. 지금 Lambda 는
자리표시자라 `NOT_IMPLEMENTED` 를 돌려줍니다. 이제 이 Lambda 의 알맹이를 만듭니다.

> gateway 스택을 배포하지 않았다면 이 Step 을 건너뛰고 Step 2 부터 in-process 로 진행하세요.

### Step 2: 추출 도구 뼈대 — 1차 pdfplumber 파싱

`lab1/index.py` 를 만듭니다. 아래는 뼈대이며 TODO 를 채웁니다.

```python
# lab1/index.py
import json
import os
import re

import boto3
import pdfplumber

REGION = "us-east-1"
MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"

s3 = boto3.client("s3", region_name=REGION)
bedrock = boto3.client("bedrock-runtime", region_name=REGION)


def _read_pdf_bytes(bucket, s3_key):
    obj = s3.get_object(Bucket=bucket, Key=s3_key)
    return obj["Body"].read()


def parse_with_pdfplumber(pdf_bytes):
    """텍스트 레이어에서 값을 뽑습니다. 텍스트가 없으면 None 을 반환합니다."""
    import io  # 함수 안에서 지역 import — 이 경로를 타지 않는 호출의 콜드스타트를 줄입니다

    # TODO ①: pdfplumber 로 PDF 바이트를 엽니다
    # - pdfplumber 는 파일 경로 또는 파일류 객체를 받습니다. io.BytesIO 로 감싸세요
    with ________(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)

    if len(text.strip()) == 0:
        return None  # 스캔본 — 2차 비전 폴백으로 넘어갑니다

    return _text_to_measurement(text)


def _text_to_measurement(text):
    """정규식으로 핵심 값을 뽑아 정규화 구조로 만듭니다 (판단 로직 아님, 결정적)."""
    # 참고: 아래 정규식은 교육용 단순화입니다. "체지방량"/"체지방률"처럼 접두가 겹치는
    # 항목이나 같은 단어가 여러 번 나오는 결과지에서는 실전에서 레이아웃 기반 파싱을 권장합니다.
    def grab(pattern):
        m = re.search(pattern, text)
        return float(m.group(1)) if m else None

    name_m = re.search(r"성명\s*([가-힣]+)", text)

    return {
        "name": name_m.group(1) if name_m else None,
        "weight_kg": grab(r"체중[^\d]*([\d.]+)"),
        "total_body_water_kg": grab(r"체수분[^\d]*([\d.]+)"),
        "protein_kg": grab(r"단백질[^\d]*([\d.]+)"),
        "minerals_kg": grab(r"무기질[^\d]*([\d.]+)"),
        "body_fat_mass_kg": grab(r"체지방량[^\d]*([\d.]+)"),
        "bmi": grab(r"BMI[^\d]*([\d.]+)"),
        "pbf_percent": grab(r"체지방률[^\d]*([\d.]+)"),
        "height_cm": grab(r"신장[^\d]*([\d.]+)"),
    }
```

### Step 3: 2차 비전 폴백 — Converse document 블록

스캔본은 `pdfplumber` 가 `None` 을 반환합니다. 이때 PDF 바이트를 그대로 Bedrock Converse 의
`document` 블록에 넣습니다. 래스터화하지 않습니다.

```python
# lab1/index.py (이어서)

EXTRACT_PROMPT = (
    "첨부한 체성분 분석 결과지에서 아래 항목의 값만 JSON 으로 추출하세요.\n"
    "찾을 수 없는 항목은 null. JSON 외 텍스트는 출력하지 마세요.\n"
    '{"name": 성명, "height_cm": 신장, "weight_kg": 체중, "bmi": BMI, '
    '"pbf_percent": 체지방률, "body_fat_mass_kg": 체지방량, '
    '"total_body_water_kg": 체수분, "protein_kg": 단백질, "minerals_kg": 무기질}'
)


def parse_with_vision(pdf_bytes):
    """스캔본을 Converse 로 시각 분석합니다. citations 는 켜지 않습니다."""
    # TODO ②: Converse 의 document 블록을 구성하세요
    # - format 은 "pdf", name 은 임의 문자열(공백 없이), source 는 bytes
    # - 키 이름이 정확해야 합니다: format / name / source
    document_block = {
        "format": "pdf",
        "name": "sheet",
        "________": {"bytes": pdf_bytes},
    }

    # TODO ③: bedrock-runtime 클라이언트로 Converse 를 호출하세요
    # - temperature=0 으로 재현성을 확보합니다
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

### Step 4: 검증 — 산수로 추출값을 검사

추출된 값은 서로 종속됩니다. 산수 불변식으로 검증해 조용한 오류를 막습니다. LLM 이 아니라
**코드**가 검증합니다.

```python
# lab1/index.py (이어서)

def validate(m):
    """산수 불변식으로 추출값을 검사합니다. 실패 항목 리스트를 반환합니다."""
    errors = []

    # 체성분 4항목의 합은 체중과 같아야 합니다 (표시 반올림 허용 ±0.3kg)
    parts = [m.get("total_body_water_kg"), m.get("protein_kg"),
             m.get("minerals_kg"), m.get("body_fat_mass_kg")]
    if all(v is not None for v in parts) and m.get("weight_kg") is not None:
        # TODO ④: 체수분+단백질+무기질+체지방량 이 체중과 (오차 0.3 이내) 같은지 검사
        # - 다르면 errors 에 "sum_mismatch" 를 append 하세요
        if abs(sum(parts) - m["weight_kg"]) > ________:
            errors.append("sum_mismatch")

    # BMI 는 체중 / 신장(m)² 로 재계산해 대조합니다 (오차 0.2 허용)
    if m.get("weight_kg") and m.get("height_cm") and m.get("bmi"):
        # TODO ⑤: BMI 재계산식을 완성하세요 — 신장은 cm 이므로 m 로 바꿉니다
        recomputed = m["weight_kg"] / (________ ** 2)
        if abs(recomputed - m["bmi"]) > 0.2:
            errors.append("bmi_mismatch")

    return errors
```

### Step 5: 본인 확인 — 편집거리로 판정

로그인 사용자 이름과 결과지에서 뽑은 이름을 대조합니다. 스캔본 오독 때문에 완전일치로
차단하면 안 됩니다.

```python
# lab1/index.py (이어서)

def _edit_distance(a, b):
    """Levenshtein 편집거리 (표준 DP)."""
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
    """완전일치 통과 / 편집거리 1 이하 경고 후 진행 / 그 외 차단."""
    if not sheet_name:
        return "WARN"  # 이름을 못 뽑았으면 진행하되 경고
    d = _edit_distance(login_name, sheet_name)
    # TODO ⑥: 편집거리 d 로 세 경우를 나눕니다
    # - 0 이면 "PASS", 1 이하이면 "WARN", 그 외 "BLOCK"
    if d == 0:
        return "PASS"
    elif d <= ________:
        return "WARN"
    return "BLOCK"


def handler(event, context):
    """Gateway → Lambda 이벤트. 도구 인자가 그대로 event 로 들어옵니다(봉투 없음)."""
    bucket = event.get("bucket") or os.environ["DATA_BUCKET"]
    s3_key = event["s3_key"]

    pdf_bytes = _read_pdf_bytes(bucket, s3_key)

    measurement = parse_with_pdfplumber(pdf_bytes)
    source = "pdfplumber"
    if measurement is None:
        measurement = parse_with_vision(pdf_bytes)  # 스캔본 폴백
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

### 로컬에서 도구 실행해 보기

Lambda 로 올리기 전에 로컬에서 세 케이스를 직접 돌려 봅니다(스캔본·디지털·타인).
버킷 이름을 환경변수 `DATA_BUCKET` 로 넣어 실행하세요.

```bash
BUCKET=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)

DATA_BUCKET=$BUCKET uv run python -c "
import index
# 디지털 출력본 — pdfplumber 경로
print(index.handler({'s3_key':'measurements/user-a-session-03.pdf'}, None)['source'])   # pdfplumber
# 스캔본 — 비전 폴백 경로
print(index.handler({'s3_key':'measurements/user-a-session-01.pdf'}, None)['source'])   # vision
# 본인 확인 세 경우
print(index.verify_identity('김도현','김도현'))   # PASS
print(index.verify_identity('김도현','김도원'))   # WARN  (스캔본 오독)
print(index.verify_identity('김도현','박지은'))   # BLOCK (타인)
"
```

**정상 동작 확인**: 디지털본은 `pdfplumber`, 스캔본은 `vision` 경로를 타고,
본인 확인이 `PASS / WARN / BLOCK` 세 값을 각각 반환합니다.

### (선택) Lambda 에 배포

gateway 스택을 배포했다면, 작성한 코드로 자리표시자 Lambda 를 교체합니다.
아래 패키징 명령은 `02-gateway.yaml` 의 스택 출력값 `BuildZipCommand` 와 글자 그대로
같습니다(그래서 `pip` 를 씁니다 — 출력값을 복사해 쓸 수 있게).

```bash
pip install pdfplumber -t build/ \
  --platform manylinux2014_aarch64 --only-binary=:all: --python-version 3.13
cp index.py build/
(cd build && zip -qr ../extractor.zip .)

aws lambda update-function-code \
  --function-name bca-workshop-extractor \
  --zip-file fileb://extractor.zip \
  --region us-east-1
```

교체 후 Step 1 의 `verify_gateway_mcp.py` 를 다시 돌리면 `NOT_IMPLEMENTED` 대신 실제
측정값이 돌아옵니다.

---

## 검증

- [ ] `verify_gateway_mcp.py` 가 도구 이름 `bodyCompositionExtractor___extract_body_composition` 를 노출
- [ ] 인증 없는 호출이 HTTP 401 로 차단됨
- [ ] `user-a-session-03.pdf`(디지털) 가 `source=pdfplumber` 로 추출됨
- [ ] `user-a-session-01.pdf`(스캔본) 가 `source=vision` 으로 추출됨
- [ ] 두 케이스 모두 `status=OK` (검증 통과)
- [ ] 본인 확인이 `김도현/김도현→PASS`, `김도현/김도원→WARN`, `김도현/박지은→BLOCK`
- [ ] (선택) Lambda 교체 후 `verify_gateway_mcp.py` 가 실제 측정값 반환

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `verify_gateway_mcp.py` 가 CERTIFICATE_VERIFY_FAILED | macOS Python 이 시스템 키체인 미사용 | `certifi` 를 설치하면 스크립트가 자동으로 씀 (boto3 와 함께 설치되어 있는 경우가 많음) |
| tools/call 이 HTTP 403 | ID 토큰을 넘김 | **액세스 토큰**을 사용. `access-token.txt` 재생성(00_setup Step 5) |
| tools/call 이 HTTP 401 | 토큰 만료(8시간) | `admin-initiate-auth` 로 토큰 재발급 |
| 스캔본이 `NO_TEXT_LAYER` 로 끝남 | 비전 폴백이 호출되지 않음 | `parse_with_pdfplumber` 가 텍스트 0자일 때 `None` 을 반환하는지 확인 |
| Converse 가 `ValidationException` | document 블록 키 오타 | `format`/`name`/`source` 키 이름 확인. name 에 공백 금지 |
| BMI 검증이 항상 실패 | 신장 단위(cm↔m) 혼동 | 신장을 100 으로 나눠 m 로 변환했는지 확인 |
| 정당한 사용자가 `BLOCK` | 완전일치로 판정 중 | 편집거리 1 이하는 `WARN` 이어야 함(TODO ⑥) |
| `pip install pdfplumber` 가 x86 휠 설치 | 플랫폼 미지정 | `--platform manylinux2014_aarch64 --only-binary=:all:` 필수(Lambda arm64) |

---

## 🏆 Challenge Task

1. **부위별 근육 표 추출 추가** — `_text_to_measurement` 에 5개 부위(오른팔/왼팔/몸통/
   오른다리/왼다리) 파싱을 추가하고, `validate` 에 "부위별 합 < 제지방량" 불변식을 넣으세요.
2. **폴백 로그 남기기** — 어느 경로(pdfplumber/vision)로 처리했는지 CloudWatch 에 남기되,
   **이름은 로그에 넣지 마세요**(개인정보 경계). `source` 와 `s3_key` 만 기록합니다.

---

완료 후 [Lab 2: 전문 에이전트 + Supervisor](./02_agents.md)로 이동하세요.

---

## 부록: 정답 코드

<details>
<summary>index.py TODO ①~⑥ 정답 (클릭하여 펼치기)</summary>

이 시점까지의 `lab1/index.py` 누적 스냅샷입니다. 뒤처졌다면 TODO 부분만 아래로 맞추세요.

**TODO ① — pdfplumber 진입점**

```python
with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
```

`pdfplumber.open()` 이 파싱 진입점입니다. 파일 경로 대신 바이트를 다룰 때는 `io.BytesIO`
로 감싸 파일류 객체로 넘깁니다.

**TODO ② — Converse document 블록의 source 키**

```python
document_block = {
    "format": "pdf",
    "name": "sheet",
    "source": {"bytes": pdf_bytes},
}
```

`source` 안에 `{"bytes": ...}` 로 원본을 넣습니다. `citations` 는 넣지 않습니다 — 스캔본은
설정 없이 자동으로 시각 분석됩니다.

**TODO ③ — Converse 호출**

```python
resp = bedrock.converse(
```

`bedrock-runtime` 클라이언트의 `converse` 메서드입니다. `temperature=0` 으로 재현성을 확보합니다.

**TODO ④ — 체성분 합 검증 오차**

```python
if abs(sum(parts) - m["weight_kg"]) > 0.3:
    errors.append("sum_mismatch")
```

체수분+단백질+무기질+체지방량 = 체중이 불변식입니다. 표시 반올림 때문에 정확히 같지는 않으므로
±0.3kg 를 허용합니다.

**TODO ⑤ — BMI 재계산**

```python
recomputed = m["weight_kg"] / ((m["height_cm"] / 100) ** 2)
```

BMI = 체중(kg) / 신장(m)². 신장이 cm 단위이므로 100 으로 나눠 m 로 바꾼 뒤 제곱합니다.

**TODO ⑥ — 본인 확인 편집거리 임계값**

```python
elif d <= 1:
    return "WARN"
```

편집거리 1 이하는 오독일 가능성이 높으므로 차단하지 않고 경고 후 진행합니다. `김도현`↔`김도원`
이 편집거리 1 입니다. OCR 결과로 곧바로 보안 판단을 내리지 않는다는 원칙의 구현입니다.

### 요약

| # | 정답 | 설명 |
|---|------|------|
| ① | `pdfplumber.open` | 텍스트 레이어 구조 파싱 진입점 |
| ② | `source` | Converse document 블록에 원본 바이트를 넣는 키 |
| ③ | `converse` | bedrock-runtime 의 비전 폴백 호출 |
| ④ | `0.3` | 체성분 4항목 합 = 체중 허용 오차(kg) |
| ⑤ | `m["height_cm"] / 100` | BMI 재계산 시 cm→m 변환 |
| ⑥ | `1` | 편집거리 임계값 — 오독 허용(경고 후 진행) |

</details>
