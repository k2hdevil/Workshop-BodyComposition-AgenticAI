# Lab 5: Runtime Deployment + Observability (25 min)

## Learning Objectives

Deploy the agents you built in Labs 2–4 to AgentCore Runtime with **CodeZip (Direct Code Deploy)**,
and trace the calls with Observability. You deploy by uploading a zip, with no Docker build.

> **Code state at the start of this Lab**: The Supervisor (Lab 2), Memory (Lab 3), and Guardrail (Lab 4)
> work locally. This Lab ties them into one entrypoint and puts it in the cloud.
> You create the Runtime yourself.

---

## Theory: Why CodeZip, and What Gets Traced (8 min)

### CodeZip vs Container

| Method | What you need | In a 4-hour session |
|------|--------|----------------|
| **CodeZip (Direct Code Deploy)** | zip archive + entrypoint | **Adopted** — no Docker needed, short cold start |
| Container | Dockerfile · ECR · ARM64 build | Excluded because it has many failure points |

A Docker build and an ECR push are failure points a 4-hour session cannot afford. For a `uv`-based
project, the AgentCore CLI packs the code into a zip and deploys it directly.

### Why Four Agents Share One Runtime

The question "shouldn't a multi-agent app have several Runtimes?" comes up naturally.
The answer is that **the 3 specialist agents in this workshop are not independent services. They are
`@tool`s of the Supervisor**.

```
Supervisor (Runtime entrypoint)
  @tool analysis_specialist()   ← function call in the same process
  @tool exercise_specialist()   ← function call in the same process
  @tool nutrition_specialist()  ← function call in the same process
```

From the outside it is a single endpoint. Inside, the Supervisor orchestrates the three agents in
sequence. This is the **Agent-as-Tool pattern** from Lab 2, and the Runtime is the unit that hosts
this Supervisor.

> In production you can also split each specialist agent into its own Runtime and have the
> Supervisor call them remotely. That allows isolation between agents, independent scaling, and
> separate deployment, but it adds network latency and authentication complexity. This workshop
> chooses a single Runtime because of the 4-hour limit and to prove the concept (see the Action Items).

### Runtime Service Contract

An agent only has to satisfy two things. With the `@app.entrypoint` decorator, the SDK handles both
automatically.

```
POST /invocations   handle a request (the agent itself)
GET  /ping          health check
```

### What You Look at in Observability

You look at call traces, latency, token usage, and the order of tool calls. The trace shows whether
the Supervisor calls the tools in the order analysis → exercise → meals. `aws-opentelemetry-distro`
instruments the code automatically and sends the data to X-Ray and CloudWatch. **Names are not put in traces** (privacy boundary design).

---

## Start the Lab

Get the Runtime execution role ARN from the core stack.

```bash
RUNTIME_ROLE=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-west-2 --query 'Stacks[0].Outputs[?OutputKey==`AgentRuntimeRoleArn`].OutputValue' \
  --output text)
echo "$RUNTIME_ROLE"
# Expected output: arn:aws:iam::<account>:role/bca-workshop-agent-runtime-role
```

`agentcore create` in Step 1 creates the project directory and the dependencies.
If the AgentCore CLI is not installed yet, install it first.

```bash
npm install -g @aws/agentcore   # AgentCore CLI (skip this if it is already installed)
```

> **Note — the CLI may already exist even if npm reports an error.** The workshop image has
> `@aws/agentcore` pre-installed, so reinstalling can fail with an `EACCES` error because of an
> ownership conflict on the existing files. If you see an error, first check whether the CLI actually works.
>
> ```bash
> agentcore --version   # if a version is printed, it is fine — ignore the npm error and go to the next step
> ```
>
> If the command is not found, delete the existing files with `sudo rm -rf ~/.nvm/versions/node/$(node -v)/lib/node_modules/@aws/agentcore`
> and run `npm install -g @aws/agentcore` again.

### Step 1: Scaffold the Project — agentcore create

Both `agentcore dev` and `agentcore deploy` work only inside an AgentCore project that has an
`agentcore.json`. Create the scaffold, then merge the code you wrote in Labs 2–4 into the project.

```bash
# Create the project (the flags skip the interactive questions)
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

When `agentcore create` finishes, `app/BcaWorkshop/main.py` and `pyproject.toml` exist.
`pyproject.toml` is inside `app/BcaWorkshop/`, so add dependencies from there.
Now copy the code from Labs 2–4 into the app directory and merge the dependencies.

```bash
# Copy the Labs 2–4 code into the app directory
# (assuming each lab directory and BcaWorkshop/ share the same parent directory)
cp ../lab2/agents.py app/BcaWorkshop/
cp ../lab3/memory_store.py app/BcaWorkshop/
cp ../lab4/guardrail.py app/BcaWorkshop/

# Move to the directory that holds pyproject.toml and add the dependencies
cd app/BcaWorkshop
uv add strands-agents bedrock-agentcore boto3 aws-opentelemetry-distro
cd ../..   # go back to the BcaWorkshop/ root (run agentcore dev/deploy from here)
```

**Expected result**: `app/BcaWorkshop/` contains `main.py`, `agents.py`, `memory_store.py`, and
`guardrail.py`, and `app/BcaWorkshop/uv.lock` is updated.

### Step 2: Integrate Labs 2–4 — Connect Guardrail · Memory

Now that the code is copied, connect the features of each Lab.

**Connect the Guardrail — edit the top of `app/BcaWorkshop/agents.py`**

`agents.py` currently has these three lines.

```python
# Current (exactly as written in Lab 2)
from strands.models import BedrockModel
MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"   # ← keep this line
model = BedrockModel(model_id=MODEL_ID, temperature=0.2)
```

Keep `MODEL_ID` as it is, and replace the other two lines with the block below.

```
from strands.models import BedrockModel               ← replace
MODEL_ID = "..."                                       ← keep
model = BedrockModel(model_id=MODEL_ID, temperature=0.2)  ← replace
```

```python
# Replace the two lines above with the block below
# Remove from strands.models import BedrockModel — the line below replaces it
import os
from guardrail import create_guardrail, get_existing_guardrail
from strands.models.bedrock import BedrockModel, CacheConfig

# At module level, read only environment variables — calling an API at import time
# makes the Runtime exceed the 30-second initialization limit and fail to start.
_gid = os.environ.get("GUARDRAIL_ID")
_ver = os.environ.get("GUARDRAIL_VERSION")


def _make_model():
    """Create a BedrockModel. If the environment variables are missing, look up the existing Guardrail, and create one only if none exists."""
    global _gid, _ver
    if not _gid:
        # 1) Look up the existing bca-safety Guardrail
        _gid, _ver = get_existing_guardrail()
    if not _gid:
        # 2) If none exists, create a new one
        _gid, _ver = create_guardrail()
    return BedrockModel(
        model_id=MODEL_ID,
        guardrail_id=_gid,
        guardrail_version=_ver,
        temperature=0.2,
        cache_config=CacheConfig(strategy="auto"),
    )
```

Then add the lookup function to `app/BcaWorkshop/guardrail.py`.

```bash
cat >> app/BcaWorkshop/guardrail.py << 'EOF'


def get_existing_guardrail(name="bca-safety"):
    """Look up an existing Guardrail by name."""
    resp = bedrock.list_guardrails()
    for g in resp.get("guardrails", []):
        if g["name"] == name:
            return g["id"], g["version"]
    return None, None
EOF
```

Then replace `model=model` with `model=_make_model()` in the 4 places:
`analysis_specialist`, `exercise_specialist`, `nutrition_specialist`, and `build_supervisor`.

```bash
sed -i 's/model=model/model=_make_model()/g' app/BcaWorkshop/agents.py

# Check that all 4 places were replaced
grep -n "model=model\|model=_make_model" app/BcaWorkshop/agents.py
```

> **Setting the environment variables is faster.** If `GUARDRAIL_ID` / `GUARDRAIL_VERSION` are in the
> Runtime environment, `create_guardrail()` is not called and the first call is faster. Before the
> Step 6 deployment, set them in `agentcore.json` (recommended; see Step 6 below).

> `create_guardrail()` creates a new resource every time. In the workshop you already created
> a resource in Lab 4, so reuse it through the `GUARDRAIL_ID` / `GUARDRAIL_VERSION` environment variables.

```bash
# Look up the Guardrail ID and version created in Lab 4
aws bedrock list-guardrails --region us-west-2 \
  --query 'guardrails[?name==`bca-safety`].[id,version]' --output table
```

Pass them as environment variables when you deploy or run the dev server:

```bash
export GUARDRAIL_ID=<guardrailId created in Lab 4>
export GUARDRAIL_VERSION=<version, usually "DRAFT">
```

---

---

**Expected result**: Importing `agents.py` raises no error, and when you run `main.py` with the
`GUARDRAIL_ID` environment variable set, `create_guardrail` is not called again.

### Step 3: Write the Entrypoint — Including the Memory Connection

Replace `app/BcaWorkshop/main.py`, created by `agentcore create`, with the content below.
Fill in TODO ①② and connect to Memory using the environment variable (`MEMORY_ID`) set in Step 2.

```python
# app/BcaWorkshop/main.py
# TODO ①: Import the standard library needed for JSON parsing
import ________
import os
from agents import coach
from memory_store import save_session

# TODO ②: Import the AgentCore app wrapper
from bedrock_agentcore import ________

app = BedrockAgentCoreApp()

MEMORY_ID = os.environ.get("MEMORY_ID")   # memory_id created in Lab 3


# TODO ③: Mark this function as the Runtime entrypoint
@app.________
def invoke(payload):
    """Runtime entrypoint.

    agentcore invoke passes the input as {"prompt": "..."}.
    If you put a JSON string in prompt, it parses the measurement and runs the coaching.

    Args:
        payload: {"prompt": "<JSON string>", "user_sub": "...", "session_id": "..."}
    """
    # agentcore invoke wraps the string under the "prompt" key
    raw = payload.get("prompt", "{}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "prompt must be a JSON string"}

    measurement = data.get("measurement")
    if not measurement:
        return {"error": "The measurement key is missing"}

    user_sub = payload.get("user_sub", data.get("user_sub", "unknown"))
    session_id = payload.get("session_id", data.get("session_id", "session-default"))

    result = coach(measurement)

    if MEMORY_ID and user_sub != "unknown":
        save_session(MEMORY_ID, user_sub, session_id, measurement)

    return {"result": result}


if __name__ == "__main__":
    app.run()
```

Set the `MEMORY_ID` environment variable. Copy the `memory_id` printed in Lab 3, or look it up
with the command below. The name you gave at creation is included as a prefix in the `id` field of the response.

```bash
# List all Memories — find the id that starts with BodyCompositionTrend-
aws bedrock-agentcore-control list-memories \
  --query 'memories[?contains(id, `BodyCompositionTrend`)].id' \
  --output text

export MEMORY_ID=<output of the command above>
```

> **Cache integration**: The replacement block above already includes `cache_config=CacheConfig(strategy="auto")`.
> With `strategy="auto"`, Bedrock caches the system prompt and tool definitions automatically.
> For Claude Sonnet 4.5, the minimum cache size is 1,024 tokens.

### Step 4: Local Test

Before deploying, check the service contract locally.
Pass along the environment variables you set in Step 2.

> **If the port is in use**: In the workshop environment, 8080 and 8081 may already be in use. Pick
> another port with `--port` and use the same port in curl.

```bash
# Terminal 1 — run from the BcaWorkshop/ root
GUARDRAIL_ID=$GUARDRAIL_ID GUARDRAIL_VERSION=$GUARDRAIL_VERSION \
MEMORY_ID=$MEMORY_ID \
agentcore dev --port 8082 --no-browser
```

Open one more terminal and run curl.

```bash
# Terminal 2
curl -X POST http://localhost:8082/invocations \
  -H "Content-Type: application/json" \
  -d '{"measurement": {"obesity_analysis": {"pbf_percent": {"value": 32.5}}}}'
# The Supervisor calls 3 agents in sequence, so the response takes tens of seconds
# Expected: {"result": "...findings/exercise/meals..."}
```

**Expected result**: `/invocations` returns 200 and a `result`.
After checking, stop the server with `Ctrl+C` in terminal 1.

### Step 5: Enable Observability

Turn on CloudWatch Transaction Search and then deploy, and traces are collected. You already added
`aws-opentelemetry-distro` to the dependencies, so instrumentation is automatic.

```bash
# Enable CloudWatch Transaction Search (once per account)
aws xray update-trace-segment-destination \
  --destination CloudWatchLogs --region us-west-2
```

> If you get `InvalidRequestException: The destination is already set to CloudWatchLogs`,
> it is already enabled. This is fine, so go to the next step.

### Step 6: Deploy and Invoke

Set the execution role in `agentcore.json` and then deploy. `agentcore deploy` does not support the
`--execution-role` flag and reads it from the config file. Put the Guardrail environment variables
there too, so that the Runtime does not call an API during initialization.

```bash
# Add the execution role and environment variables to runtimes[0] of agentcore/agentcore.json
jq --arg role "$RUNTIME_ROLE" \
   --arg gid "$GUARDRAIL_ID" \
   --arg ver "$GUARDRAIL_VERSION" \
  '.runtimes[0].executionRoleArn = $role |
   .runtimes[0].environmentVariables = {"GUARDRAIL_ID": $gid, "GUARDRAIL_VERSION": $ver}' \
  agentcore/agentcore.json > /tmp/ac.json && mv /tmp/ac.json agentcore/agentcore.json

# Deploy — it is a uv project, so it deploys with Direct Code Deploy (zip)
# TODO ③: Complete the deploy command
agentcore ________ -y
```

When the deployment finishes, invoke it.

```bash
agentcore invoke '{"measurement": {"obesity_analysis": {"pbf_percent": {"value": 32.5}}}}'
# Expected: {"result": "...coaching result..."}
```

> `agentcore invoke` wraps the argument as `{"prompt": "..."}` and passes it to the Runtime.
> The JSON string above arrives as `payload["prompt"]`, and `main.py` parses it.

**Expected result**: `agentcore invoke` returns a coaching result, and the trace of this call
(including the order of tool calls) is visible in Transaction Search in the CloudWatch console.

---

## Verification

- [ ] The local `/invocations` returns 200 through `agentcore dev`
- [ ] The `model` in `agents.py` is replaced with a `BedrockModel` that includes the Guardrail arguments (`guardrail_id`, `guardrail_version`)
- [ ] `invoke` in `main.py` calls `save_session()` (Memory connection)
- [ ] The `@app.entrypoint` entrypoint exists in `main.py`
- [ ] The deployment specifies `AgentRuntimeRoleArn` as the execution role
- [ ] `agentcore invoke` returns a coaching result
- [ ] The call trace is collected in CloudWatch Transaction Search
- [ ] The traces and logs contain no user name (boundary check)

---

## Troubleshooting

| Symptom | Cause | Fix |
|------|------|------|
| The deployment goes the Container way | uv is not used | Check that it is a uv project. CodeZip is recommended when `uv.lock` exists |
| `agentcore dev` reports a port error | 8080 is in use | Specify another port such as `--port 8082`, and use the same port in curl |
| `Unsupported method POST` response | Another process holds that port | Check the port in use with `lsof -i :8082` and use a free port |
| The curl response takes too long | The Supervisor calls 3 agents in sequence | Normal. Wait tens of seconds |
| The deployment fails with AccessDenied | The execution role lacks permissions | Check that you specified `AgentRuntimeRoleArn`. Do not use an arbitrary role |
| `invoke` fails with ModuleNotFound (agents) | The Lab 2 code was not copied | Check that you ran `cp ../lab2/agents.py app/BcaWorkshop/` from Step 1 |
| The trace is not visible | Transaction Search is not enabled | Run the Step 5 command and redeploy. Collection takes a few minutes |
| `ImportError: guardrail` | guardrail.py was not copied | Check `cp ../lab4/guardrail.py app/BcaWorkshop/` from Step 1 |
| `ImportError: memory_store` | memory_store.py was not copied | Check `cp ../lab3/memory_store.py app/BcaWorkshop/` from Step 1 |
| A new Guardrail is created on every start | The GUARDRAIL_ID environment variable is not set | Set `export GUARDRAIL_ID=...` as described in Step 2 |
| `AccessDeniedException: CreateGuardrail` | The Runtime role lacks the permission | Add ListGuardrails and GetGuardrail with the `put-role-policy` from Step 2 |
| `ConflictException: Another guardrail has this name` | The environment variables were not passed, so create was retried | `get_existing_guardrail()` looks up first, so adding the role permission fixes it |
| The cold start is long | The first deployment installs the dependencies | Later updates are faster because the zip reuses the dependencies |

---

## 🏆 Challenge Task

1. **Keep the session** — Pass a session ID to `agentcore invoke` to connect it to the Lab 3 Memory,
   and check in the trace whether the second call from the same user refers to the previous session.
2. **Break down latency** — In the trace, separate the latency of the extraction tool (deterministic)
   from the agent calls (LLM), and explain with evidence where the time is spent.

---

When you finish, go to [Lab 6: Streamlit + ECS Express Mode](./06_frontend.md).

---

## Appendix: Answer Code

<details>
<summary>main.py · deployment TODO ①–④ answers (click to expand)</summary>

**TODO ① — JSON import**

```python
import json
```

`agentcore invoke` passes the input wrapped as `{"prompt": "..."}`, so you have to parse the
`payload["prompt"]` string as JSON.

**TODO ② — App wrapper import**

```python
from bedrock_agentcore import BedrockAgentCoreApp
```

`BedrockAgentCoreApp` handles the HTTP server (`/invocations`, `/ping`) for you.

**TODO ③ — Entrypoint decorator**

```python
@app.entrypoint
def invoke(payload):
```

`@app.entrypoint` registers this function as the `/invocations` handler. You do not have to write
the server code yourself.

**TODO ④ — Deploy command**

```bash
agentcore deploy -y
```

`agentcore deploy` packs the code into a zip, then uploads and deploys it. Before deploying, set the
execution role in `runtimes[0].executionRoleArn` of `agentcore.json` (added with the `jq` command
— see Step 6). `-y` skips the confirmation prompt.

### Summary

| # | Answer | Explanation |
|---|------|------|
| ① | `json` | Standard library that parses the prompt string as JSON |
| ② | `BedrockAgentCoreApp` | HTTP service contract wrapper |
| ③ | `entrypoint` | Register the `/invocations` entrypoint |
| ④ | `deploy -y` | zip packaging · upload · deploy (the execution role is preset in agentcore.json) |

</details>
