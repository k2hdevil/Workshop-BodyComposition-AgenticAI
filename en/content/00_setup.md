# 00. Opening · Environment Check (25 min)

> This document is not a Lab. It is the **opening theory (25 min)**. So it has no `🏆 Challenge Task`
> or `Appendix: Answer Code`, which are part of the required Lab skeleton. Participants do not write
> any code here. Instead, deploying, uploading, and getting the token are handled as **verification steps**.

## Learning Objectives

Understand what the body composition analysis app solves, then deploy and check the pre-provisioned resources
to reach the state where you can start Lab 1 (2 stacks · 5 samples · access token).

---

## Theory 1: What You Build (12 min)

You build a web app where a user uploads their own **body composition result sheet PDF**, and several agents
work together to analyze it, track changes between sessions, and suggest exercise and meals. The goal is to reach
"deployed and running on AWS" within 4 hours.

```
User (browser) ─ Cognito login ─▶ Streamlit (ECS Express)
                                        │  access token
                                        ▼
                                 AgentCore Runtime
                                   Supervisor Agent
                        ┌──────────────┼───────────────┐
                        ▼              ▼               ▼
                  Body composition  Exercise          Meal
                  analysis agent    prescription      suggestion
                                    agent             agent
                        │  (analysis → exercise → meal sequential chaining)
             ┌──────────┴───────────┐
             ▼                      ▼
      AgentCore Gateway       AgentCore Memory
       Sheet extraction (λ)   Per-session measurement history
```

There are **4 agents** (the Supervisor + 3 specialists). There are 5 tools.

### Why result sheet extraction is a tool, not an agent

This is the first design decision of the workshop and a teaching point.

| Nature of the work | Example | Suitable implementation |
|--------------------|---------|-------------------------|
| Deterministic | Extract numbers from a PDF, recompute BMI | **Tool** — no LLM loop needed |
| Requires judgment | Interpret findings, suggest exercise and meals | Agent |

The same PDF must not produce different values each time. Wrapping deterministic work in an LLM loop adds only latency, cost, and
non-determinism. So extraction stays a **tool**. In Lab 1 you check this decision yourself by comparing the token usage
of the two paths.

### Sample data — 3 sessions of one person + 1 session of another person

| Document | Person | Format | Role |
|----------|--------|--------|------|
| `user-a-session-01` | Dohyun Kim, 44, male | **Scanned** | Trend baseline · obesity |
| `user-a-session-02` | Dohyun Kim | Digital | Improvement in progress |
| `user-a-session-03` | Dohyun Kim | Digital | Latest · delta analysis |
| `user-b-session-01` | Jieun Park, 32, female | Digital | Different user · D-shape trap |
| `user-a-session-04` | Dohyun Kim | Digital | Extra sample · crosses into Obesity Stage 1 (not used by the labs) |

Trend analysis cannot be validated with two different people, so you need 3 sessions of the same person.
Session 1 is a **scanned copy with no text layer**, so a structural parser alone fails (you confirm the fallback in Lab 1).

> All result sheets in this workshop are **fictional synthetic data**. "InBody" is a registered
> trademark of InBody Co., Ltd., and this repository uses the generic name **body composition analysis**.

---

## Theory 2: AgentCore Components (13 min)

Amazon Bedrock AgentCore is a set of managed components for running agents.
This workshop uses only these 5.

| Component | Role | In this workshop | Created by |
|-----------|------|------------------|------------|
| **Runtime** | Agent execution environment | Hosts the Supervisor + specialist agents | Participant (Lab 5) |
| **Gateway** | Expose tools as MCP | The Lambda extractor as an MCP tool | Participant (stack deployment · Step 4) |
| **Memory** | Long-term memory for conversations and events | Per-session measurement history | Participant (Lab 3) |
| **Identity** | Inbound/outbound authentication | Cognito JWT inbound | Pre-provisioned |
| **Observability** | Tracing, logs, metrics | X-Ray · CloudWatch | Participant (Lab 5) |

> Memory, Guardrail, and Runtime are **created by participants.** Designing the strategy and the policy
> is the core of the learning, and if they were baked into a template you would just read past them. Gateway and Cognito, on the other hand, are
> **deployed from a CloudFormation template, and the labs only connect to them and check them**. You do not write the
> resource definitions by hand (a deliberate choice because of the 4-hour limit). The Gateway is the path that the extraction in Lab 1 must
> go through, so the Step 4 deployment is **required**.

### The Agent-as-Tool pattern

The Supervisor **calls specialist agents like tools**. If you wrap each specialist agent in `@tool`,
"analyze the body composition" becomes a single tool call from the Supervisor's point of view.

```
@tool analysis_specialist(measurement)  -> findings
@tool exercise_specialist(findings)     -> exercise plan
@tool nutrition_specialist(findings, exercise) -> meal plan   # takes the exercise plan as input
```

The reason to **chain exercise and meals sequentially**: running them independently produces contradictory plans.
If the meal plan suggests a large calorie deficit while the exercise plan prescribes high-intensity strength training, it causes muscle loss.
Lab 2 covers the implementation in detail.

### MCP and Gateway (preview)

MCP (Model Context Protocol) is the standard protocol between agents and tools. The key point is that
the Lambda does not need to implement MCP, because the **Gateway handles the protocol for it**.
So no container, ECR, CodeBuild, or HTTPS endpoint is needed. You confirm this by actually calling the
Gateway in Lab 1.

---

## Environment Check

From here on you write no code. You only deploy and check the pre-provisioned resources.
All labs use **a single Region, `us-west-2` (Oregon)**.

### Step 1: Clone the repository

```bash
git clone https://github.com/k2hdevil/Workshop-BodyComposition-AgenticAI
cd Workshop-BodyComposition-AgenticAI/en
```

**Expected result**: The `content/`, `infra/`, and `sample-data/` folders are visible in the `en/` directory. Run every later command from this `en/` directory (the workshop root).

### Step 2: Check credentials and Region

```bash
aws sts get-caller-identity
# Expected output:
# {
#   "UserId": "...",
#   "Account": "409016825341",
#   "Arn": "arn:aws:sts::409016825341:assumed-role/..."
# }

aws configure get region
# Expected output: us-west-2
```

If the Region is not `us-west-2`, set it with the command below.

```bash
export AWS_DEFAULT_REGION=us-west-2
```

**Expected result**: `get-caller-identity` returns an account number and the Region is `us-west-2`.

### Step 3: Deploy the core stack (required)

This creates an S3 bucket, a Cognito User Pool, and 2 IAM roles. It takes about 2 minutes.

```bash
aws cloudformation deploy \
  --template-file infra/01-core.yaml \
  --stack-name bca-workshop-core \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-west-2
# Expected output:
# Successfully created/updated stack - bca-workshop-core
```

Check the output values as a table.

```bash
aws cloudformation describe-stacks \
  --stack-name bca-workshop-core \
  --region us-west-2 \
  --query 'Stacks[0].Outputs[].{Key:OutputKey,Value:OutputValue}' \
  --output table
```

You see `DataBucketName`, `UserPoolId`, `UserPoolClientId`, `AgentRuntimeRoleArn`,
`MemoryExecutionRoleArn`, `OIDCDiscoveryUrl`, and others. You use these values in every Lab.

**Expected result**: The stack status is `CREATE_COMPLETE`, and the output table contains all of the keys above.

### Step 4: Upload the sample result sheets

CloudFormation cannot put files into S3, so you upload the 5 result sheets yourself.
Run this from the `en/` directory.

```bash
BUCKET=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-west-2 --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)

aws s3 cp sample-data/pdf/ "s3://$BUCKET/measurements/" --recursive --region us-west-2
aws s3 ls "s3://$BUCKET/measurements/" --region us-west-2
# Expected output: you see 5 files
#   user-a-session-01.pdf
#   user-a-session-02.pdf
#   user-a-session-03.pdf
#   user-a-session-04.pdf
#   user-b-session-01.pdf
```

**Expected result**: The `s3 ls` output lists 5 PDFs.

### Step 5: Deploy the gateway stack

This creates the extraction Lambda and the AgentCore Gateway. It takes about 3 to 5 minutes.

```bash
aws cloudformation deploy \
  --template-file infra/02-gateway.yaml \
  --stack-name bca-workshop-gateway \
  --parameter-overrides CoreStackName=bca-workshop-core \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-west-2
```

Check that the `GatewayStatus` output is `READY`.

```bash
aws cloudformation describe-stacks --stack-name bca-workshop-gateway \
  --region us-west-2 \
  --query 'Stacks[0].Outputs[?OutputKey==`GatewayStatus`].OutputValue' --output text
# Expected output: READY
```

**Expected result**: `GatewayStatus` is `READY`. If it is `CREATING`, check again in a moment.

### Step 6: Create a test user · get an access token

Labs 1–5 call the Gateway and the agents without a frontend. So instead of a browser login, you get a
token with the CLI (this works because the `ADMIN_USER_PASSWORD_AUTH` flow is enabled on the App Client.
Do not enable it in production).

```bash
POOL_ID=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-west-2 --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
  --output text)
CLIENT_ID=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-west-2 --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' \
  --output text)

# Create the test user (the name attribute is used for the identity check; set it to Dohyun Kim)
aws cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" \
  --username test@example.com \
  --user-attributes Name=email,Value=test@example.com "Name=name,Value=Dohyun Kim" \
  --message-action SUPPRESS \
  --region us-west-2

# Set a permanent password (skips the temporary password challenge)
aws cognito-idp admin-set-user-password \
  --user-pool-id "$POOL_ID" \
  --username test@example.com \
  --password 'Workshop#2026' \
  --permanent \
  --region us-west-2
```

Now get the access token. **The Gateway requires an access token** (an ID token returns 403).

This App Client has a **client secret enabled**, which `st.login()` (Lab 6) needs
(`GenerateSecret: true`). When you authenticate with an App Client that has a secret,
you must pass `SECRET_HASH` to `admin-initiate-auth`. Without it, the call fails with
`NotAuthorizedException: Client is configured with secret but SECRET_HASH was not received`.
`SECRET_HASH` is the Base64 encoding of `HMAC-SHA256(client_secret, username + client_id)`.

First, look up the client secret (it is not exposed as a CloudFormation output, so you look it up separately).

```bash
CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client \
  --user-pool-id "$POOL_ID" \
  --client-id "$CLIENT_ID" \
  --region us-west-2 \
  --query 'UserPoolClient.ClientSecret' --output text)
echo "Got secret: ${CLIENT_SECRET:0:5}..."
```

Compute `SECRET_HASH` with the secret you looked up (the message is the username + client_id).

```bash
SECRET_HASH=$(python3 -c "
import hmac, hashlib, base64
msg = 'test@example.com' + '$CLIENT_ID'
sig = hmac.new('$CLIENT_SECRET'.encode(), msg.encode(), hashlib.sha256).digest()
print(base64.b64encode(sig).decode())
")
```

Now include `SECRET_HASH` in the auth parameters to get the token.

```bash
aws cognito-idp admin-initiate-auth \
  --user-pool-id "$POOL_ID" \
  --client-id "$CLIENT_ID" \
  --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters USERNAME=test@example.com,PASSWORD='Workshop#2026',SECRET_HASH="$SECRET_HASH" \
  --region us-west-2 \
  --query 'AuthenticationResult.AccessToken' --output text > access-token.txt

head -c 20 access-token.txt; echo " ...(token saved)"
```

**Expected result**: `access-token.txt` contains a JWT that starts with `eyJ...`.
You use this file as it is in Lab 1.

> **Why an access token and not an ID token**: A Cognito ID token has no `client_id` or `scope`
> claim, only `aud`. The Gateway's `CustomJWTAuthorizer` compares `AllowedClients`
> against the `client_id` claim, so an ID token does not pass. You reproduce this difference
> yourself in Lab 1.

---

## Verification

- [ ] The repository is cloned and you can see the `content/`, `infra/`, and `sample-data/` folders in `en/`
- [ ] `aws sts get-caller-identity` returns an account number and the Region is `us-west-2`
- [ ] The `bca-workshop-core` stack is `CREATE_COMPLETE`
- [ ] The core output table contains `DataBucketName` · `UserPoolId` · `AgentRuntimeRoleArn`
- [ ] `s3 ls .../measurements/` shows 5 PDFs
- [ ] The `GatewayStatus` of the `bca-workshop-gateway` stack is `READY`
- [ ] `access-token.txt` holds an access token that starts with `eyJ`

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `deploy` fails with a `CAPABILITY_NAMED_IAM` error | Creating named IAM roles was not acknowledged | Check that you added the `--capabilities CAPABILITY_NAMED_IAM` flag |
| The core stack is `ROLLBACK_COMPLETE` | A previous failed stack is left over | Run `aws cloudformation delete-stack --stack-name bca-workshop-core`, then deploy again |
| The gateway deployment fails with an IAM Role error | Non-ASCII characters in the role `Description` | The template `Description` is already English. If you edited it, restore ASCII |
| `GatewayStatus` stays `CREATING` | Gateway creation is still in progress | Query again after 30 seconds to 1 minute. If it takes more than 5 minutes, check the stack events |
| `admin-initiate-auth` returns `NotAuthorizedException` | Wrong password or the flow is not allowed | Rerun `admin-set-user-password` and check that the App Client has `ADMIN_USER_PASSWORD_AUTH` |
| `Client is configured with secret but SECRET_HASH was not received` | The App Client has a secret but the hash is missing | Follow the steps above: look up `CLIENT_SECRET` → compute `SECRET_HASH` → include it in `--auth-parameters` |
| `NotAuthorizedException` even with `SECRET_HASH` | The hash inputs do not match | The hash message is `username + client_id` in that order. The `USERNAME` value must equal the username used in the hash |
| `s3 cp` returns `AccessDenied` | Region mismatch or a typo in the bucket name | Check the `$BUCKET` value and pass `--region us-west-2` explicitly |
| Cognito `name` is saved as `Dohyun` only | The value was not quoted, so the shell split it at the space | Quote the whole attribute: `"Name=name,Value=Dohyun Kim"` |

---

When you finish, go to [Lab 1: Result Sheet Extraction](./01_extract.md).
