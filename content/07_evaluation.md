# Lab 7: Evaluations (12분)

## 학습 목표

Ground Truth 를 기준으로 결과지 **추출 정확도**를 회귀 검증합니다. 추출 도구를 바꿔도 같은
샘플에서 값이 어긋나지 않는지 자동으로 확인하는 평가 루프를 만듭니다.

> **이 Lab 시작 시점의 코드 상태**: 앱 전체(추출·에이전트·Memory·Guardrail·배포·프론트)가
> 동작합니다. 이 Lab 은 그중 가장 결정적인 부분인 **추출**을 정답과 대조해 회귀를 막습니다.

---

## 이론: 왜 추출 정확도부터인가 (5분)

### 결정적 작업이 회귀 검증의 1순위

추출은 결정적입니다(Lab 1). 결정적이라는 것은 **정답이 존재한다**는 뜻이고, 정답이 있으면
자동 채점이 가능합니다. 해석·제안(에이전트)은 정답이 하나가 아니라 채점이 어렵습니다. 그래서
평가는 추출 정확도 한 축부터 시작합니다.

| 축 | 정답 존재? | 이 Lab |
|----|-----------|--------|
| **추출 정확도** | 있음(Ground Truth) | **채택** |
| 안전성 / 라우팅 / 운동↔식단 모순 | 판정 규칙 필요 | Action Items |

### Ground Truth 는 이미 있습니다

`sample-data/ground-truth/*.json` 이 단일 정답 원본입니다. 결과지에 인쇄되지 않는
`expected_*` 필드는 평가 전용입니다. 추출 도구의 출력을 이 값과 대조합니다.

```
추출 도구 출력  ─┐
                 ├─▶  대조(수치 오차 허용)  ─▶  정확도 점수
Ground Truth   ─┘
```

수치는 정확히 맞아야 하고(표시 반올림만 허용), 이름은 스캔본에서 오독되므로 **점수에서
제외하거나 별도 축**으로 둡니다(Lab 1 의 교훈).

---

## 실습 시작

```bash
mkdir -p lab7 && cd lab7
uv init --python 3.13 .
uv add boto3
```

### Step 1: 평가 하네스

`lab7/evaluate.py` 를 만듭니다. 추출 결과와 정답을 대조합니다.

```python
# lab7/evaluate.py
import json
from pathlib import Path

GT_DIR = Path("../sample-data/ground-truth")

# 수치 항목만 채점합니다. 이름은 스캔본 오독 때문에 이 축에서 제외합니다.
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
    # TODO ①: 두 수치가 허용 오차 tol 이내로 같은지 판정하세요
    try:
        return abs(float(a) - float(b)) <= ________
    except (TypeError, ValueError):
        return False


def score_one(doc_id, extracted):
    """추출 결과 dict 를 정답과 대조해 (맞은 개수, 전체)를 반환합니다."""
    expected = load_expected(doc_id)
    hit = 0
    for key, exp in expected.items():
        # TODO ②: 추출값 extracted[key] 가 정답 exp 와 같으면 hit 를 올립니다
        if num_eq(extracted.get(key), ________):
            hit += 1
    return hit, len(expected)
```

### Step 2: 회귀 실행

추출 도구(Lab 1)를 4건에 대해 돌리고 채점합니다. 여기서는 추출 결과가 준비됐다고 보고
정답과 대조하는 부분만 실행합니다(추출은 Lab 1 도구 재사용).

```python
# lab7/evaluate.py (이어서)

DOC_IDS = [
    "user-a-session-01",  # 스캔본 (비전 경로)
    "user-a-session-02",
    "user-a-session-03",
    "user-b-session-01",
]


def run_regression(extract_fn):
    """extract_fn(doc_id) -> 추출 dict. 전 문서 정확도를 집계합니다."""
    total_hit, total = 0, 0
    rows = []
    for doc_id in DOC_IDS:
        extracted = extract_fn(doc_id)
        hit, n = score_one(doc_id, extracted)
        rows.append((doc_id, hit, n))
        total_hit += hit
        total += n
    # TODO ③: 전체 정확도(백분율)를 계산하세요
    accuracy = ________ / total * 100
    return accuracy, rows
```

### Step 3: 정답으로 자기 검증(자기 대조)

추출 도구를 붙이기 전에, "정답을 그대로 추출했다면 100%"가 나오는지 하네스 자체를
검증합니다.

```bash
uv run python -c "
import evaluate as e
# 정답 그대로를 추출 결과로 준 경우 — 하네스가 정상이면 100%
acc, rows = e.run_regression(lambda doc_id: e.load_expected(doc_id))
for doc, hit, n in rows:
    print(f'{doc}: {hit}/{n}')
print(f'정확도: {acc:.1f}%')
# 예상: 각 5/5, 정확도 100.0%
"
```

**정상 동작 확인**: 정답을 입력으로 주면 정확도 100.0%. 이후 실제 추출 도구(Lab 1)를
`extract_fn` 으로 넣으면, 스캔본을 포함해 수치가 정답과 일치하는지 회귀로 확인됩니다.

---

## 검증

- [ ] `load_expected` 가 문서당 5개 수치 필드를 반환
- [ ] `num_eq` 가 표시 반올림(±0.05)을 허용
- [ ] 정답 자기 대조에서 각 문서 5/5, 정확도 100.0%
- [ ] 이름 필드는 점수 축에서 제외됨(스캔본 오독 근거)
- [ ] 실제 추출 도구로 바꿔도 수치 정확도가 유지됨(회귀)

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| 자기 대조가 100% 미만 | 채점식 오류 | `num_eq` 와 `score_one` 의 비교 대상 확인(TODO ①②) |
| `FileNotFoundError` (ground-truth) | 경로 불일치 | `GT_DIR` 상대 경로를 실행 위치에 맞게 조정 |
| 스캔본만 점수가 낮음 | 비전 추출 실패 | Lab 1 의 비전 폴백이 동작하는지 확인 |
| 이름 때문에 점수가 깎임 | 이름을 채점에 포함 | `SCORED_FIELDS` 에 이름을 넣지 않음 |
| 정확도가 0% | first/expected 대조 키 불일치 | `SCORED_FIELDS` 키와 추출 dict 키를 일치 |

---

## 🏆 Challenge Task

1. **부위별 근육 축 추가** — 5개 부위 근육량을 채점 항목에 추가하고, 소수 2자리까지
   일치하는지 확인하세요(정답 JSON 이 소수 2자리).
2. **이름 축 분리** — 이름은 별도 축으로 두되 편집거리 1 이하를 "부분 정답"으로 채점해,
   스캔본 오독을 회귀에서 어떻게 다룰지 설계하세요.

---

완료 후 [Action Items · 리소스 정리](./99_cleanup.md)로 이동하세요.

---

## 부록: 정답 코드

<details>
<summary>evaluate.py TODO ①~③ 정답 (클릭하여 펼치기)</summary>

**TODO ① — 오차 허용 비교**

```python
return abs(float(a) - float(b)) <= tol
```

표시 반올림(소수 자릿수 절삭) 때문에 정확히 같지는 않으므로 절대 오차 `tol` 을 허용합니다.

**TODO ② — 채점 대조**

```python
if num_eq(extracted.get(key), exp):
    hit += 1
```

추출값과 정답값을 대조해 맞으면 hit 를 올립니다. `extracted.get(key)` 로 누락도 안전하게 처리합니다.

**TODO ③ — 정확도 계산**

```python
accuracy = total_hit / total * 100
```

맞은 개수를 전체로 나눠 백분율로 만듭니다.

### 요약

| # | 정답 | 설명 |
|---|------|------|
| ① | `tol` | 표시 반올림 허용 오차 |
| ② | `exp` | 추출값과 대조할 정답값 |
| ③ | `total_hit` | 정확도 = 맞은 개수 / 전체 |

</details>
