# 00. 오프닝 · 환경 확인 (25분)

> 이 문서는 Lab 이 아니라 **오프닝 이론(25분)** 입니다. 그래서 Lab 필수 골격 중
> `🏆 Challenge Task` 와 `부록: 정답 코드` 는 두지 않습니다. 참가자가 코드를 작성하는
> 구간이 없기 때문입니다. 대신 배포·업로드·토큰 획득은 **확인 절차**로 다룹니다.

## 학습 목표

체성분 분석 앱이 무엇을 푸는지 이해하고, 사전 프로비저닝된 리소스를 배포·확인하여
Lab 1 을 시작할 수 있는 상태(스택 2개 · 샘플 4건 · 액세스 토큰)를 만듭니다.

---

## 이론 1: 무엇을 만드는가 (12분)

사용자가 자신의 **체성분 분석 결과지 PDF** 를 올리면, 여러 에이전트(Agent)가 협업해
분석하고 회차 간 변화를 추적하며 운동·식단을 제안하는 웹 앱을 만듭니다. 4시간 안에
"돌아가는 것을 AWS 에 배포"까지 도달하는 것이 목표입니다.

```
사용자(브라우저) ─ Cognito 로그인 ─▶ Streamlit(ECS Express)
                                        │  액세스 토큰
                                        ▼
                                 AgentCore Runtime
                                   Supervisor Agent
                        ┌──────────────┼───────────────┐
                        ▼              ▼               ▼
                    체성분 분석      운동 처방        식단 제안
                     에이전트        에이전트         에이전트
                        │  (분석 → 운동 → 식단 순차 체이닝)
             ┌──────────┴───────────┐
             ▼                      ▼
      AgentCore Gateway       AgentCore Memory
       결과지 추출(λ)          회차별 측정 이력
```

에이전트는 **4개**입니다(Supervisor + 전문 3개). 도구(tool)는 5개입니다.

### 왜 결과지 추출은 에이전트가 아니라 도구인가

이 워크샵의 첫 설계 결정이자 교육 포인트입니다.

| 작업 성격 | 예 | 적합한 구현 |
|-----------|-----|-------------|
| 결정적(deterministic) | PDF 에서 숫자 뽑기, BMI 재계산 | **도구** — LLM 루프 불필요 |
| 판단이 필요 | 소견 해석, 운동·식단 제안 | 에이전트 |

같은 PDF 에서 매번 다른 값이 나오면 안 됩니다. 결정적 작업에 LLM 루프를 씌우면 지연·비용·
비결정성만 늘어납니다. 그래서 추출은 **도구**로 둡니다. 이 판단을 Lab 1 에서 두 경로의
토큰 사용량으로 직접 확인합니다.

### 샘플 데이터 — 같은 사람 3회 + 다른 사람 1회

| 문서 | 인물 | 형식 | 역할 |
|------|------|------|------|
| `user-a-session-01` | 김도현 44세 남 | **스캔본** | 추이 기준선 · 비만 |
| `user-a-session-02` | 김도현 | 디지털 | 개선 진행 |
| `user-a-session-03` | 김도현 | 디지털 | 최근 · 델타 분석 |
| `user-b-session-01` | 박지은 32세 여 | 디지털 | 다른 사용자 · D자형 함정 |

추이 분석은 서로 다른 두 사람으로 검증할 수 없어 같은 사람의 3회차가 필요합니다.
1회차는 **텍스트 레이어가 없는 스캔본**이라 구조 파서만으로는 실패합니다(Lab 1 에서 폴백 확인).

> 본 워크샵의 결과지는 전부 **가상의 합성 데이터**입니다. "인바디"는 (주)인바디의 등록
> 상표이며, 본 저장소는 일반명 **체성분 분석(body composition)** 을 사용합니다.

---

## 이론 2: AgentCore 구성 요소 (13분)

Amazon Bedrock AgentCore 는 에이전트를 운영하기 위한 관리형 구성 요소의 모음입니다.
이번 워크샵에서 쓰는 5개만 정리합니다.

| 구성 요소 | 역할 | 이 워크샵에서 | 만드는 주체 |
|-----------|------|---------------|-------------|
| **Runtime** | 에이전트 실행 환경 | Supervisor + 전문 에이전트 호스팅 | 참가자(Lab 5) |
| **Gateway** | 도구를 MCP 로 노출 | Lambda 추출기를 MCP 도구로 | 사전 프로비저닝 |
| **Memory** | 대화·이벤트 장기 기억 | 회차별 측정 이력 | 참가자(Lab 3) |
| **Identity** | 인바운드/아웃바운드 인증 | Cognito JWT 인바운드 | 사전 프로비저닝 |
| **Observability** | 추적·로그·메트릭 | X-Ray · CloudWatch | 참가자(Lab 5) |

> Memory · Guardrail · Runtime 은 **참가자가 직접 만듭니다.** 전략 설계와 정책 설계가
> 학습의 본체라서 템플릿에 박아두면 읽고 지나갈 뿐입니다. 반면 Gateway · Cognito 는
> 이미 만들어진 것에 **연결하고 확인**하는 데까지만 다룹니다(4시간 제약의 의도적 선택).

### Agent-as-Tool 패턴

Supervisor 가 전문 에이전트를 **도구처럼 호출**합니다. 각 전문 에이전트를 `@tool` 로
감싸면, Supervisor 입장에서는 "체성분을 분석해줘"가 하나의 도구 호출이 됩니다.

```
@tool analysis_specialist(measurement) -> 소견
@tool exercise_specialist(소견)         -> 운동 계획
@tool nutrition_specialist(소견, 운동)  -> 식단 계획   # 운동 계획을 입력으로 받음
```

운동과 식단을 **순차로 체이닝**하는 이유: 독립 실행하면 모순된 계획이 나옵니다.
식단이 큰 칼로리 적자를 제안하는데 운동이 고강도 근력을 처방하면 근손실을 유발합니다.
자세한 구현은 Lab 2 에서 다룹니다.

### MCP 와 Gateway (미리 보기)

MCP(Model Context Protocol)는 에이전트와 도구 사이의 표준 프로토콜입니다. 핵심은
Lambda 가 MCP 를 구현하지 않아도 **Gateway 가 프로토콜을 대신 처리**한다는 점입니다.
그래서 컨테이너·ECR·CodeBuild·HTTPS 엔드포인트가 전부 불필요합니다. Lab 1 에서 실제로
Gateway 를 호출하며 확인합니다.

---

## 환경 확인

여기서부터는 코드를 쓰지 않고, 사전 프로비저닝된 리소스를 배포·확인만 합니다.
전 실습이 **`us-east-1`(N. Virginia) 리전 하나**를 사용합니다.

### Step 1: 자격 증명과 리전 확인

```bash
aws sts get-caller-identity
# 예상 출력:
# {
#   "UserId": "...",
#   "Account": "409016825341",
#   "Arn": "arn:aws:sts::409016825341:assumed-role/..."
# }

aws configure get region
# 예상 출력: us-east-1
```

리전이 `us-east-1` 이 아니면 아래로 고정하세요.

```bash
export AWS_DEFAULT_REGION=us-east-1
```

**정상 동작 확인**: `get-caller-identity` 가 계정 번호를 반환하고 리전이 `us-east-1`.

### Step 2: core 스택 배포 (필수)

S3 버킷, Cognito User Pool, IAM 역할 2개를 만듭니다. 약 2분 걸립니다.

```bash
aws cloudformation deploy \
  --template-file infra/01-core.yaml \
  --stack-name bca-workshop-core \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
# 예상 출력:
# Successfully created/updated stack - bca-workshop-core
```

출력값을 표로 확인합니다.

```bash
aws cloudformation describe-stacks \
  --stack-name bca-workshop-core \
  --region us-east-1 \
  --query 'Stacks[0].Outputs[].{Key:OutputKey,Value:OutputValue}' \
  --output table
```

`DataBucketName`, `UserPoolId`, `UserPoolClientId`, `AgentRuntimeRoleArn`,
`MemoryExecutionRoleArn`, `OIDCDiscoveryUrl` 등이 보입니다. 이 값들을 Lab 마다 씁니다.

**정상 동작 확인**: 스택 상태가 `CREATE_COMPLETE`, 출력값 표에 위 키들이 모두 존재.

### Step 3: 샘플 결과지 업로드

CloudFormation 은 S3 에 파일을 넣지 못하므로, 결과지 4건을 직접 올립니다.
저장소 루트에서 실행하세요.

```bash
BUCKET=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)

aws s3 cp sample-data/pdf/ "s3://$BUCKET/measurements/" --recursive --region us-east-1
aws s3 ls "s3://$BUCKET/measurements/" --region us-east-1
# 예상 출력: 4건이 보입니다
#   user-a-session-01.pdf
#   user-a-session-02.pdf
#   user-a-session-03.pdf
#   user-b-session-01.pdf
```

**정상 동작 확인**: `s3 ls` 결과에 PDF 4건.

### Step 4: gateway 스택 배포 (선택)

추출 Lambda 와 AgentCore Gateway 를 만듭니다. 약 3~5분 걸립니다.

```bash
aws cloudformation deploy \
  --template-file infra/02-gateway.yaml \
  --stack-name bca-workshop-gateway \
  --parameter-overrides CoreStackName=bca-workshop-core \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

`GatewayStatus` 출력이 `READY` 인지 확인합니다.

```bash
aws cloudformation describe-stacks --stack-name bca-workshop-gateway \
  --region us-east-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`GatewayStatus`].OutputValue' --output text
# 예상 출력: READY
```

> 이 스택은 **선택**입니다. 배포하지 않거나 실패해도 Lab 1 은 Runtime 내부(in-process)
> 추출 경로로 진행됩니다. Gateway · MCP 부분만 건너뜁니다.

**정상 동작 확인**: `GatewayStatus` 가 `READY`. `CREATING` 이면 잠시 후 다시 확인.

### Step 5: 테스트 사용자 생성 · 액세스 토큰 획득

Lab 1~5 는 프론트엔드가 없는 상태에서 Gateway 와 에이전트를 호출합니다. 그래서
브라우저 로그인 대신 CLI 로 토큰을 받습니다(App Client 에 `ADMIN_USER_PASSWORD_AUTH`
흐름이 켜져 있어 가능합니다. 프로덕션에서는 켜지 마세요).

```bash
POOL_ID=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
  --output text)
CLIENT_ID=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' \
  --output text)

# 테스트 사용자 생성 (name 속성은 본인 확인용이며 김도현으로 둡니다)
aws cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" \
  --username test@example.com \
  --user-attributes Name=email,Value=test@example.com Name=name,Value=김도현 \
  --message-action SUPPRESS \
  --region us-east-1

# 영구 비밀번호 설정 (임시 비밀번호 챌린지를 건너뜁니다)
aws cognito-idp admin-set-user-password \
  --user-pool-id "$POOL_ID" \
  --username test@example.com \
  --password 'Workshop#2026' \
  --permanent \
  --region us-east-1
```

이제 액세스 토큰을 받습니다. **Gateway 는 액세스 토큰을 요구합니다**(ID 토큰은 403).

```bash
aws cognito-idp admin-initiate-auth \
  --user-pool-id "$POOL_ID" \
  --client-id "$CLIENT_ID" \
  --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters USERNAME=test@example.com,PASSWORD='Workshop#2026' \
  --region us-east-1 \
  --query 'AuthenticationResult.AccessToken' --output text > access-token.txt

head -c 20 access-token.txt; echo " ...(토큰 저장됨)"
```

**정상 동작 확인**: `access-token.txt` 에 `eyJ...` 로 시작하는 JWT 가 저장됨.
Lab 1 에서 이 파일을 그대로 씁니다.

> **왜 ID 토큰이 아니라 액세스 토큰인가**: Cognito ID 토큰에는 `client_id` 와 `scope`
> 클레임이 없고 `aud` 만 있습니다. Gateway 의 `CustomJWTAuthorizer` 는 `AllowedClients`
> 를 `client_id` 클레임과 대조하므로 ID 토큰은 통과하지 못합니다. 이 차이를 Lab 1 에서
> 직접 재현합니다.

---

## 검증

- [ ] `aws sts get-caller-identity` 가 계정 번호를 반환하고 리전이 `us-east-1`
- [ ] `bca-workshop-core` 스택이 `CREATE_COMPLETE`
- [ ] core 출력값 표에 `DataBucketName` · `UserPoolId` · `AgentRuntimeRoleArn` 존재
- [ ] `s3 ls .../measurements/` 에 PDF 4건
- [ ] (선택) `bca-workshop-gateway` 스택의 `GatewayStatus` 가 `READY`
- [ ] `access-token.txt` 에 `eyJ` 로 시작하는 액세스 토큰 저장

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `deploy` 가 `CAPABILITY_NAMED_IAM` 오류 | 명명된 IAM 역할 생성 권한 미승인 | `--capabilities CAPABILITY_NAMED_IAM` 플래그를 붙였는지 확인 |
| core 스택이 `ROLLBACK_COMPLETE` | 이전 실패 스택이 남음 | `aws cloudformation delete-stack --stack-name bca-workshop-core` 후 재배포 |
| gateway 배포가 IAM Role 오류로 실패 | 역할 `Description` 에 비 ASCII 문자 | 템플릿의 `Description` 은 이미 영문. 수정했다면 ASCII 로 되돌리기 |
| `GatewayStatus` 가 계속 `CREATING` | Gateway 생성이 진행 중 | 30초~1분 후 다시 조회. 5분 넘으면 스택 이벤트 확인 |
| `admin-initiate-auth` 가 `NotAuthorizedException` | 비밀번호 불일치 또는 흐름 미허용 | `admin-set-user-password` 재실행, App Client 에 `ADMIN_USER_PASSWORD_AUTH` 확인 |
| `s3 cp` 가 `AccessDenied` | 리전 불일치 또는 버킷명 오타 | `$BUCKET` 값 확인, `--region us-east-1` 명시 |
| 한글 `name` 속성이 깨져 저장 | 터미널 인코딩 | UTF-8 터미널 사용, 값 앞뒤 공백 제거 |

---

완료 후 [Lab 1: 결과지 추출](./01_extract.md)로 이동하세요.
