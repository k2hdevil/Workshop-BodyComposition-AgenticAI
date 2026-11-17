# Infrastructure Deployment

Participants deploy the infrastructure themselves. It is split into two stacks, and **both are required**. The extraction in Lab 1
always goes through the Gateway MCP, so you cannot do Lab 1 without the gateway stack.

| Stack | File | Contents | Creation time | Required |
|------|------|------|----------|------|
| core | `01-core.yaml` | S3 · Cognito · 2 IAM roles | about 2 min | **Required** |
| gateway | `02-gateway.yaml` | Extractor Lambda · AgentCore Gateway · GatewayTarget | about 3-5 min | **Required** |

## Why AgentCore resources are not in the templates

**Participants create Memory, Guardrail, and Runtime themselves in the labs.** Designing the strategies and policies
is the core of the learning, and if they were baked into a template you would only read them and move on. So these templates contain only the supporting
infrastructure and the IAM roles.

The Gateway is the exception and is in the template. To expose a Lambda as an MCP tool you have to create the Gateway and
the GatewayTarget together, and if participants also had to set up the JWT authorizer, they could not finish the
app in 4 hours. Instead, in Lab 1 you read the `ToolSchema` block in the template
and confirm that **the tool schema is the interface the agent sees**.

---

## 1. Deploy the core stack

```bash
aws cloudformation deploy \
  --template-file infra/01-core.yaml \
  --stack-name bca-workshop-core \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-west-2
```

Check the output values:

```bash
aws cloudformation describe-stacks \
  --stack-name bca-workshop-core \
  --region us-west-2 \
  --query 'Stacks[0].Outputs[].{Key:OutputKey,Value:OutputValue}' \
  --output table
```

Main output values:

| Output | Where it is used |
|------|----------|
| `DataBucketName` | Uploading result sheets · storing outputs |
| `UploadSamplesCommand` | Command that uploads the 5 sample result sheets (copy and run it) |
| `UserPoolId` / `UserPoolClientId` | Lab 6 Streamlit authentication |
| `GetClientSecretCommand` | Command that retrieves the client secret |
| `OIDCDiscoveryUrl` | `server_metadata_url` of `st.login()` |
| `AgentRuntimeRoleArn` | `roleArn` when you create the Runtime in Lab 5 |
| `MemoryExecutionRoleArn` | `memoryExecutionRoleArn` when you create the Memory in Lab 3 |

### Upload the sample result sheets

CloudFormation cannot put files into S3 (the 5 PDFs total about 1.3 MB, which also exceeds the template inline limit).
Run it once from the `en/` directory.

```bash
BUCKET=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-west-2 --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)

aws s3 cp sample-data/pdf/ "s3://$BUCKET/measurements/" --recursive --region us-west-2
aws s3 ls "s3://$BUCKET/measurements/" --region us-west-2
# You should see 5 files
```

---

## 2. Deploy the gateway stack (required)

```bash
aws cloudformation deploy \
  --template-file infra/02-gateway.yaml \
  --stack-name bca-workshop-gateway \
  --parameter-overrides CoreStackName=bca-workshop-core \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-west-2
```

The call works only when the `GatewayStatus` output is `READY`. If it is `CREATING`, check again in a moment.

### This stack is a prerequisite for Lab 1

The extraction in Lab 1 is done through **a Gateway MCP tool call**. You replace the placeholder Lambda that this stack deploys
with the extraction code you write, call it through the Gateway, and check the result.
So you cannot start Lab 1 without this stack. Wait until `GatewayStatus` is
`READY`, then move on to Lab 1.

### The Lambda is a placeholder

`ExtractorFunction` holds only the minimum deployable code, and **you replace it with the extraction code
you write in Lab 1**. The IAM, Gateway, and tool schema wiring is already complete.

```bash
# 1) Build the deployment package (install pdfplumber with arm64 wheels)
pip install pdfplumber -t build/ \
  --platform manylinux2014_aarch64 --only-binary=:all: --python-version 3.13
cp index.py build/
(cd build && zip -qr ../extractor.zip .)

# 2) Replace the code
aws lambda update-function-code \
  --function-name bca-workshop-extractor \
  --zip-file fileb://extractor.zip \
  --region us-west-2
```

Both commands are in the stack outputs (`BuildZipCommand`, `UpdateFunctionCodeCommand`).

---

## Design Notes

### Least privilege

`AdministratorAccess` is not used. The Runtime role is split into 4 policies.

| Policy | Scope |
|------|------|
| `bedrock-model-invoke` | Limited to Claude models and inference profiles. Guardrail is limited to this account and Region |
| `agentcore-memory` | Only the 6 actions needed to store and read events. Limited to `memory/*` |
| `s3-data-access` | Read and write of objects in this bucket only |
| `observability` | Limited to the log group prefix. X-Ray writes and `PutMetricData` do not support resource-level permissions, so they use `*`, and the metrics are narrowed with a namespace condition |

Participants create Memory and Guardrail in the labs, so their ARNs are not known when the stack is
created. The policy therefore uses wildcards scoped to the account and Region.

The trust policies of both roles include an `aws:SourceAccount` condition to prevent the confused deputy
problem.

### Why the Cognito `name` attribute is required

It is for **identity checks**, not for display. The name extracted from the result sheet is compared with the logged-in user's name
to filter out uploads of other people's result sheets. The name shown on screen comes from the Cognito profile,
and the name is not put in the payload passed to the agent or in the logs.

### S3

- A bucket policy denies non-HTTPS requests (personal body composition data)
- SSE-S3 default encryption
- All 4 public access blocks are on
- 7-day expiration lifecycle: no data is left behind even if you forget to clean up

### The Gateway uses a Lambda target

Instead of running an MCP server yourself, you use the Gateway's Lambda target. **The Lambda does not implement the MCP protocol,
and the Gateway handles `tools/list` and `tools/call` on its behalf**. Because of this, all of the following
become unnecessary.

- An ARM64 container (an AgentCore Runtime requirement for hosting MCP)
- ECR · CodeBuild
- An HTTPS endpoint (the Gateway's MCP server target requires `^https://`)
- Handling of the streamable-http `Mcp-Session-Id`

Instead, you declare the tool definition in `ToolSchema.InlinePayload` of the template.

---

## Verification Status

| Item | Status |
|------|------|
| `cfn-lint` | 0 errors and warnings in both templates |
| `01-core` actual deployment | **Succeeded** (us-west-2) |
| `02-gateway` actual deployment | **Succeeded** (us-west-2) |
| Gateway MCP call end-to-end | **Succeeded** |

The schemas bundled with `cfn-lint` 1.55 do not include AgentCore resources (there is no
`aws-bedrockagentcore-*` schema in any of the 46 Region folders). So `E3006` and `W3037` are ignored, and
**the linter cannot validate the `Gateway` and `GatewayTarget` blocks.** They were checked by an actual deployment instead.

### Problems caught in the dry run

| # | Problem | Fix |
|---|------|------|
| 1 | **Non-Latin-1 characters in an IAM Role `Description` make the deployment fail** — the pattern is limited to ASCII/Latin-1 | Changed every resource `Description` to English. Explanations stay in the YAML comments and this document |
| 2 | The App Client allowed only SRP authentication, so **you cannot get a test token from the CLI** | Added `ALLOW_ADMIN_USER_PASSWORD_AUTH`. Labs 1-5 have no frontend, so they need a CLI token |

cfn-lint did not catch problem 1. It showed up only in an actual deployment.

### Gateway inbound authentication — use the access token

These are the results confirmed with `verify_gateway_mcp.py`.

| Attempt | Result |
|------|------|
| No token | HTTP 401 |
| **ID token** | HTTP 403 `insufficient_scope` |
| **Access token** | HTTP 200 |

A Cognito ID token has only `aud`, with no `client_id` or `scope` claim. The Gateway's
`CustomJWTAuthorizer` compares `AllowedClients` with `client_id`, so an ID token does not
pass. In Streamlit too, you must take the **access token** and pass it to the Gateway, and
`expose_tokens` in `secrets.toml` must include `"access"`.

### Verify the Gateway MCP behavior

```
tools/list  ->  bodyCompositionExtractor___extract_body_composition
                (target name + 3 underscores + tool name)

tools/call  ->  Lambda event     = {"s3_key": "measurements/user-a-session-03.pdf"}
                Lambda tool name = client_context.custom["bedrockAgentCoreToolName"]
                response         = NOT_IMPLEMENTED from the placeholder (expected)
```

The Lambda was called even though it does not implement MCP. This confirmed in practice that the Gateway translates JSON-RPC into a Lambda
invocation.

### How to reproduce

```bash
# 1) Create a test user + get an access token (Lab 1 uses the same procedure)
#    See content/00_setup.md for the detailed steps

# 2) Verify the Gateway MCP
python3 sample-data/tools/verify_gateway_mcp.py \
  "$(aws cloudformation describe-stacks --stack-name bca-workshop-gateway --region us-west-2 \
      --query 'Stacks[0].Outputs[?OutputKey==`GatewayUrl`].OutputValue' --output text)" \
  /path/to/access-token.txt
```

---

## Cleanup

Empty the bucket first, otherwise the stack cannot be deleted.

```bash
BUCKET=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-west-2 --query 'Stacks[0].Outputs[?OutputKey==`DataBucketName`].OutputValue' \
  --output text)
aws s3 rm "s3://$BUCKET" --recursive --region us-west-2

# Delete the stacks in the reverse order of creation
aws cloudformation delete-stack --stack-name bca-workshop-gateway --region us-west-2
aws cloudformation wait stack-delete-complete --stack-name bca-workshop-gateway --region us-west-2
aws cloudformation delete-stack --stack-name bca-workshop-core --region us-west-2
```

The resources you created yourself in the labs (Memory, Guardrail, Runtime) do not belong to a stack, so you have to
delete them separately. The procedure is in `content/99_cleanup.md`.
