# Lab 3: Memory 추이 분석 (25분)

## 학습 목표

AgentCore Memory 를 직접 생성하고 전략(strategy)을 설계하여, 같은 사용자의 회차별 측정
이력을 저장하고 3회차의 변화(델타)를 분석합니다. 사용자 식별은 이름이 아니라 Cognito `sub`
로 격리합니다.

> **이 Lab 시작 시점의 코드 상태**: Lab 2 에서 분석·운동·식단 에이전트가 단일 측정값을
> 처리합니다. 이 Lab 은 여러 회차를 저장·조회해 "지난번보다 나아졌는가"를 답합니다.
> Memory 리소스는 참가자가 직접 만듭니다.

---

## 이론: 왜 Memory 를 직접 만드는가, 무엇을 격리하는가 (8분)

### 전략 설계가 학습의 본체입니다

Memory 는 템플릿에 박아두지 않고 참가자가 만듭니다. 단기 기억(원문 이벤트)과 장기 기억
(추출된 요약)을 어떻게 나눌지, 네임스페이스를 어떻게 설계할지가 이 Lab 의 핵심입니다.

| 구분 | 저장 내용 | 이 워크샵에서 |
|------|-----------|---------------|
| 단기(이벤트) | 원문 그대로 | 회차별 측정값 JSON |
| 장기(전략) | 모델이 추출·통합한 요약 | 회차 간 추세 요약 |

### 사용자 격리 — 이름이 아니라 `sub`

`actor_id` 로 사용자를 격리합니다. 여기에 **이름을 넣지 않습니다.** 스캔본 이름은 오독되고
(Lab 1), 이름은 로그·추적·Memory 에서 제외한다는 경계 설계(README)에 따라 Cognito `sub`
(불변 사용자 ID)를 씁니다.

```
actor_id = Cognito sub  (예: "a1b2c3d4-...")     <- 이름 아님
session_id = 회차 식별   (예: "session-2026-08-14")
```

user-a 와 user-b 는 `actor_id` 가 달라 Memory 가 자동으로 격리됩니다.

### user-a 의 6개월 추이 (델타 정답)

| 지표 | 1회차 | 3회차 | 변화 |
|------|-------|-------|------|
| 체중 (kg) | 96.6 | 92.4 | **−4.2** |
| 체지방량 (kg) | 34.0 | 30.0 | **−4.0** |
| 골격근량 (kg) | 34.9 | 34.8 | −0.1 |
| 체지방률 (%) | 35.2 | 32.5 | −2.7%p |

감량 4.2kg 중 4.0kg 이 체지방이고 근손실은 0.1kg 입니다. **근손실 없는 양질의 감량**이라
"현재 방향 유지"가 옳은 판단입니다. 추이 분석은 서로 다른 두 사람으로는 검증할 수 없어
같은 사람의 3회차가 필요합니다.

---

## 실습 시작

```bash
mkdir -p lab3 && cd lab3
uv init --python 3.13 .
uv add bedrock-agentcore boto3
```

Memory 실행 역할 ARN 을 core 스택에서 가져옵니다(Memory 가 요약 추출 시 모델을 부를 때 씀).

```bash
MEMORY_ROLE=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-west-2 --query 'Stacks[0].Outputs[?OutputKey==`MemoryExecutionRoleArn`].OutputValue' \
  --output text)
echo "$MEMORY_ROLE"
# 예상 출력: arn:aws:iam::<계정>:role/bca-workshop-memory-execution-role
```

### Step 1: Memory 생성 — 전략 설계

`lab3/memory_store.py` 를 만듭니다.

```python
# lab3/memory_store.py
import json
import os
import time

# TODO ①: AgentCore Memory 클라이언트를 가져옵니다
from bedrock_agentcore.memory import ________

REGION = "us-west-2"
client = MemoryClient(region_name=REGION)


def create_trend_memory():
    """회차 요약 전략을 가진 Memory 를 생성합니다."""
    # TODO ②: 요약 전략으로 Memory 를 생성하세요(생성 완료까지 대기하는 메서드 사용)
    # - strategies 에 summaryMemoryStrategy 를 넣습니다
    # - namespaceTemplates 에 {actorId}/{sessionId} 를 써서 사용자·회차별로 격리합니다
    memory = client.________(
        name="BodyCompositionTrend",
        strategies=[{
            "summaryMemoryStrategy": {
                "name": "SessionSummarizer",
                "namespaceTemplates": ["/trend/{actorId}/{sessionId}/"],
            }
        }],
        # TODO ⑤: 요약 전략은 Memory 가 모델을 호출하므로 실행 역할 ARN 이 필요합니다.
        # - 이 값을 넘기는 인자 이름을 채우세요. 값은 MEMORY_ROLE 환경변수에서 읽습니다
        ________=os.environ["MEMORY_ROLE"],
    )
    return memory.get("id")
```

> `create_memory_and_wait` 는 Memory 가 `ACTIVE` 가 될 때까지 기다립니다. `summaryMemoryStrategy`
> 는 요약을 추출할 때 Memory 가 사용자 계정에서 Bedrock 모델을 호출하므로, 그 권한을 주는
> 실행 역할 ARN 을 넘겨야 합니다(TODO ⑤). 값은 `os.environ["MEMORY_ROLE"]` 에서 읽으므로,
> 실습 시작에서 조회한 `MEMORY_ROLE` 을 실행할 때 환경변수로 전달합니다(Step 4 참고).

### Step 2: 회차 저장 — actor_id 에 sub 사용

```python
# lab3/memory_store.py (이어서)

def save_session(memory_id, user_sub, session_id, measurement):
    """한 회차의 측정값을 이벤트로 저장합니다.

    Args:
        user_sub: Cognito sub. 이름이 아니라 이 값으로 사용자를 격리합니다.
        session_id: 회차 식별자.
        measurement: 정규화된 측정값(dict).
    """
    summary = {
        "weight_kg": measurement["body_composition_analysis"]["weight_kg"],
        "body_fat_mass_kg": measurement["body_composition_analysis"]["body_fat_mass_kg"]["value"],
        "skeletal_muscle_mass_kg": measurement["muscle_fat_analysis"]["skeletal_muscle_mass_kg"]["value"],
        "pbf_percent": measurement["obesity_analysis"]["pbf_percent"]["value"],
    }
    # TODO ③: 이벤트를 저장하세요. actor_id 에는 이름이 아니라 user_sub 를 넣습니다
    client.create_event(
        memory_id=memory_id,
        actor_id=________,
        session_id=session_id,
        messages=[(json.dumps(summary, ensure_ascii=False), "USER")],
    )
```

### Step 3: 추이 조회 — 회차 간 델타

```python
# lab3/memory_store.py (이어서)

def get_trend(memory_id, user_sub, session_id):
    """저장된 요약을 조회해 추세 질의를 던집니다."""
    # TODO ④: 네임스페이스에서 추세 요약을 조회하세요
    # - namespace 는 전략의 템플릿을 사용자·회차로 치환한 문자열입니다
    memories = client.________(
        memory_id=memory_id,
        namespace=f"/trend/{user_sub}/{session_id}/",
        query="회차 간 체중·체지방·골격근량 변화 추세를 요약",
    )
    return memories


def compute_delta(first, latest):
    """두 회차 요약의 차이를 코드로 계산합니다(결정적)."""
    return {
        "weight_delta_kg": round(latest["weight_kg"] - first["weight_kg"], 1),
        "body_fat_mass_delta_kg": round(
            latest["body_fat_mass_kg"] - first["body_fat_mass_kg"], 1),
        "skeletal_muscle_mass_delta_kg": round(
            latest["skeletal_muscle_mass_kg"] - first["skeletal_muscle_mass_kg"], 1),
    }
```

### Step 4: 3회차 저장하고 델타 확인

user-a 의 3회차를 저장한 뒤 요약이 추출되기를 잠시 기다립니다.

`memory_store.py` 가 `os.environ["MEMORY_ROLE"]` 을 읽으므로, 실행 시 이 환경변수를
반드시 함께 넘깁니다(실습 시작에서 조회한 `MEMORY_ROLE` 값).

```bash
MEMORY_ROLE=$MEMORY_ROLE uv run python -c "
import json, time, memory_store as ms
mid = ms.create_trend_memory()
print('memory_id:', mid)

SUB = 'user-a-sub-0001'   # 실제로는 Cognito sub. 이름을 쓰지 않습니다
gt = '../sample-data/ground-truth'
for seq in ('01','02','03'):
    m = json.load(open(f'{gt}/user-a-session-{seq}.json'))
    ms.save_session(mid, SUB, f'session-{seq}', m)
    print('saved session', seq)

# 코드 기반 델타(결정적) — 정답과 대조 가능
first = json.load(open(f'{gt}/user-a-session-01.json'))
latest = json.load(open(f'{gt}/user-a-session-03.json'))
def brief(d):
    return {
        'weight_kg': d['body_composition_analysis']['weight_kg'],
        'body_fat_mass_kg': d['body_composition_analysis']['body_fat_mass_kg']['value'],
        'skeletal_muscle_mass_kg': d['muscle_fat_analysis']['skeletal_muscle_mass_kg']['value'],
    }
print('delta:', ms.compute_delta(brief(first), brief(latest)))
# 예상: {'weight_delta_kg': -4.2, 'body_fat_mass_delta_kg': -4.0, 'skeletal_muscle_mass_delta_kg': -0.1}
"
```

**정상 동작 확인**: `compute_delta` 가 체중 −4.2 / 체지방 −4.0 / 골격근 −0.1 을 반환합니다
(정답 JSON 의 `expected_trend_vs_session_01` 과 일치). Memory 요약은 추출에 시간이
걸리므로, 조회가 비면 잠시 후 다시 시도합니다.

### Step 5: 사용자 격리 검증 — 다른 sub 로는 안 보인다

격리 키는 `actor_id`(=Cognito `sub`)이고, 조회 네임스페이스도 `/trend/{sub}/...` 로 그
`sub` 를 끼워 넣습니다. 따라서 **다른 사용자의 `sub` 로 조회하면 남의 회차가 나오면 안
됩니다.** 이 앱은 본인이 본인 결과지를 보는 앱이므로, 이 격리가 깨지면 타인의 건강 이력이
노출됩니다. 말로 끝내지 않고 직접 확인합니다.

같은 Memory 를 방금 만들었다면 그 `memory_id` 를 재사용하고, 새 셸이면 Step 4 처럼 다시
만들어 user-a 3회차를 저장한 상태에서 실행하세요. user-a 의 `sub` 로는 결과가 나오고,
아무것도 저장하지 않은 user-b 의 `sub` 로는 비어 있어야 합니다.

```bash
MEMORY_ROLE=$MEMORY_ROLE uv run python -c "
import json, memory_store as ms

# Step 4 에서 만든 Memory 를 그대로 쓰거나, 없으면 새로 만들어 user-a 3회차를 저장합니다
mid = ms.create_trend_memory()
gt = '../sample-data/ground-truth'
A_SUB, B_SUB = 'user-a-sub-0001', 'user-b-sub-0002'   # 서로 다른 Cognito sub
for seq in ('01','02','03'):
    ms.save_session(mid, A_SUB, f'session-{seq}', json.load(open(f'{gt}/user-a-session-{seq}.json')))

# 같은 session_id 로 두 사용자의 네임스페이스를 조회해 대조합니다
a_hits = ms.get_trend(mid, A_SUB, 'session-03')   # user-a 본인 — 결과가 있어야 함
b_hits = ms.get_trend(mid, B_SUB, 'session-03')   # user-b — user-a 것이 보이면 안 됨

def count(hits):
    # retrieve_memories 응답 형태(list 또는 dict)에 관계없이 길이를 셉니다
    if isinstance(hits, dict):
        hits = hits.get('memoryRecords') or hits.get('memories') or []
    return len(hits or [])

print('user-a sub 조회 건수:', count(a_hits))
print('user-b sub 조회 건수:', count(b_hits))
assert count(b_hits) == 0, '격리 실패: user-b sub 로 user-a 데이터가 조회됨'
print('격리 확인 OK — 다른 sub 로는 조회되지 않음')
"
```

**정상 동작 확인**: `user-b sub 조회 건수: 0` 이 나오고 `assert` 가 통과합니다. user-a 는
방금 저장했으므로 요약이 추출되면 건수가 1 이상으로 올라갑니다(추출 지연 시 user-a 는 0 일
수 있으나, 격리 검증의 핵심은 **user-b 가 항상 0** 이라는 점입니다).

> 참고: `session_id` 는 회차를 나누는 값이고, 사용자 격리는 `actor_id`(`sub`)가 담당합니다.
> 그래서 같은 `session-03` 을 조회해도 `sub` 가 다르면 서로 다른 네임스페이스가 됩니다.

---

## 검증

- [ ] `create_trend_memory` 가 `memory_id` 를 반환하고 Memory 가 `ACTIVE`
- [ ] `memory_execution_role_arn` 인자를 채워 실행 역할을 전달함(요약 전략 필수, TODO ⑤)
- [ ] `save_session` 의 `actor_id` 에 이름이 아니라 `sub` 가 들어감
- [ ] user-a 3회차가 저장됨
- [ ] `compute_delta` 결과가 체중 −4.2 / 체지방 −4.0 / 골격근 −0.1
- [ ] user-b 의 `sub` 로는 user-a 의 회차가 조회되지 않음(Step 5 격리 검증 통과, `assert` OK)

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `create_memory_and_wait` 가 AccessDenied | 실행 역할 ARN 미전달 | 실행 시 `MEMORY_ROLE=$MEMORY_ROLE uv run python ...` 로 환경변수를 넘겼는지 확인 |
| `KeyError: 'MEMORY_ROLE'` | 환경변수 미전달 | 위와 동일. 실습 시작에서 `MEMORY_ROLE` 을 조회했는지도 확인 |
| `retrieve_memories` 결과가 비어 있음 | 요약 추출이 아직 진행 중 | 30~60초 후 재시도. 단기 이벤트는 즉시, 장기 요약은 지연 |
| 다른 사용자 데이터가 섞임 | `actor_id` 를 고정값으로 씀 | 사용자마다 다른 `sub` 를 넣었는지 확인 |
| Step 5 `assert` 가 격리 실패로 멈춤 | 저장·조회 네임스페이스에 `sub` 미반영 | `create_event` 의 `actor_id` 와 `get_trend` 의 `namespace` 가 모두 `sub` 를 쓰는지 확인 |
| `namespace` 불일치로 조회 실패 | 템플릿과 조회 문자열 불일치 | 전략의 `namespaceTemplates` 와 조회 `namespace` 를 같은 형식으로 |
| 델타 부호가 반대 | first/latest 순서 뒤바뀜 | `compute_delta(first, latest)` 인자 순서 확인 |
| `ThrottlingException` | 짧은 시간 다수 이벤트 | 저장 사이에 지연을 두거나 재시도 |

---

## 🏆 Challenge Task

1. **추세를 에이전트에 주입** — Lab 2 의 `analysis_specialist` 가 현재 측정값뿐 아니라
   `compute_delta` 결과도 받아 "지난번 대비" 소견을 내도록 프롬프트를 확장하세요.
2. **페이스 추정** — 월 평균 감량 속도로 목표 체중 도달까지 남은 개월 수를 계산해 소견에
   포함하세요(정답 JSON 의 `assessment_ko` 가 약 27개월이라 명시).

---

완료 후 [Lab 4: Guardrail + 캐시](./04_guardrail_cache.md)로 이동하세요.

---

## 부록: 정답 코드

<details>
<summary>memory_store.py TODO ①~⑤ 정답 (클릭하여 펼치기)</summary>

**TODO ① — Memory 클라이언트 import**

```python
from bedrock_agentcore.memory import MemoryClient
```

`bedrock-agentcore` 패키지의 상위 SDK 클라이언트입니다. boto3 저수준 호출보다 간결합니다.

**TODO ② — Memory 생성(대기 포함)**

```python
memory = client.create_memory_and_wait(
```

`create_memory_and_wait` 는 Memory 가 `ACTIVE` 가 될 때까지 폴링합니다. 바로 이벤트를 저장할
수 있어 실습에 적합합니다. 실행 역할 ARN 인자는 TODO ⑤ 에서 채웁니다.

**TODO ③ — actor_id 에 sub**

```python
actor_id=user_sub,
```

`actor_id` 가 사용자 격리 키입니다. 이름 대신 Cognito `sub` 를 넣어 오독·개인정보 노출을 피합니다.

**TODO ④ — 추세 조회**

```python
memories = client.retrieve_memories(
```

`retrieve_memories` 가 네임스페이스에서 추출된 요약을 의미 검색으로 가져옵니다.

**TODO ⑤ — 실행 역할 인자 이름** (TODO ② 의 `create_memory_and_wait` 호출 안에 들어갑니다)

```python
memory_execution_role_arn=os.environ["MEMORY_ROLE"],
```

`summaryMemoryStrategy` 는 요약을 만들 때 Memory 가 사용자 계정에서 Bedrock 모델을 호출하므로,
그 권한을 주는 실행 역할 ARN 을 `memory_execution_role_arn` 인자로 넘겨야 합니다. 값은
`os.environ["MEMORY_ROLE"]` 에서 읽고, `MEMORY_ROLE` 은 실습 시작에서 core 스택 출력값
(`MemoryExecutionRoleArn`)으로 받은 값입니다. 실행할 때 `MEMORY_ROLE=$MEMORY_ROLE uv run python ...`
형태로 환경변수를 전달합니다(Step 4). 전달을 빠뜨리면 `os.environ` 조회가 `KeyError` 로 실패합니다.

### 요약

| # | 정답 | 설명 |
|---|------|------|
| ① | `MemoryClient` | AgentCore Memory 상위 SDK 클라이언트 |
| ② | `create_memory_and_wait` | ACTIVE 까지 대기하는 생성 |
| ③ | `user_sub` | 격리 키에 이름이 아닌 Cognito sub |
| ④ | `retrieve_memories` | 네임스페이스에서 요약 조회 |
| ⑤ | `memory_execution_role_arn` | 요약 전략이 모델을 호출하므로 실행 역할 인자 필요 |

</details>
