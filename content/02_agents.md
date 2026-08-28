# Lab 2: 전문 에이전트 + Supervisor (45분)

## 학습 목표

Strands Agents SDK 로 체성분 분석·운동 처방·식단 제안 전문 에이전트 3개를 만들고, 각각을
`@tool` 로 감싸 Supervisor 가 조율하는 Agent-as-Tool 구조를 완성합니다. 운동→식단 순차
체이닝과 일관성 검증까지 넣습니다.

> **이 Lab 시작 시점의 코드 상태**: Lab 1 에서 `extract_body_composition` 도구가 정규화된
> 측정값(dict)을 반환하는 상태입니다. 이 Lab 은 그 측정값을 입력으로 받는 에이전트를
> 작성합니다. 아직 Runtime 배포 전이라 로컬에서 실행합니다.

---

## 이론: Agent-as-Tool 과 순차 체이닝 (12분)

### 왜 에이전트가 4개인가

| 에이전트 | 역할 | 판단 성격 |
|----------|------|-----------|
| **Supervisor** | 라우팅 · 일관성 검증 · 최종 종합 | 조율 |
| analysis (체성분 분석) | 측정값 → 소견 | 해석 |
| exercise (운동 처방) | 소견 → 운동 계획 | 처방 |
| nutrition (식단 제안) | 소견 + **운동 계획** → 식단 | 처방 |

추출은 Lab 1 에서 봤듯 **도구**입니다(결정적). 여기 4개는 전부 판단이 필요해 **에이전트**입니다.

### Agent-as-Tool 패턴

Supervisor 가 전문 에이전트를 **도구처럼 호출**합니다. 전문 에이전트를 `@tool` 함수로 감싸면,
Supervisor 의 모델이 "체성분을 분석해야겠다"고 판단할 때 그 함수를 호출합니다. 모두 같은
Python 프로세스 안에서 돕니다.

```
Supervisor Agent
   │ tools=[analysis_specialist, exercise_specialist, nutrition_specialist]
   ▼
@tool analysis_specialist(measurement)          -> 소견
@tool exercise_specialist(findings)             -> 운동 계획
@tool nutrition_specialist(findings, exercise)  -> 식단 계획   # 운동 계획을 입력으로
```

### 운동 → 식단은 순차로 체이닝합니다

두 에이전트를 독립 실행하면 모순된 계획이 나옵니다. 식단이 큰 칼로리 적자를 제안하는데
운동이 고강도 근력을 처방하면 근손실을 유발합니다. 그래서 **분석 → 운동 → 식단** 순서를
고정하고, 식단 에이전트가 운동 계획을 입력으로 받습니다. Supervisor 가 마지막에 일관성을
검증합니다.

### 이름은 에이전트에게 보내지 않습니다

측정값에는 이름이 들어 있지만, **분석에 이름은 아무 역할도 하지 않습니다.** 개인정보 경계
설계(00_setup·README)에 따라 에이전트 컨텍스트에서 이름을 제외합니다. 애초에 LLM 에 보내지
않으면 마스킹이 필요 없습니다.

### D자형 함정 (user-b)

체형 판정 D자형의 교과서적 설명은 "근육 많고 지방 적은 이상적 상태"입니다. 그러나 user-b 는
D자형이면서 표준 대비 세 지표가 **모두 100% 미만**입니다(저체중 + 근육량 부족). 형태만 보고
"이상적"이라 답하면 오판입니다. 분석 에이전트가 형태 패턴에 낚이지 않고 표준 대비 절대값까지
읽어야 합니다. 이 케이스를 실습 끝에서 확인합니다.

---

## 실습 시작

Lab 1 의 `lab1/` 과 별도로 작업합니다. Strands 와 AgentCore SDK 를 설치합니다.

```bash
mkdir -p lab2 && cd lab2
uv init --python 3.13 .
uv add strands-agents boto3
```

### Step 1: 전문 에이전트의 시스템 프롬프트

`lab2/agents.py` 를 만듭니다. 먼저 SDK 를 들여오고 공통 모델을 정의합니다.

```python
# lab2/agents.py
import json

# TODO ①: Strands 에서 Agent 와 tool 을 가져옵니다
from strands import ________, ________
from strands.models import BedrockModel

MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"

# 전문 에이전트가 공유하는 모델. temperature 를 낮춰 처방의 일관성을 확보합니다.
model = BedrockModel(model_id=MODEL_ID, temperature=0.2)

DISCLAIMER = (
    "본 분석은 건강 참고용 정보이며 의학적 진단이 아닙니다. "
    "확정 진단이나 약물·보충제 처방은 하지 않습니다."
)

ANALYSIS_PROMPT = (
    "당신은 체성분 분석 전문가입니다. 정규화된 측정값(JSON)을 받아 소견을 제시하세요.\n"
    "- 체형 판정(C/I/D)은 형태일 뿐입니다. 표준 대비 백분율의 절대값을 함께 보세요.\n"
    "- D자형이라도 세 지표가 모두 표준 미만이면 '이상적'이 아니라 저체중·근육부족입니다.\n"
    "- 부위별 근육의 상하·좌우 불균형을 지적하세요.\n"
    f"- 확정 진단을 내리지 마세요. 모든 소견 끝에 다음을 덧붙이세요: {DISCLAIMER}"
)

EXERCISE_PROMPT = (
    "당신은 운동 처방 전문가입니다. 분석 소견을 받아 운동 계획을 제시하세요.\n"
    "- 부위별 불균형이 있으면 약한 부위를 보완하는 운동을 우선하세요.\n"
    "- 유산소와 근력의 비율, 주당 빈도, 강도를 구체적으로 제시하세요.\n"
    "- 확정 진단·약물 처방을 하지 마세요."
)

NUTRITION_PROMPT = (
    "당신은 식단 제안 전문가입니다. 분석 소견과 '운동 계획'을 함께 받아 식단을 제시하세요.\n"
    "- 운동 계획의 강도와 모순되지 않게 하세요. 고강도 근력 + 극단적 칼로리 적자 금지.\n"
    "- 극단적 칼로리 제한을 권하지 마세요. 약물·보충제 처방을 하지 마세요."
)
```

### Step 2: 분석 에이전트를 도구로 감싸기

각 전문 에이전트를 `@tool` 함수 안에서 생성·호출합니다. 함수의 docstring 과 타입 힌트가
Supervisor 에게 보이는 도구 명세가 됩니다.

```python
# lab2/agents.py (이어서)

def _strip_pii(measurement: dict) -> dict:
    """에이전트에 넘기기 전 이름을 제거합니다 (개인정보 경계)."""
    # TODO ⑥: measurement 에서 'name' 키를 제외한 새 dict 를 만듭니다
    # - 이름은 분석에 필요 없으므로 애초에 LLM 컨텍스트에 넣지 않습니다
    return {k: v for k, v in measurement.items() if k != ________}


# TODO ②: 이 함수를 Strands 도구로 만드는 데코레이터를 붙이세요
@________
def analysis_specialist(measurement: dict) -> str:
    """체성분 측정값(JSON)을 분석해 소견을 반환합니다.

    Args:
        measurement: 정규화된 체성분 측정값. 이름은 제외하고 전달됩니다.
    Returns:
        체형·비만·부위별 균형에 대한 소견 텍스트.
    """
    safe = _strip_pii(measurement)
    # TODO ③: 분석 시스템 프롬프트로 Agent 를 생성하세요
    # - model=model, system_prompt=ANALYSIS_PROMPT, tools=[] (도구 불필요)
    agent = ________(model=model, system_prompt=ANALYSIS_PROMPT, tools=[])
    response = agent(f"다음 측정값을 분석하세요:\n{json.dumps(safe, ensure_ascii=False)}")
    return str(response)
```

### Step 3: 운동·식단 에이전트 — 순차 체이닝

운동은 소견을 입력으로, 식단은 소견 **과 운동 계획**을 함께 입력으로 받습니다.

```python
# lab2/agents.py (이어서)

@tool
def exercise_specialist(findings: str) -> str:
    """분석 소견을 받아 운동 계획을 반환합니다.

    Args:
        findings: analysis_specialist 가 만든 소견 텍스트.
    Returns:
        유산소·근력 구성, 빈도, 강도를 담은 운동 계획.
    """
    agent = Agent(model=model, system_prompt=EXERCISE_PROMPT, tools=[])
    return str(agent(f"다음 소견에 맞는 운동 계획을 제시하세요:\n{findings}"))


# TODO ④: 식단 에이전트가 '운동 계획'을 입력으로 받도록 시그니처를 완성하세요
# - 순차 체이닝: 운동 계획과 모순되지 않는 식단을 만들기 위함입니다
@tool
def nutrition_specialist(findings: str, ________: str) -> str:
    """분석 소견과 운동 계획을 받아 식단 계획을 반환합니다.

    Args:
        findings: 분석 소견.
        exercise_plan: exercise_specialist 가 만든 운동 계획.
    Returns:
        운동 계획과 일관된 식단 계획.
    """
    agent = Agent(model=model, system_prompt=NUTRITION_PROMPT, tools=[])
    prompt = (
        f"소견:\n{findings}\n\n운동 계획:\n{exercise_plan}\n\n"
        "위 운동 계획과 모순되지 않는 식단을 제시하세요."
    )
    return str(agent(prompt))
```

### Step 4: Supervisor 조율

Supervisor 는 세 전문 에이전트를 도구로 등록하고, 순서(분석→운동→식단)와 일관성 검증을
시스템 프롬프트로 지시받습니다.

```python
# lab2/agents.py (이어서)

SUPERVISOR_PROMPT = (
    "당신은 체성분 코칭을 조율하는 Supervisor 입니다. 다음 순서를 반드시 지키세요.\n"
    "1) analysis_specialist 로 소견을 얻습니다.\n"
    "2) exercise_specialist 로 운동 계획을 얻습니다.\n"
    "3) nutrition_specialist 에 소견과 운동 계획을 함께 넘겨 식단을 얻습니다.\n"
    "4) 운동과 식단이 모순되면(예: 고강도 근력 + 극단 칼로리 적자) 지적하고 조정하세요.\n"
    "최종 답변에 소견·운동·식단을 정리하고 건강 참고용 정보라는 면책을 포함하세요."
)


def build_supervisor() -> "Agent":
    # TODO ⑤: 세 전문 에이전트를 Supervisor 의 도구로 등록하세요
    return Agent(
        model=model,
        system_prompt=SUPERVISOR_PROMPT,
        tools=[________, ________, ________],
    )


def coach(measurement: dict) -> str:
    """측정값을 받아 Supervisor 를 실행하고 최종 코칭을 반환합니다."""
    supervisor = build_supervisor()
    return str(supervisor(
        "다음 측정값으로 코칭을 진행하세요. 반드시 분석 → 운동 → 식단 순서로."
        f"\n{json.dumps(measurement, ensure_ascii=False)}"
    ))
```

### Step 5: 로컬 실행 — user-a 와 D자형 함정(user-b)

Lab 1 정답 JSON 을 측정값으로 써서 두 사람을 각각 돌려 봅니다.

```bash
uv run python -c "
import json, agents
# user-a-session-03 (C자형 비만) — 감량 방향
m_a = json.load(open('../sample-data/ground-truth/user-a-session-03.json'))
print('=== user-a ===')
print(agents.analysis_specialist({
    'body_type': m_a['muscle_fat_analysis']['body_type'],
    'bmi': m_a['obesity_analysis']['bmi']['value'],
    'pbf_percent': m_a['obesity_analysis']['pbf_percent']['value'],
}))
# user-b-session-01 (D자형 함정) — 증량 방향이어야 함
m_b = json.load(open('../sample-data/ground-truth/user-b-session-01.json'))
print('=== user-b (D자형 함정) ===')
print(agents.analysis_specialist({
    'body_type': m_b['muscle_fat_analysis']['body_type'],
    'muscle_fat_analysis': m_b['muscle_fat_analysis'],
}))
"
```

**정상 동작 확인**: user-a 소견은 체지방 감량 방향, user-b 소견은 D자형이라도
"이상적"이라 하지 않고 저체중·근육부족을 지적하며 **증량 방향**을 제시합니다. 두 소견
모두 끝에 면책 문구가 있어야 합니다.

---

## 검증

- [ ] `agents.py` 가 import 오류 없이 로드됨
- [ ] `analysis_specialist` 에 넘기는 dict 에 `name` 키가 없음(개인정보 경계)
- [ ] Supervisor 가 분석 → 운동 → 식단 순서로 도구를 호출함
- [ ] `nutrition_specialist` 가 운동 계획을 입력으로 받음(시그니처에 2개 인자)
- [ ] user-a 소견은 감량, user-b 소견은 증량 방향
- [ ] 모든 소견에 건강 참고용 면책 문구가 포함됨

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `ImportError: cannot import name 'tool'` | 패키지 미설치 | `uv add strands-agents` 후 `uv run` 으로 실행 |
| `AccessDeniedException` (bedrock) | 모델 접근 미승인 | 콘솔에서 Claude Sonnet 4.5 모델 액세스 활성화 |
| Supervisor 가 식단을 먼저 호출 | 순서 지시가 약함 | `SUPERVISOR_PROMPT` 에 순서를 번호로 명시했는지 확인 |
| 운동·식단이 서로 모순 | 순차 체이닝이 끊김 | `nutrition_specialist` 가 `exercise_plan` 을 실제로 받는지 확인(TODO ④) |
| user-b 소견이 "이상적 체형" | 형태만 보고 판단 | `ANALYSIS_PROMPT` 의 "표준 대비 절대값" 지시 확인 |
| 응답에 이름이 노출됨 | PII 제거 누락 | `_strip_pii` 가 실제로 호출되는지 확인(TODO ⑥) |
| `ThrottlingException` | 짧은 시간에 다수 호출 | 재시도 또는 호출 간 지연. 워크샵 계정 한도 고려 |

---

## 🏆 Challenge Task

1. **라우팅 분기** — 측정값의 체형·PBF 로 "감량 트랙 / 증량 트랙"을 먼저 분기해 Supervisor
   프롬프트에 힌트로 넣으세요. user-a 와 user-b 가 반대 트랙을 타는지 확인합니다.
2. **일관성 자동 검증** — 운동 계획에 "고강도"가, 식단에 "칼로리 적자"가 동시에 있으면
   경고를 반환하는 코드 기반 체크(`check_consistency`)를 추가하세요.

---

완료 후 [Lab 3: Memory 추이 분석](./03_memory.md)로 이동하세요.

---

## 부록: 정답 코드

<details>
<summary>agents.py TODO ①~⑥ 정답 (클릭하여 펼치기)</summary>

**TODO ① — SDK import**

```python
from strands import Agent, tool
```

`Agent` 는 에이전트 본체, `tool` 은 함수를 도구로 만드는 데코레이터입니다.

**TODO ② — 도구 데코레이터**

```python
@tool
def analysis_specialist(measurement: dict) -> str:
```

`@tool` 이 docstring 과 타입 힌트에서 도구 명세(이름·설명·입력 스키마)를 자동 생성합니다.

**TODO ③ — 분석 Agent 생성**

```python
agent = Agent(model=model, system_prompt=ANALYSIS_PROMPT, tools=[])
```

전문 에이전트는 다른 도구가 필요 없으므로 `tools=[]` 로 둡니다. 판단만 합니다.

**TODO ④ — 식단 에이전트 시그니처**

```python
def nutrition_specialist(findings: str, exercise_plan: str) -> str:
```

식단이 운동 계획을 입력으로 받아야 순차 체이닝이 성립합니다. 두 번째 인자 이름은 함수 본문에서
쓰는 `exercise_plan` 과 일치해야 합니다.

**TODO ⑤ — Supervisor 도구 등록**

```python
tools=[analysis_specialist, exercise_specialist, nutrition_specialist],
```

세 전문 에이전트(도구)를 Supervisor 에 등록합니다. Supervisor 의 모델이 순서를 판단해 호출합니다.

**TODO ⑥ — 이름 제외**

```python
return {k: v for k, v in measurement.items() if k != "name"}
```

이름은 분석에 쓰이지 않으므로 LLM 컨텍스트에 넣지 않습니다. 마스킹이 아니라 경계 분리입니다.

### 요약

| # | 정답 | 설명 |
|---|------|------|
| ① | `Agent, tool` | Strands 에이전트 본체와 도구 데코레이터 |
| ② | `tool` | 함수를 Supervisor 가 부를 도구로 변환 |
| ③ | `Agent` | 전문 에이전트 생성(도구 없음) |
| ④ | `exercise_plan` | 식단이 운동 계획을 받는 순차 체이닝 |
| ⑤ | `analysis_specialist, exercise_specialist, nutrition_specialist` | Supervisor 의 3개 도구 |
| ⑥ | `"name"` | 이름을 컨텍스트에서 제외(개인정보 경계) |

</details>
