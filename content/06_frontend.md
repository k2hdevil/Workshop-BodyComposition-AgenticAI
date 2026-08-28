# Lab 6: Streamlit 프론트엔드 + ECS Express Mode (25분)

## 학습 목표

Streamlit 앱에 Cognito OIDC 로그인을 붙이고, 로그인 사용자의 이름·액세스 토큰을 꺼내
에이전트와 Gateway 를 호출하는 화면을 만듭니다. 완성한 앱을 컨테이너로 만들어 ECS Express
Mode 로 배포해 HTTPS 로 접속합니다.

> **이 Lab 시작 시점의 코드 상태**: Runtime 에이전트(Lab 5)가 배포되어 있고, Gateway 는
> 액세스 토큰을 요구합니다(00_setup). 이 Lab 은 그 앞단의 웹 화면을 만들어 배포까지 합니다.

---

## 이론: 왜 ECS Express Mode 이고, 토큰 경계는 무엇인가 (7분)

### 프론트엔드 배포 대상: ECS Express Mode

Streamlit 을 HTTPS 로 서빙하려면 관리형 배포가 필요합니다. **AWS App Runner 는 신규 고객
접수를 종료**했으므로(워크샵 임시 계정은 신규 계정이라 사용 불가), 그 대체로 **Amazon ECS
Express Mode** 를 씁니다. 컨테이너 이미지 하나만 주면 Fargate 서비스·로드밸런서(SSL/TLS)·
오토스케일·고유 URL 을 자동으로 구성합니다.

| 항목 | ECS Express Mode |
|------|------------------|
| 입력 | **컨테이너 이미지** + 실행 역할 2개 |
| 자동 구성 | Fargate 서비스, ALB(HTTPS), 오토스케일, URL |
| URL 형식 | `https://<서비스명>.ecs.us-east-1.on.aws/` |
| 요금 | Express 자체 무과금 (Fargate·ALB·CloudWatch·데이터전송만) |

> **컨테이너는 프론트엔드에만 씁니다.** 에이전트 Runtime 은 Lab 5 에서 정한 대로 **CodeZip**
> 을 유지합니다(Docker 빌드가 4시간 세션의 실패 지점이라서). 프론트는 Streamlit 한 개만
> 얇게 컨테이너화하므로(Dockerfile 6줄), ECR push 한 번이면 됩니다.

### `st.login()` 은 authorization code 흐름을 씁니다

Streamlit 1.42+ 의 `st.login()` 이 Cognito 로 리다이렉트해 로그인을 처리합니다. 콜백 경로는
**`/oauth2callback` 로 끝나야** 합니다(사전 프로비저닝된 Cognito App Client 의 콜백 URL 이
이 규칙에 맞춰져 있습니다).

### 화면에는 이름, 에이전트에는 토큰

경계 설계(README)를 화면 단에서 마무리합니다.

| 무엇 | 어디서 | 처리 |
|------|--------|------|
| 사용자 이름 | Cognito 프로필 | **화면에만** 표시 |
| 액세스 토큰 | `st.user` | Gateway 호출에 사용 |
| 결과지 이름 | 추출 결과 | 로그인 이름과 **대조만**(본인 확인) |

### Gateway 는 액세스 토큰을 요구합니다

ID 토큰은 403(`insufficient_scope`)입니다. 기본값은 아무 토큰도 노출하지 않으므로,
`secrets.toml` 의 `expose_tokens` 에 `"access"` 를 넣어야 토큰을 꺼낼 수 있습니다.

> **주의(재확인 필요)**: `st.login()` 의 authorization-code 흐름이 발급하는 액세스 토큰
> (`scope: openid email profile`)이 Gateway 를 통과하는지는 아직 브라우저 흐름으로 실측하지
> 못했습니다. CLI 로 확인한 것은 `admin-initiate-auth` 토큰입니다. 통과하지 않으면 Gateway
> 호출은 Runtime 경유로 우회하고, 이 Lab 의 로그인·업로드·화면 부분은 그대로 진행됩니다.

---

## 실습 시작

```bash
mkdir -p lab6 && cd lab6
uv init --python 3.13 .
uv add streamlit boto3
```

core 스택에서 인증 값들을 가져옵니다.

```bash
POOL_ID=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' --output text)
CLIENT_ID=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' --output text)
OIDC_URL=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`OIDCDiscoveryUrl`].OutputValue' --output text)
# client secret 조회 명령은 GetClientSecretCommand 출력값에 있습니다
CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client \
  --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" --region us-east-1 \
  --query 'UserPoolClient.ClientSecret' --output text)
echo "OIDC: $OIDC_URL"
```

### Step 1: secrets.toml — 토큰 노출 설정

`lab6/.streamlit/secrets.toml` 을 만듭니다. 위에서 받은 값을 채웁니다.

```toml
# lab6/.streamlit/secrets.toml
[auth]
redirect_uri = "http://localhost:8501/oauth2callback"
cookie_secret = "임의의-긴-랜덤-문자열로-교체"
client_id = "<CLIENT_ID>"
client_secret = "<CLIENT_SECRET>"
server_metadata_url = "<OIDC_URL>"

# TODO ①: Gateway 가 요구하는 토큰을 노출하도록 설정하세요
# - 기본값은 아무 토큰도 노출하지 않습니다. Gateway 는 액세스 토큰을 요구합니다
expose_tokens = ["________"]
```

### Step 2: 로그인 화면

`lab6/app.py` 를 만듭니다.

```python
# lab6/app.py
import json

import boto3
import streamlit as st

st.set_page_config(page_title="체성분 코칭")

# TODO ②: 로그인하지 않은 사용자를 Cognito 로 보냅니다
if not st.user.is_logged_in:
    st.title("체성분 분석 코칭")
    st.write("계속하려면 로그인하세요.")
    if st.button("로그인"):
        st.________()   # Cognito OIDC 로그인 시작
    st.stop()

# 로그인 이후: 이름은 화면에만 표시합니다
display_name = st.user.name
st.sidebar.write(f"안녕하세요, {display_name} 님")
if st.sidebar.button("로그아웃"):
    st.logout()
```

### Step 3: 업로드 + 본인 확인 + 호출

업로드한 결과지에서 추출한 이름과 로그인 이름을 대조합니다(Lab 1 의 편집거리 판정 재사용).

```python
# lab6/app.py (이어서)

REGION = "us-east-1"

uploaded = st.file_uploader("체성분 결과지 PDF 업로드", type="pdf")
if uploaded is not None:
    # (추출은 Lab 1 도구/Gateway 로. 여기서는 결과에 sheet_name, measurement 가 있다고 가정)
    result = {"sheet_name": "김도현", "measurement": {}}   # 데모용 자리표시자

    # TODO ③: 로그인 이름과 결과지 이름을 대조하는 본인 확인 판정을 받습니다
    from identity import verify_identity   # Lab 1 의 편집거리 판정 재사용
    verdict = verify_identity(display_name, result["________"])

    if verdict == "BLOCK":
        st.error("업로드한 결과지의 이름이 로그인 사용자와 다릅니다. 본인 결과지만 분석할 수 있습니다.")
        st.stop()
    elif verdict == "WARN":
        st.warning("결과지 이름이 로그인 사용자와 근소하게 다릅니다(스캔 오독 가능). 본인 결과지가 맞는지 확인하세요.")

    # 액세스 토큰을 꺼내 에이전트/Gateway 호출에 사용합니다
    # TODO ④: 노출된 액세스 토큰을 꺼냅니다
    access_token = st.user.get("________")

    st.success("본인 확인 완료. 분석을 요청합니다.")
    # 여기서 Runtime(agentcore invoke) 또는 Gateway 를 access_token 과 함께 호출합니다
    # 이름은 넘기지 않습니다(경계 설계) — measurement 만 전달
    st.json({"has_token": bool(access_token)})
```

### Step 4: 컨테이너 이미지 만들기

ECS Express Mode 는 컨테이너 이미지를 입력으로 받습니다. Streamlit 을 담는 얇은 `Dockerfile`
을 만듭니다.

```dockerfile
# lab6/Dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir streamlit boto3

# TODO ⑤: Streamlit 이 실제로 여는 포트를 노출하세요(기본 8501)
EXPOSE ________

# 컨테이너 안에서는 0.0.0.0 으로 바인딩해야 로드밸런서가 도달합니다
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", "--server.address=0.0.0.0"]
```

로컬에서 먼저 로그인·업로드 흐름을 확인합니다(컨테이너 없이).

```bash
uv run streamlit run app.py
# 브라우저에서 로그인 → 결과지 업로드 → 본인 확인 메시지 확인
```

ECR 리포지토리를 만들고 이미지를 올립니다.

```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REPO="bca-workshop-frontend"
aws ecr create-repository --repository-name "$REPO" --region us-east-1

aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.us-east-1.amazonaws.com"

IMAGE="$ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/$REPO:latest"
# Express Mode 는 CPU 아키텍처를 지정하는 옵션이 없어 Fargate 기본값(x86_64)으로 태스크를
# 띄웁니다. Apple Silicon(arm64) 등에서 빌드하면 반드시 --platform linux/amd64 를 붙이세요.
# (아키텍처가 어긋나면 태스크가 exec format error 로 기동하지 못합니다 — 실측 확인)
docker build --platform linux/amd64 -t "$IMAGE" .
docker push "$IMAGE"
echo "IMAGE=$IMAGE"
```

**정상 동작 확인**: `docker push` 가 성공하고 `ecr describe-images` 에 `latest` 태그가 보입니다.

### Step 5: ECS Express Mode 서비스 생성

Express Mode 는 실행 역할 2개를 요구합니다. 계정에 없으면 한 번 만듭니다(AWS 관리형 정책 사용).

```bash
# Task Execution Role — 이미지 pull·로그 기록
aws iam create-role --role-name ecsTaskExecutionRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}' 2>/dev/null || true
aws iam attach-role-policy --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# Infrastructure Role — Express 가 ALB·오토스케일을 구성
aws iam create-role --role-name ecsInfrastructureRoleForExpressServices \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs.amazonaws.com"},"Action":"sts:AssumeRole"}]}' 2>/dev/null || true
aws iam attach-role-policy --role-name ecsInfrastructureRoleForExpressServices \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices
```

서비스를 생성합니다. Streamlit 은 8501 포트를 쓰고 헬스체크 경로는 `/_stcore/health` 입니다.

```bash
aws ecs create-express-gateway-service \
  --service-name bca-frontend \
  --primary-container "{\"image\":\"$IMAGE\",\"containerPort\":8501}" \
  --execution-role-arn "arn:aws:iam::$ACCOUNT:role/ecsTaskExecutionRole" \
  --infrastructure-role-arn "arn:aws:iam::$ACCOUNT:role/ecsInfrastructureRoleForExpressServices" \
  --health-check-path "/_stcore/health" \
  --monitor-resources \
  --region us-east-1
# 상태가 ACTIVE 가 되면 서비스 URL 이 반환됩니다. URL 접두사는 서비스명이 아니라
# Express 가 붙이는 `bc-<해시>` 형태입니다 (실측 예):
#   https://bc-00fcb754df8d4f21ade08f2e3542727e.ecs.us-east-1.on.aws/
```

> IAM 역할은 생성 직후 전파에 시간이 걸립니다. 첫 호출이 assume-role 오류로 실패하면 약 1분
> 뒤 다시 시도하세요.

### Step 6: 콜백 URL 갱신

Express 가 발급한 URL 로 Cognito 콜백을 갱신합니다. URL 은 배포 전에는 알 수 없으므로 배포
후에 스택 파라미터를 업데이트합니다.

서비스 URL 은 Step 5 의 `create-express-gateway-service` 출력에 포함됩니다. 나중에 다시
확인하려면 `describe-express-gateway-service` 를 쓰는데, 이 명령은 서비스 이름이 아니라
**`--service-arn`** 을 받습니다. ARN 을 모르면 `list-services` 로 먼저 찾습니다.

```bash
# 서비스 ARN 을 이름으로 찾기 (describe 는 --service-arn 만 받으므로 ARN 을 먼저 확보)
SERVICE_ARN=$(aws ecs list-services --region us-east-1 \
  --query "serviceArns[?contains(@, 'bca-frontend')]" --output text)

# 서비스 URL 조회 (또는 Step 5 의 create 출력에서 복사)
# URL 은 service.url 이 아니라 활성 구성의 ingressPaths[].endpoint 에 있습니다
APP_URL=$(aws ecs describe-express-gateway-service \
  --service-arn "$SERVICE_ARN" --region us-east-1 \
  --query 'service.activeConfigurations[0].ingressPaths[0].endpoint' --output text)
echo "$APP_URL"   # 예: https://bc-00fcb754df8d4f21ade08f2e3542727e.ecs.us-east-1.on.aws

# TODO ⑥: 콜백 URL 파라미터를 실제 서비스 URL 로 갱신합니다(경로는 /oauth2callback)
aws cloudformation deploy \
  --template-file infra/01-core.yaml \
  --stack-name bca-workshop-core \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1 \
  --parameter-overrides ________="$APP_URL/oauth2callback"
```

배포된 앱에서는 `secrets.toml` 의 `redirect_uri` 도 `$APP_URL/oauth2callback` 로 맞춰
이미지를 다시 빌드·push 하고 서비스를 업데이트합니다.

**정상 동작 확인**: 서비스 URL(`*.ecs.us-east-1.on.aws`)로 접속해 Cognito 로그인이 되고,
로그인 후 이름이 화면에 표시되며 업로드 시 본인 확인 메시지가 뜹니다.

---

## 검증

- [ ] `secrets.toml` 의 `expose_tokens` 에 `"access"` 포함
- [ ] 콜백 경로가 `/oauth2callback` 로 끝남
- [ ] `Dockerfile` 의 `EXPOSE` 포트와 `--server.port` 가 8501 로 일치
- [ ] 이미지가 ECR 에 push 되고 Express 서비스가 `ACTIVE`
- [ ] 로그인 후 사용자 이름이 화면에만 표시(에이전트 페이로드에는 없음)
- [ ] 업로드 시 본인 확인이 PASS/WARN/BLOCK 로 분기
- [ ] 서비스 URL(`*.ecs.us-east-1.on.aws`)로 HTTPS 접속·로그인 성공
- [ ] `HostedCallbackUrl` 파라미터가 실제 서비스 URL 로 갱신됨

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| 로그인 후 redirect_uri mismatch | 콜백 URL 불일치 | Cognito App Client 콜백과 `redirect_uri` 를 `/oauth2callback` 로 일치 |
| 토큰을 꺼낼 수 없음 | `expose_tokens` 누락 | `secrets.toml` 에 `expose_tokens = ["access"]` 추가 |
| Gateway 호출 403 | ID 토큰 사용 | 액세스 토큰을 넘김. 그래도 실패 시 Runtime 경유로 우회 |
| `st.login` 이 없음 | Streamlit 버전 낮음 | Streamlit 1.42+ 로 업그레이드 |
| Express 생성이 assume-role 오류 | IAM 역할 전파 지연 | 약 1분 후 재시도 |
| 헬스체크 실패로 ACTIVE 안 됨 | 포트·경로 불일치 | `containerPort` 8501, `--health-check-path /_stcore/health` 확인 |
| 태스크가 `exec format error` 로 안 뜸 | arm64 이미지를 x86 Fargate 에 배포 | `--platform linux/amd64` 로 다시 빌드·push |
| `create-express-gateway-service` 가 VPC 오류 | 기본 VPC 없음 | 기본 VPC 생성 또는 `--subnets` 로 서브넷 지정 |
| create 가 `Role is not valid` | 역할 전파 지연 또는 ARN 문자열 손상 | 1분 후 재시도. ARN 이 `:role/` 온전한지 확인(셸 변수 조립 시 깨질 수 있음) |
| 배포 후 로그인 실패 | 콜백이 로컬 URL | Step 6 의 스택 파라미터 갱신 실행 |
| 화면에 결과지 이름이 뜸 | 표시용/검증용 혼동 | 화면에는 Cognito 이름만. 결과지 이름은 대조에만 |

---

## 🏆 Challenge Task

1. **추이 차트** — Lab 3 Memory 에서 회차별 체중·체지방을 읽어 `st.line_chart` 로 그리세요.
   사용자 격리는 `st.user` 의 `sub` 로 합니다.
2. **보고서 다운로드** — 코칭 결과를 PDF 로 만들어 `st.download_button` 으로 내려받게 하세요
   (in-process fpdf2 + 한글 TTF).

---

완료 후 [Lab 7: Evaluations](./07_evaluation.md)로 이동하세요.

---

## 부록: 정답 코드

<details>
<summary>secrets.toml · app.py · Dockerfile · 배포 TODO ①~⑥ 정답 (클릭하여 펼치기)</summary>

**TODO ① — 액세스 토큰 노출**

```toml
expose_tokens = ["access"]
```

Gateway 는 액세스 토큰을 요구합니다. 기본값은 아무 토큰도 노출하지 않으므로 명시해야 합니다.

**TODO ② — 로그인 시작**

```python
st.login()
```

`st.login()` 이 Cognito authorization code 흐름으로 리다이렉트합니다.

**TODO ③ — 결과지 이름 키**

```python
verdict = verify_identity(display_name, result["sheet_name"])
```

추출 결과의 결과지 이름을 로그인 이름과 대조합니다. 완전일치/편집거리1/그외로 분기(Lab 1).

**TODO ④ — 액세스 토큰 추출**

```python
access_token = st.user.get("access")
```

`expose_tokens` 에 노출한 키 이름(`access`)으로 토큰을 꺼냅니다.

**TODO ⑤ — 컨테이너 포트**

```dockerfile
EXPOSE 8501
```

Streamlit 기본 포트는 8501 입니다. `--server.port=8501`, Express 의 `containerPort` 8501,
`EXPOSE 8501` 이 모두 같아야 로드밸런서가 컨테이너에 도달합니다.

**TODO ⑥ — 콜백 파라미터 갱신**

```python
--parameter-overrides HostedCallbackUrl="$APP_URL/oauth2callback"
```

배포 후 얻은 ECS Express 서비스 URL 로 `HostedCallbackUrl` 을 갱신합니다. 경로는
`/oauth2callback`, URL 형식은 `https://<서비스명>.ecs.us-east-1.on.aws`.

### 요약

| # | 정답 | 설명 |
|---|------|------|
| ① | `access` | Gateway 가 요구하는 액세스 토큰 노출 |
| ② | `st.login` | Cognito OIDC 로그인 시작 |
| ③ | `sheet_name` | 본인 확인용 결과지 이름 |
| ④ | `access` | 노출된 액세스 토큰 키 |
| ⑤ | `8501` | Streamlit 포트(EXPOSE·server.port·containerPort 일치) |
| ⑥ | `HostedCallbackUrl` | 배포 후 콜백 URL 파라미터 |

</details>
