# 99. Action Items · 리소스 정리

> 이 문서는 Lab 이 아니라 **마무리(8분)** 입니다. 코드 빈칸이 없으므로 `🏆 Challenge Task`
> 와 `부록: 정답 코드` 는 두지 않습니다. 대신 정리는 **반드시** 수행하세요 — 남은 리소스는
> 과금됩니다.

## 학습 목표

워크샵에서 만든 모든 리소스를 정리하고, 4시간에서 빠진 항목을 Action Items 로 정리합니다.

---

## 정리 순서 개요

리소스는 크게 둘로 나뉩니다.

| 구분 | 만든 방법 | 정리 방법 |
|------|-----------|-----------|
| 인프라(S3·Cognito·IAM·Lambda·Gateway) | CloudFormation 스택 2개 | 스택 삭제 (버킷 먼저 비우기) |
| 실습 리소스(Memory·Guardrail·Runtime) | 참가자가 직접 생성 | **개별 삭제** (스택에 없음) |

실습에서 직접 만든 것은 스택에 속하지 않으므로 **스택만 지우면 남습니다.** 아래 순서를
그대로 따르세요.

---

## 정리 시작

### Step 1: 실습에서 만든 리소스 삭제

스택에 포함되지 않은 것부터 지웁니다. Runtime → Memory → Guardrail 순.

```bash
# Runtime — agentcore CLI 로 삭제
agentcore destroy   # 또는 콘솔에서 해당 Runtime 삭제

# Memory — Lab 3 에서 만든 memory_id 로 삭제
uv run python -c "
from bedrock_agentcore.memory import MemoryClient
c = MemoryClient(region_name='us-east-1')
c.delete_memory(memory_id='<LAB3_MEMORY_ID>')
print('memory deleted')
"

# Guardrail — Lab 4 에서 만든 guardrailId 로 삭제
aws bedrock delete-guardrail --guardrail-identifier <LAB4_GUARDRAIL_ID> --region us-east-1
```

**정상 동작 확인**: `agentcore` 목록·`list-guardrails`·Memory 조회에서 해당 리소스가
사라졌는지 확인합니다.

```bash
aws bedrock list-guardrails --region us-east-1 \
  --query 'guardrails[].name' --output text
# bca-safety 가 목록에 없어야 합니다
```

### Step 2: 버킷 비우기

S3 버킷에 객체가 남아 있으면 스택 삭제가 실패합니다. 먼저 비웁니다.

```bash
BUCKET=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-east-1 --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)

aws s3 rm "s3://$BUCKET" --recursive --region us-east-1
aws s3 ls "s3://$BUCKET" --region us-east-1
# 아무것도 출력되지 않아야 합니다
```

**정상 동작 확인**: `s3 ls` 결과가 빔.

### Step 3: 스택 삭제 (생성의 역순)

gateway(선택 스택)를 먼저, core 를 나중에 지웁니다.

```bash
# gateway 스택을 배포했다면 먼저 삭제
aws cloudformation delete-stack --stack-name bca-workshop-gateway --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name bca-workshop-gateway --region us-east-1

# core 스택 삭제
aws cloudformation delete-stack --stack-name bca-workshop-core --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name bca-workshop-core --region us-east-1
```

**정상 동작 확인**: 두 `wait` 명령이 오류 없이 끝나면 삭제 완료입니다.

```bash
aws cloudformation describe-stacks --stack-name bca-workshop-core --region us-east-1 2>&1 | tail -1
# "does not exist" 류 메시지가 나오면 정상 삭제된 것입니다
```

### Step 4: ECS Express Mode 서비스·ECR 리포지토리 삭제 (Lab 6 을 배포했다면)

Express 서비스를 지우면 ALB·타깃그룹·보안그룹·오토스케일 등 딸린 인프라가 함께 정리됩니다.

```bash
# 서비스 ARN 조회 (delete/describe 는 --service-arn 을 받으므로 이름으로 먼저 찾습니다)
SERVICE_ARN=$(aws ecs list-services --region us-east-1 \
  --query "serviceArns[?contains(@, 'bca-frontend')]" --output text)

# Express 서비스 삭제 (딸린 ALB·타깃그룹·보안그룹·오토스케일 함께 제거)
aws ecs delete-express-gateway-service --service-arn "$SERVICE_ARN" --region us-east-1

# ECR 리포지토리 삭제 (이미지 포함 강제 삭제)
aws ecr delete-repository --repository-name bca-workshop-frontend \
  --force --region us-east-1
```

---

## 정리 검증

- [ ] Runtime 이 삭제됨(`agentcore` 목록에 없음)
- [ ] Memory 가 삭제됨
- [ ] Guardrail `bca-safety` 가 `list-guardrails` 에 없음
- [ ] S3 버킷이 비워짐
- [ ] `bca-workshop-gateway` 스택 삭제 완료
- [ ] `bca-workshop-core` 스택 삭제 완료
- [ ] (배포했다면) ECS Express 서비스·ECR 리포지토리 삭제

> S3 버킷에는 7일 만료 수명주기가 걸려 있어 정리를 잊어도 데이터는 남지 않습니다. 다만
> Gateway·ECS Express(Fargate·ALB) 는 시간당 과금이 있을 수 있으므로 반드시 삭제하세요.

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| core 스택 삭제가 `DELETE_FAILED` | 버킷에 객체가 남음 | Step 2 로 버킷을 먼저 비운 뒤 재삭제 |
| Guardrail 삭제가 참조 오류 | 에이전트가 아직 참조 중 | Runtime 을 먼저 삭제한 뒤 Guardrail 삭제 |
| Memory 삭제 권한 오류 | 자격 증명 부족 | 실습 계정 자격 증명으로 재시도 |
| Express 서비스가 조회 안 됨 | Lab 6 미배포 | 배포하지 않았으면 건너뜁니다 |
| ECR 삭제가 이미지 존재 오류 | 태그된 이미지가 남음 | `--force` 플래그로 이미지 포함 삭제 |
| gateway 스택이 이미 없음 | 선택 스택 미배포 | 정상. core 만 삭제하면 됩니다 |

---

## Action Items (워크샵 이후)

4시간 제약으로 실습에서 빠진 항목입니다. 각 Lab 의 Challenge Task 와 이어집니다.

| 항목 | 내용 |
|------|------|
| 외부 헬스 데이터 연동 | AgentCore Identity 의 **outbound** 인증으로 삼성헬스·Apple Health 등 OAuth 대행. 이번 실습은 inbound(로그인)만 |
| 컨텍스트 압축 | Strands `SummarizingConversationManager` 적용. Lab 4 에서 코드만 제공하고 실습은 캐시까지 |
| Gateway·Cognito 직접 구성 | 사전 프로비저닝된 것을 직접 만들어 보기. Cedar 정책으로 세밀한 인가 |
| 평가 축 확장 | 안전성(code-based evaluator), 운동↔식단 모순 감지, 라우팅 정확도. Lab 7 은 추출 정확도 1개 축만 |
| 프로덕션 준비 | VPC Private Subnet + ALB, Multi-AZ, CI/CD 에 평가 통합, 감사 로그 장기 보존 |
| MCP 서버 심화 | Lambda 타겟 대신 자체 MCP 서버 호스팅(ARM64 컨테이너). `rsp2k/mcp-pdf` 같은 서버는 시스템 바이너리 의존이 커 이번 범위에서 제외 |

---

## 마무리

이 워크샵에서 만든 것:

- 결정적 작업(추출)과 판단 작업(해석·제안)을 구분한 멀티 에이전트 앱
- Agent-as-Tool 로 조율하고 운동→식단을 순차 체이닝
- Memory 로 회차 추이를 분석하고 사용자별로 격리
- Guardrail 로 확정 진단·약물 처방·프롬프트 인젝션을 차단
- 개인정보를 마스킹이 아니라 경계로 다룸(이름은 화면에만, 에이전트·로그에서 제외)
- CodeZip 으로 Runtime 배포, Streamlit 을 ECS Express Mode 로 HTTPS 배포
- Ground Truth 로 추출 정확도를 회귀 검증

수고하셨습니다.
