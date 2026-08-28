# 인프라 배포

참가자가 직접 배포합니다. 스택 두 개로 나뉘어 있고 **두 번째는 선택**입니다.

| 스택 | 파일 | 내용 | 생성 시간 | 필수 |
|------|------|------|----------|------|
| core | `01-core.yaml` | S3 · Cognito · IAM 역할 2개 | 약 2분 | **필수** |
| gateway | `02-gateway.yaml` | 추출 Lambda · AgentCore Gateway · GatewayTarget | 약 3~5분 | 선택 |

## 왜 AgentCore 리소스가 템플릿에 없나

**Memory · Guardrail · Runtime 은 실습에서 참가자가 직접 만듭니다.** 전략 설계와 정책 설계가
학습의 본체라서 템플릿에 박아두면 읽고 지나갈 뿐입니다. 그래서 이 템플릿에는 부수 인프라와
IAM 역할만 들어 있습니다.

Gateway 는 예외적으로 템플릿에 있습니다. Lambda 를 MCP 도구로 노출하려면 Gateway 와
GatewayTarget 을 함께 만들어야 하고, JWT authorizer 설정까지 참가자가 하면 4시간 안에
앱을 못 만듭니다. 대신 Lab 1 에서 **도구 스키마가 곧 에이전트에게 보이는 인터페이스라는 점**을
템플릿의 `ToolSchema` 블록을 읽으면서 확인합니다.

---

## 1. core 스택 배포

```bash
aws cloudformation deploy \
  --template-file infra/01-core.yaml \
  --stack-name bca-workshop-core \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

출력값 확인:

```bash
aws cloudformation describe-stacks \
  --stack-name bca-workshop-core \
  --region us-east-1 \
  --query 'Stacks[0].Outputs[].{Key:OutputKey,Value:OutputValue}' \
  --output table
```

주요 출력값:

| 출력 | 쓰이는 곳 |
|------|----------|
| `DataBucketName` | 결과지 업로드 · 산출물 저장 |
| `UploadSamplesCommand` | 샘플 결과지 4건을 올리는 명령 (복사해서 실행) |
| `UserPoolId` / `UserPoolClientId` | Lab 6 Streamlit 인증 |
| `GetClientSecretCommand` | client secret 조회 명령 |
| `OIDCDiscoveryUrl` | `st.login()` 의 `server_metadata_url` |
| `AgentRuntimeRoleArn` | Lab 5 Runtime 생성 시 `roleArn` |
| `MemoryExecutionRoleArn` | Lab 3 Memory 생성 시 `memoryExecutionRoleArn` |

### 샘플 결과지 업로드

CloudFormation 은 S3 에 파일을 넣지 못합니다 (PDF 4건이 약 2MB 라 템플릿 인라인 한도도
넘습니다). 저장소 루트에서 한 번 실행하세요.

```bash
BUCKET=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)

aws s3 cp sample-data/pdf/ "s3://$BUCKET/measurements/" --recursive --region us-east-1
aws s3 ls "s3://$BUCKET/measurements/" --region us-east-1
# 4건이 보여야 합니다
```

---

## 2. gateway 스택 배포 (선택)

```bash
aws cloudformation deploy \
  --template-file infra/02-gateway.yaml \
  --stack-name bca-workshop-gateway \
  --parameter-overrides CoreStackName=bca-workshop-core \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

`GatewayStatus` 출력이 `READY` 여야 호출됩니다. `CREATING` 이면 잠시 후 다시 확인하세요.

### 이 스택을 건너뛰어도 됩니다

Lab 1 은 **Gateway 경유 → 실패 시 in-process 추출** 순서로 폴백하도록 설계되어 있습니다.
이 스택이 없거나 실패해도 실습은 진행됩니다. 대신 MCP · Gateway 부분만 건너뜁니다.

### Lambda 는 자리표시자입니다

`ExtractorFunction` 은 배포 가능한 최소 코드만 담고 있고, **Lab 1 에서 참가자가 작성한
추출 코드로 교체**합니다. IAM · Gateway · 도구 스키마 배선은 이미 완료된 상태입니다.

```bash
# 1) 배포 패키지 만들기 (arm64 휠로 pdfplumber 설치)
pip install pdfplumber -t build/ \
  --platform manylinux2014_aarch64 --only-binary=:all: --python-version 3.13
cp index.py build/
(cd build && zip -qr ../extractor.zip .)

# 2) 코드 교체
aws lambda update-function-code \
  --function-name bca-workshop-extractor \
  --zip-file fileb://extractor.zip \
  --region us-east-1
```

두 명령 모두 스택 출력값(`BuildZipCommand`, `UpdateFunctionCodeCommand`)에 들어 있습니다.

---

## 설계 노트

### 최소 권한

`AdministratorAccess` 를 쓰지 않습니다. Runtime 역할은 4개 정책으로 쪼개져 있습니다.

| 정책 | 범위 |
|------|------|
| `bedrock-model-invoke` | Claude 모델과 추론 프로파일에 한정. Guardrail 은 이 계정/리전으로 한정 |
| `agentcore-memory` | 이벤트 저장·조회에 필요한 6개 동작만. `memory/*` 로 한정 |
| `s3-data-access` | 해당 버킷의 객체 읽기/쓰기만 |
| `observability` | 로그 그룹 접두사 한정. X-Ray 쓰기와 `PutMetricData` 는 리소스 수준 권한을 지원하지 않아 `*` 이며, 메트릭은 네임스페이스 조건으로 좁혔습니다 |

Memory 와 Guardrail 은 참가자가 실습에서 만들기 때문에 스택 생성 시점에 ARN 을 알 수
없습니다. 그래서 계정과 리전으로 범위를 좁힌 와일드카드를 씁니다.

두 역할의 신뢰 정책에는 `aws:SourceAccount` 조건을 넣어 혼동된 대리인(confused deputy)
문제를 막았습니다.

### Cognito 의 `name` 속성이 필수인 이유

표시용이 아니라 **본인 확인용**입니다. 결과지에서 추출한 이름과 로그인 사용자 이름을 대조해
타인의 결과지 업로드를 걸러냅니다. 화면에 표시할 이름은 Cognito 프로필에서 가져오고,
에이전트에게 넘기는 페이로드와 로그에는 이름을 넣지 않습니다.

### S3

- HTTPS 아닌 요청을 버킷 정책으로 거부합니다 (개인 체성분 데이터)
- SSE-S3 기본 암호화
- 퍼블릭 액세스 4종 모두 차단
- 7일 만료 수명주기 — 정리를 잊어도 데이터가 남지 않습니다

### Gateway 는 Lambda 타겟을 씁니다

MCP 서버를 직접 띄우는 대신 Gateway 의 Lambda 타겟을 씁니다. **Lambda 는 MCP 프로토콜을
구현하지 않고, Gateway 가 `tools/list` 와 `tools/call` 을 대신 처리**합니다. 덕분에 아래가
전부 불필요해집니다.

- ARM64 컨테이너 (AgentCore Runtime 의 MCP 호스팅 요구사항)
- ECR · CodeBuild
- HTTPS 엔드포인트 (Gateway 의 MCP 서버 타겟은 `^https://` 를 요구합니다)
- streamable-http 의 `Mcp-Session-Id` 처리

대신 도구 정의를 템플릿의 `ToolSchema.InlinePayload` 에 선언합니다.

---

## 검증 상태

| 항목 | 상태 |
|------|------|
| `cfn-lint` | 두 템플릿 오류·경고 0 |
| `01-core` 실제 배포 | **성공** (us-east-1) |
| `02-gateway` 실제 배포 | **성공** (us-east-1) |
| Gateway MCP 호출 end-to-end | **성공** |

`cfn-lint` 1.55 의 번들 스키마에는 AgentCore 리소스가 없습니다 (46개 리전 폴더 전체에
`aws-bedrockagentcore-*` 스키마가 없음). 그래서 `E3006`·`W3037` 을 무시 처리했고
**`Gateway`·`GatewayTarget` 블록은 린터가 검증해 주지 못합니다.** 대신 실제 배포로 확인했습니다.

### 드라이런에서 잡힌 문제

| # | 문제 | 조치 |
|---|------|------|
| 1 | **IAM Role `Description` 에 한글을 쓰면 배포 실패** — 패턴이 ASCII/Latin-1 로 제한 | 모든 리소스 `Description` 을 영문으로 변경. 설명은 YAML 주석과 이 문서에 한국어로 유지 |
| 2 | App Client 가 SRP 인증만 허용해 **CLI 로 테스트 토큰을 얻을 수 없음** | `ALLOW_ADMIN_USER_PASSWORD_AUTH` 추가. Lab 1~5 는 프론트엔드가 없어 CLI 토큰이 필요합니다 |

1번은 cfn-lint 가 잡지 못했고 실제 배포에서만 드러났습니다.

### Gateway 인바운드 인증 — 액세스 토큰을 쓰세요

`verify_gateway_mcp.py` 로 확인한 결과입니다.

| 시도 | 결과 |
|------|------|
| 토큰 없음 | HTTP 401 |
| **ID 토큰** | HTTP 403 `insufficient_scope` |
| **액세스 토큰** | HTTP 200 |

Cognito ID 토큰에는 `client_id` 와 `scope` 클레임이 없고 `aud` 만 있습니다. Gateway 의
`CustomJWTAuthorizer` 는 `AllowedClients` 를 `client_id` 와 대조하므로 ID 토큰은 통과하지
못합니다. Streamlit 에서도 **액세스 토큰**을 꺼내 Gateway 로 넘겨야 하며,
`secrets.toml` 의 `expose_tokens` 에 `"access"` 를 포함해야 합니다.

### Gateway MCP 동작 확인

```
tools/list  ->  bodyCompositionExtractor___extract_body_composition
                (타겟명 + 밑줄 3개 + 도구명)

tools/call  ->  Lambda event     = {"s3_key": "measurements/user-a-session-03.pdf"}
                Lambda tool name = client_context.custom["bedrockAgentCoreToolName"]
                응답             = 자리표시자의 NOT_IMPLEMENTED (정상)
```

Lambda 는 MCP 를 구현하지 않았는데도 호출되었습니다. Gateway 가 JSON-RPC 를 Lambda 호출로
번역한다는 점이 실물로 확인되었습니다.

### 재현 방법

```bash
# 1) 테스트 사용자 생성 + 액세스 토큰 획득 (Lab 1 에서도 같은 절차를 씁니다)
#    상세 절차는 content/00_setup.md 참고

# 2) Gateway MCP 검증
python3 sample-data/tools/verify_gateway_mcp.py \
  "$(aws cloudformation describe-stacks --stack-name bca-workshop-gateway --region us-east-1 \
      --query 'Stacks[0].Outputs[?OutputKey==`GatewayUrl`].OutputValue' --output text)" \
  /path/to/access-token.txt
```

---

## 정리 (Cleanup)

버킷을 먼저 비워야 스택이 삭제됩니다.

```bash
BUCKET=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)
aws s3 rm "s3://$BUCKET" --recursive --region us-east-1

# 스택은 생성의 역순으로 삭제합니다
aws cloudformation delete-stack --stack-name bca-workshop-gateway --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name bca-workshop-gateway --region us-east-1
aws cloudformation delete-stack --stack-name bca-workshop-core --region us-east-1
```

실습에서 직접 만든 리소스(Memory, Guardrail, Runtime)는 스택에 속하지 않으므로 별도로
삭제해야 합니다. 절차는 `content/99_cleanup.md` 에 있습니다.
