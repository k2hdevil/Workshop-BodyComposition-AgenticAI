# Lab 5: Runtime 배포 + Observability (25분)

## 학습 목표

Lab 2~4 에서 만든 에이전트를 AgentCore Runtime 에 **CodeZip(Direct Code Deploy)** 방식으로
배포하고, Observability 로 호출을 추적합니다. Docker 빌드 없이 zip 업로드만으로 배포합니다.

> **이 Lab 시작 시점의 코드 상태**: Supervisor(Lab 2)·Memory(Lab 3)·Guardrail(Lab 4)이
> 로컬에서 동작합니다. 이 Lab 은 이것들을 하나의 entrypoint 로 묶어 클라우드에 올립니다.
> Runtime 은 참가자가 직접 만듭니다.

---

## 이론: 왜 CodeZip 인가, 무엇을 추적하는가 (8분)

### CodeZip vs Container

| 방식 | 준비물 | 4시간 세션에서 |
|------|--------|----------------|
| **CodeZip (Direct Code Deploy)** | zip 아카이브 + entrypoint | **채택** — Docker 불필요, 콜드스타트 짧음 |
| Container | Dockerfile · ECR · ARM64 빌드 | 실패 지점이 많아 제외 |

Docker 빌드와 ECR push 는 4시간 세션에서 감당할 수 없는 실패 지점입니다. `uv` 기반 프로젝트면
AgentCore CLI 가 코드를 zip 으로 묶어 바로 배포합니다.

### 에이전트 4개가 하나의 Runtime인 이유

"멀티 에이전트라면 Runtime도 여러 개여야 하지 않나"라는 의문이 자연스럽게 생깁니다.
답은 **이 워크샵의 전문 에이전트 3개가 독립 서비스가 아니라 Supervisor 의 `@tool`** 이기
때문입니다.

```
Supervisor (Runtime 진입점)
  @tool analysis_specialist()   ← 같은 프로세스 내 함수 호출
  @tool exercise_specialist()   ← 같은 프로세스 내 함수 호출
  @tool nutrition_specialist()  ← 같은 프로세스 내 함수 호출
```

외부에서 보면 단일 엔드포인트, 내부에서는 Supervisor 가 세 에이전트를 순차로 조율합니다.
이것이 Lab 2 에서 배운 **Agent-as-Tool 패턴**이고, Runtime 은 이 Supervisor 를 호스팅하는
단위입니다.

> 프로덕션에서는 전문 에이전트를 각각 독립 Runtime 으로 분리하고 Supervisor 가 원격으로
> 호출하는 구조도 가능합니다. 그 경우 에이전트 간 격리·독립 확장·개별 배포가 가능하지만
> 네트워크 지연과 인증 복잡도가 추가됩니다. 이 워크샵은 4시간 제약과 개념 검증을 위해
> 단일 Runtime 을 선택합니다(Action Items 참고).

### Runtime 서비스 컨트랙트

에이전트는 두 가지만 만족하면 됩니다. `@app.entrypoint` 데코레이터를 쓰면 아래를 SDK 가
자동 처리합니다.

```
POST /invocations   요청 처리 (에이전트 본체)
GET  /ping          헬스 체크
```

### Observability 로 무엇을 보는가

호출 추적(trace), 지연, 토큰 사용, 도구 호출 순서를 봅니다. Supervisor 가 분석→운동→식단
순서로 도구를 호출하는지 트레이스로 확인할 수 있습니다. `aws-opentelemetry-distro` 가 자동
계측하고 X-Ray·CloudWatch 로 보냅니다. **이름은 트레이스에 넣지 않습니다**(경계 설계).

---

## 실습 시작

Runtime 실행 역할 ARN 을 core 스택에서 가져옵니다.

```bash
RUNTIME_ROLE=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-west-2 --query 'Stacks[0].Outputs[?OutputKey==`AgentRuntimeRoleArn`].OutputValue' \
  --output text)
echo "$RUNTIME_ROLE"
# 예상 출력: arn:aws:iam::<계정>:role/bca-workshop-agent-runtime-role
```

프로젝트 디렉터리와 의존성은 Step 1 의 `agentcore create` 가 모두 만들어 줍니다.
AgentCore CLI 가 아직 없다면 먼저 설치하세요.

```bash
npm install -g @aws/agentcore   # AgentCore CLI (이미 설치돼 있으면 건너뜁니다)
```

> **참고 — npm 설치 오류가 나도 CLI 가 이미 있을 수 있습니다.** 워크샵 이미지에는
> `@aws/agentcore` 가 사전 설치되어 있어, 재설치 시 기존 파일의 소유권 충돌로
> `EACCES` 오류가 날 수 있습니다. 오류가 보이면 CLI 가 실제로 동작하는지 먼저 확인하세요.
>
> ```bash
> agentcore --version   # 버전이 출력되면 정상 — npm 오류는 무시하고 다음 단계로 이동
> ```
>
> 명령을 찾지 못한다면 `sudo rm -rf ~/.nvm/versions/node/$(node -v)/lib/node_modules/@aws/agentcore`
> 로 기존 파일을 지운 뒤 `npm install -g @aws/agentcore` 를 다시 실행하세요.

### Step 1: 프로젝트 스캐폴드 — agentcore create

`agentcore dev` 와 `agentcore deploy` 는 모두 `agentcore.json` 이 있는 AgentCore 프로젝트
안에서만 동작합니다. 스캐폴드를 만들고, Lab 2~4 에서 작성한 코드를 프로젝트 안으로 합칩니다.

```bash
# 프로젝트 생성 (플래그로 대화형 질문을 건너뜁니다)
agentcore create \
  --project-name BcaWorkshop \
  --name BcaWorkshop \
  --language Python \
  --framework Strands \
  --model-provider Bedrock \
  --memory none \
  --build CodeZip

cd BcaWorkshop
```

`agentcore create` 가 완료되면 `app/BcaWorkshop/main.py` 와 `pyproject.toml` 이 생깁니다.
`pyproject.toml` 은 `app/BcaWorkshop/` 안에 있으므로, 의존성 추가는 그 안에서 합니다.
이제 Lab 2~4 에서 만든 코드를 앱 디렉터리로 복사하고 의존성을 합칩니다.

```bash
# Lab 2~4 코드를 앱 디렉터리로 복사합니다
# (각 lab 디렉터리와 BcaWorkshop/ 이 같은 부모 디렉터리에 있다고 가정)
cp ../lab2/agents.py app/BcaWorkshop/
cp ../lab3/memory_store.py app/BcaWorkshop/
cp ../lab4/guardrail.py app/BcaWorkshop/

# pyproject.toml 이 있는 디렉터리로 이동해 의존성을 추가합니다
cd app/BcaWorkshop
uv add strands-agents bedrock-agentcore boto3 aws-opentelemetry-distro
cd ../..   # BcaWorkshop/ 루트로 돌아옵니다 (agentcore dev/deploy 는 여기서 실행)
```

**정상 동작 확인**: `app/BcaWorkshop/` 안에 `main.py`, `agents.py`, `memory_store.py`,
`guardrail.py` 가 있고, `app/BcaWorkshop/uv.lock` 이 갱신됩니다.

### Step 2: Lab 2~4 통합 — Guardrail · Memory 연결

코드를 복사했으니 이제 각 Lab 의 기능을 실제로 연결합니다.

**Guardrail 연결 — `app/BcaWorkshop/agents.py` 상단 수정**

`agents.py` 에는 지금 이 두 줄이 있습니다.

```python
# 현재 (Lab 2 에서 작성한 그대로)
MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"   # ← 이 줄은 그대로 둡니다
model = BedrockModel(model_id=MODEL_ID, temperature=0.2)         # ← 이 줄만 교체합니다
```

`model = ...` 한 줄을 Guardrail 이 붙은 모델로 교체합니다. `MODEL_ID` 는 그대로 유지합니다.
`model` 은 세 전문 에이전트가 공유하므로 여기 한 곳만 바꾸면 에이전트 4개에 Guardrail 이
일괄 적용됩니다.

```python
# 위 한 줄을 아래 블록으로 교체합니다
import os
from guardrail import create_guardrail

# GUARDRAIL_ID 환경변수가 있으면 Lab 4 리소스를 재사용, 없으면 새로 생성합니다
_gid = os.environ.get("GUARDRAIL_ID")
_ver = os.environ.get("GUARDRAIL_VERSION")
if not _gid:
    _gid, _ver = create_guardrail()

# temperature=0.2 는 처방 일관성을 위한 설정 — Guardrail 추가 시에도 유지합니다
model = BedrockModel(
    model_id=MODEL_ID,
    guardrail_id=_gid,
    guardrail_version=_ver,
    temperature=0.2,
)
```

> `create_guardrail()` 은 매번 새 리소스를 만듭니다. 워크샵에서는 Lab 4 에서 이미 만든
> 리소스가 있으므로 `GUARDRAIL_ID` / `GUARDRAIL_VERSION` 환경변수로 재사용하는 것이 좋습니다.

```bash
# Lab 4 에서 만든 Guardrail ID·버전 조회
aws bedrock list-guardrails --region us-west-2 \
  --query 'guardrails[?name==`bca-safety`].[id,version]' --output table
```

배포·개발 서버 실행 시 환경변수로 넘깁니다:

```bash
export GUARDRAIL_ID=<Lab 4 에서 만든 guardrailId>
export GUARDRAIL_VERSION=<version, 보통 "DRAFT">
```

---

---

> **캐시는 Action Item 으로 남깁니다.** Lab 4 의 `cache_demo.py` 는 `boto3 converse()` 의
> `cachePoint` 를 직접 씁니다. Strands `BedrockModel` 은 현재 `cachePoint` 를 지원하지
> 않으므로, 전문 에이전트에 캐시를 붙이려면 Strands 의 raw Bedrock 클라이언트를 커스터마이징
> 해야 합니다. 이 워크샵의 시간 범위를 벗어나므로 `99_cleanup.md` 의 Action Items 에서
> 이어갑니다.

**정상 동작 확인**: `agents.py` 를 import 해도 오류가 없고, `GUARDRAIL_ID` 환경변수를 설정한
상태에서 `main.py` 를 실행하면 `create_guardrail` 이 다시 호출되지 않습니다.

### Step 3: entrypoint 작성 — Memory 연동 포함

`agentcore create` 가 생성한 `app/BcaWorkshop/main.py` 를 아래 내용으로 교체합니다.
TODO ①② 를 채우고, Step 2 에서 설정한 환경변수(`MEMORY_ID`)를 활용해 Memory 와 연결합니다.

```python
# app/BcaWorkshop/main.py
import os
from agents import coach
from memory_store import save_session

# TODO ①: AgentCore 앱 래퍼를 가져옵니다
from bedrock_agentcore import ________

app = BedrockAgentCoreApp()

MEMORY_ID = os.environ.get("MEMORY_ID")   # Lab 3 에서 만든 memory_id


# TODO ②: 이 함수를 Runtime 진입점으로 표시하세요
@app.________
def invoke(payload):
    """Runtime 진입점.

    Args:
        payload: {
            "measurement": {...},      # 정규화된 측정값
            "user_sub": "...",         # Cognito sub (사용자 격리 키, 이름 아님)
            "session_id": "..."        # 회차 식별자 (예: "session-2026-08-14")
        }
    """
    measurement = payload["measurement"]
    user_sub = payload.get("user_sub", "unknown")
    session_id = payload.get("session_id", "session-default")

    result = coach(measurement)

    # 코칭 완료 후 이번 회차를 Memory 에 저장합니다
    if MEMORY_ID and user_sub != "unknown":
        save_session(MEMORY_ID, user_sub, session_id, measurement)

    return {"result": result}


if __name__ == "__main__":
    app.run()
```

`MEMORY_ID` 환경변수를 설정합니다. Lab 3 에서 출력한 `memory_id` 를 복사해 쓰거나,
아래 명령으로 조회합니다. 응답의 `id` 필드에 생성 시 지정한 이름이 prefix 로 포함됩니다.

```bash
# 전체 Memory 목록 조회 — BodyCompositionTrend- 로 시작하는 id 를 찾습니다
aws bedrock-agentcore-control list-memories \
  --query 'memories[?contains(id, `BodyCompositionTrend`)].id' \
  --output text

export MEMORY_ID=<위 명령 출력값>
```

> **캐시 통합**: Strands `BedrockModel` 은 `CacheConfig` 를 통해 프롬프트 캐시를 지원합니다.
> `agents.py` 에서 `model` 생성 시 `cache_config=CacheConfig(strategy="auto")` 를 추가하면
> 시스템 프롬프트와 도구 정의를 자동으로 캐시합니다. `CacheConfig` 를 import 한 뒤 아래처럼
> 추가하세요.
>
> ```python
> from strands.models.bedrock import BedrockModel, CacheConfig
>
> model = BedrockModel(
>     model_id=MODEL_ID,
>     guardrail_id=_gid,
>     guardrail_version=_ver,
>     temperature=0.2,
>     cache_config=CacheConfig(strategy="auto"),   # 시스템 프롬프트·도구 정의 자동 캐시
> )
> ```
>
> Claude Sonnet 4.5 기준 캐시 최소 토큰은 1,024 입니다. `strategy="auto"` 는 Bedrock 이
> 캐시 가능한 prefix 를 자동으로 판단합니다.

### Step 4: 로컬 테스트

배포 전에 로컬에서 서비스 컨트랙트를 확인합니다.
Step 2 에서 설정한 환경변수를 함께 넘깁니다.

> **포트 충돌 시**: 워크샵 환경에서 8080·8081 은 이미 사용 중일 수 있습니다. `--port` 로
> 다른 포트를 지정하고 curl 도 같은 포트를 쓰세요.

```bash
# 터미널 1 — BcaWorkshop/ 루트에서 실행
GUARDRAIL_ID=$GUARDRAIL_ID GUARDRAIL_VERSION=$GUARDRAIL_VERSION \
MEMORY_ID=$MEMORY_ID \
agentcore dev --port 8082 --no-browser
```

터미널을 하나 더 열어 curl 을 실행합니다.

```bash
# 터미널 2
curl -X POST http://localhost:8082/invocations \
  -H "Content-Type: application/json" \
  -d '{"measurement": {"obesity_analysis": {"pbf_percent": {"value": 32.5}}}}'
# Supervisor 가 에이전트 3개를 순차 호출하므로 응답까지 수십 초가 걸립니다
# 예상: {"result": "...소견/운동/식단..."}
```

**정상 동작 확인**: `/invocations` 가 200 과 `result` 를 반환합니다.
확인 후 터미널 1에서 `Ctrl+C` 로 서버를 종료합니다.

### Step 5: Observability 활성화

CloudWatch Transaction Search 를 켠 뒤 배포하면 트레이스가 수집됩니다. 이미 의존성에
`aws-opentelemetry-distro` 를 넣었으므로 자동 계측됩니다.

```bash
# CloudWatch Transaction Search 활성화 (계정에서 한 번)
aws xray update-trace-segment-destination \
  --destination CloudWatchLogs --region us-west-2
```

### Step 6: 배포와 호출

실행 역할을 지정해 배포합니다.

```bash
# 배포 — uv 프로젝트라 Direct Code Deploy(zip)로 배포됩니다
# TODO ③: 배포 명령을 완성하세요
agentcore ________ --execution-role "$RUNTIME_ROLE"
```

배포가 끝나면 호출합니다.

```bash
agentcore invoke '{"measurement": {"obesity_analysis": {"pbf_percent": {"value": 32.5}}}}'
# 예상: {"result": "...코칭 결과..."}
```

**정상 동작 확인**: `agentcore invoke` 가 코칭 결과를 반환하고, CloudWatch 콘솔의
Transaction Search 에서 이 호출의 트레이스(도구 호출 순서 포함)가 보입니다.

---

## 검증

- [ ] `agentcore dev` 로 로컬 `/invocations` 가 200 반환
- [ ] `agents.py` 의 `model` 이 Guardrail 인자(`guardrail_id`, `guardrail_version`)를 포함한 `BedrockModel` 로 교체됨
- [ ] `main.py` 의 `invoke` 가 `save_session()` 을 호출함 (Memory 연결)
- [ ] `main.py` 에 `@app.entrypoint` 진입점 존재
- [ ] 배포 시 `AgentRuntimeRoleArn` 을 실행 역할로 지정
- [ ] `agentcore invoke` 가 코칭 결과 반환
- [ ] CloudWatch Transaction Search 에 호출 트레이스가 수집됨
- [ ] 트레이스·로그에 사용자 이름이 없음(경계 확인)

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| 배포가 Container 방식으로 감 | uv 미사용 | uv 프로젝트인지 확인. `uv.lock` 존재 시 CodeZip 권장 |
| `agentcore dev` 가 포트 오류 | 8080 사용 중 | `--port 8082` 등 다른 포트 지정 후 curl 도 같은 포트로 |
| `Unsupported method POST` 응답 | 다른 프로세스가 해당 포트 점유 | `lsof -i :8082` 로 사용 중인 포트 확인 후 빈 포트 사용 |
| curl 응답이 너무 오래 걸림 | Supervisor 가 에이전트 3개 순차 호출 | 정상. 수십 초 기다리세요 |
| 배포가 AccessDenied | 실행 역할 권한 부족 | `AgentRuntimeRoleArn` 을 지정했는지 확인. 임의 역할 금지 |
| `invoke` 가 ModuleNotFound (agents) | Lab 2 코드 미복사 | Step 1 의 `cp ../lab2/agents.py app/BcaWorkshop/` 를 실행했는지 확인 |
| 트레이스가 안 보임 | Transaction Search 미활성 | Step 5 명령 실행 후 재배포. 수집까지 수 분 지연 |
| `ImportError: guardrail` | guardrail.py 미복사 | Step 1 의 `cp ../lab4/guardrail.py app/BcaWorkshop/` 확인 |
| `ImportError: memory_store` | memory_store.py 미복사 | Step 1 의 `cp ../lab3/memory_store.py app/BcaWorkshop/` 확인 |
| Guardrail 이 매 시작마다 새로 생성됨 | GUARDRAIL_ID 환경변수 미설정 | Step 2 안내대로 `export GUARDRAIL_ID=...` 설정 |
| 콜드스타트가 김 | 첫 배포는 의존성 설치 | 이후 업데이트는 zip 의존성 재사용으로 빨라짐 |

---

## 🏆 Challenge Task

1. **세션 유지** — `agentcore invoke` 에 세션 ID 를 넘겨 Lab 3 Memory 와 연결하고, 같은
   사용자의 두 번째 호출에서 이전 회차를 참조하는지 트레이스로 확인하세요.
2. **지연 분해** — 트레이스에서 추출 도구(결정적)와 에이전트 호출(LLM)의 지연을 분리해
   보고, 어디에 시간이 쓰이는지 근거로 설명하세요.

---

완료 후 [Lab 6: Streamlit + ECS Express Mode](./06_frontend.md)로 이동하세요.

---

## 부록: 정답 코드

<details>
<summary>agent_runtime.py · 배포 TODO ①~③ 정답 (클릭하여 펼치기)</summary>

**TODO ① — 앱 래퍼 import**

```python
from bedrock_agentcore import BedrockAgentCoreApp
```

`BedrockAgentCoreApp` 이 HTTP 서버(`/invocations`, `/ping`)를 대신 처리합니다.

**TODO ② — 진입점 데코레이터**

```python
@app.entrypoint
def invoke(payload):
```

`@app.entrypoint` 가 이 함수를 `/invocations` 핸들러로 등록합니다. 서버 코드를 직접 쓰지
않아도 됩니다.

**TODO ③ — 배포 명령**

```python
agentcore deploy --execution-role "$RUNTIME_ROLE"
```

`agentcore deploy` 가 코드를 zip 으로 묶어 업로드·배포합니다. uv 프로젝트라 Direct Code
Deploy 로 진행되고, 실행 역할은 사전 프로비저닝된 `AgentRuntimeRoleArn` 을 씁니다.

### 요약

| # | 정답 | 설명 |
|---|------|------|
| ① | `BedrockAgentCoreApp` | HTTP 서비스 컨트랙트 래퍼 |
| ② | `entrypoint` | `/invocations` 진입점 등록 |
| ③ | `deploy` | zip 패키징·업로드·배포 |

</details>
