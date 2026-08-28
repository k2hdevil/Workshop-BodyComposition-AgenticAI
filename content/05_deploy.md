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
  --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`AgentRuntimeRoleArn`].OutputValue' \
  --output text)
echo "$RUNTIME_ROLE"
# 예상 출력: arn:aws:iam::<계정>:role/bca-workshop-agent-runtime-role
```

프로젝트를 만들고 의존성을 설치합니다.

```bash
mkdir -p lab5 && cd lab5
uv init --python 3.13 .
uv add bedrock-agentcore strands-agents aws-opentelemetry-distro
npm install -g @aws/agentcore   # AgentCore CLI
```

### Step 1: entrypoint 작성

`lab5/agent_runtime.py` 를 만듭니다. Lab 2 의 `coach()` 를 호출하는 진입점입니다.

```python
# lab5/agent_runtime.py
# from agents import coach   # Lab 2 의 Supervisor 조율 함수 (같은 프로젝트에 복사)

# TODO ①: AgentCore 앱 래퍼를 가져옵니다
from bedrock_agentcore import ________

app = BedrockAgentCoreApp()


# TODO ②: 이 함수를 Runtime 진입점으로 표시하세요
@app.________
def invoke(payload):
    """Runtime 진입점. payload 로 측정값을 받아 코칭 결과를 반환합니다.

    Args:
        payload: {"measurement": {...}} 형태의 요청 본문.
    """
    measurement = payload["measurement"]
    # 이름은 에이전트로 넘기기 전에 제거합니다(경계 설계). coach 내부에서도 재확인.
    result = coach(measurement)   # Lab 2 의 Supervisor
    return {"result": result}


if __name__ == "__main__":
    app.run()
```

> `coach` 는 Lab 2 `agents.py` 의 함수입니다. 이 프로젝트로 `agents.py` 를 복사해 오거나
> import 경로를 맞추세요. Guardrail(Lab 4)을 붙인 모델을 쓰면 안전 장치가 함께 배포됩니다.

### Step 2: 로컬 테스트

배포 전에 로컬에서 서비스 컨트랙트를 확인합니다.

```bash
agentcore dev --no-browser
# 다른 터미널에서:
curl -X POST http://localhost:8080/invocations \
  -H "Content-Type: application/json" \
  -d '{"measurement": {"obesity_analysis": {"pbf_percent": {"value": 32.5}}}}'
# 예상: {"result": "...소견/운동/식단..."}
```

**정상 동작 확인**: `/invocations` 가 200 과 `result` 를 반환합니다. 확인 후 `Ctrl+C`.

### Step 3: Observability 활성화

CloudWatch Transaction Search 를 켠 뒤 배포하면 트레이스가 수집됩니다. 이미 의존성에
`aws-opentelemetry-distro` 를 넣었으므로 자동 계측됩니다.

```bash
# CloudWatch Transaction Search 활성화 (계정에서 한 번)
aws xray update-trace-segment-destination \
  --destination CloudWatchLogs --region us-east-1
```

### Step 4: 배포와 호출

`agentcore create` 로 스캐폴드를 만들고(프레임워크는 Strands 선택), 실행 역할을 지정한 뒤
배포합니다.

```bash
# 스캐폴드 (프레임워크: Strands Agents 선택)
agentcore create

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
- [ ] `agent_runtime.py` 에 `@app.entrypoint` 진입점 존재
- [ ] 배포 시 `AgentRuntimeRoleArn` 을 실행 역할로 지정
- [ ] `agentcore invoke` 가 코칭 결과 반환
- [ ] CloudWatch Transaction Search 에 호출 트레이스가 수집됨
- [ ] 트레이스·로그에 사용자 이름이 없음(경계 확인)

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| 배포가 Container 방식으로 감 | uv 미사용 | uv 프로젝트인지 확인. `uv.lock` 존재 시 CodeZip 권장 |
| `agentcore dev` 가 포트 오류 | 8080 사용 중 | 8080 을 쓰는 프로세스 종료 후 재실행 |
| 배포가 AccessDenied | 실행 역할 권한 부족 | `AgentRuntimeRoleArn` 을 지정했는지 확인. 임의 역할 금지 |
| `invoke` 가 ModuleNotFound (agents) | Lab 2 코드 미포함 | `agents.py` 를 프로젝트에 복사했는지 확인 |
| 트레이스가 안 보임 | Transaction Search 미활성 | Step 3 명령 실행 후 재배포. 수집까지 수 분 지연 |
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
