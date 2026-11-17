# Lab 3: Memory Trend Analysis (25 min)

## Learning Objectives

You create AgentCore Memory yourself and design its strategy. You store the measurement history of the same
user per session and analyze the change (delta) at Session 3. Users are isolated by Cognito `sub`, not by name.

> **Code state at the start of this Lab**: In Lab 2, the analysis, exercise, and meal agents handle a single
> set of measurements. This Lab stores and retrieves several sessions to answer "Is it better than last time?"
> Participants create the Memory resource themselves.

---

## Theory: Why You Create Memory Yourself and What You Isolate (8 min)

### Strategy design is the core of the learning

Memory is not baked into the template. Participants create it. The core of this Lab is how you split short-term
memory (raw events) from long-term memory (extracted summaries) and how you design the namespace.

| Type | What is stored | In this workshop |
|------|-----------|---------------|
| Short-term (events) | The raw content as is | Per-session measurement JSON |
| Long-term (strategy) | Summaries the model extracts and consolidates | Trend summary across sessions |

### User isolation — `sub`, not the name

You isolate users by `actor_id`. **Do not put the name in it.** A scanned name gets misread
(Lab 1), and under the boundary design (README) the name is excluded from logs, traces, and Memory, so
you use the Cognito `sub` (an immutable user ID).

```
actor_id = Cognito sub  (example: "a1b2c3d4-...")     <- not the name
session_id = session identifier   (example: "session-2026-08-14")
```

user-a and user-b have different `actor_id` values, so Memory isolates them automatically.

### user-a's 6-month trend (the delta answer)

| Metric | Session 1 | Session 3 | Change |
|------|-------|-------|------|
| Weight (kg) | 96.6 | 92.4 | **−4.2** |
| Body Fat Mass (kg) | 34.0 | 30.0 | **−4.0** |
| Skeletal Muscle Mass (kg) | 34.9 | 34.8 | −0.1 |
| Percent Body Fat (%) | 35.2 | 32.5 | −2.7 pp |

Of the 4.2 kg lost, 4.0 kg is body fat and only 0.1 kg is muscle loss. This is **high-quality weight loss without muscle loss**,
so "keep the current direction" is the right call. You cannot verify trend analysis with two different people.
It needs Session 3 of the same person.

---

## Start the Lab

```bash
mkdir -p lab3 && cd lab3
uv init --python 3.13 .
uv add bedrock-agentcore boto3
```

Get the Memory execution role ARN from the core stack (Memory uses it when it calls a model to extract summaries).

```bash
MEMORY_ROLE=$(aws cloudformation describe-stacks --stack-name bca-workshop-core \
  --region us-west-2 --query 'Stacks[0].Outputs[?OutputKey==`MemoryExecutionRoleArn`].OutputValue' \
  --output text)
echo "$MEMORY_ROLE"
# Expected output: arn:aws:iam::<account>:role/bca-workshop-memory-execution-role
```

### Step 1: Create Memory — design the strategy

Create `lab3/memory_store.py`.

```python
# lab3/memory_store.py
import json
import os
import time

# TODO ①: Import the AgentCore Memory client
from bedrock_agentcore.memory import ________

REGION = "us-west-2"
client = MemoryClient(region_name=REGION)


def create_trend_memory():
    """Creates a Memory with a session summary strategy."""
    # TODO ②: Create the Memory with a summary strategy (use the method that waits until creation completes)
    # - Put summaryMemoryStrategy in strategies
    # - Use {actorId}/{sessionId} in namespaceTemplates to isolate per user and per session
    memory = client.________(
        name="BodyCompositionTrend",
        strategies=[{
            "summaryMemoryStrategy": {
                "name": "SessionSummarizer",
                "namespaceTemplates": ["/trend/{actorId}/{sessionId}/"],
            }
        }],
        # TODO ⑤: The summary strategy makes Memory call a model, so it needs an execution role ARN.
        # - Fill in the name of the argument that takes this value. The value is read from the MEMORY_ROLE environment variable
        ________=os.environ["MEMORY_ROLE"],
    )
    return memory.get("id")
```

> `create_memory_and_wait` waits until the Memory becomes `ACTIVE`. When `summaryMemoryStrategy`
> extracts summaries, Memory calls a Bedrock model in your account, so you must pass the
> execution role ARN that grants that permission (TODO ⑤). The value is read from `os.environ["MEMORY_ROLE"]`,
> so pass the `MEMORY_ROLE` you looked up at the start of the lab as an environment variable when you run it (see Step 4).

### Step 2: Save a session — use sub as actor_id

```python
# lab3/memory_store.py (continued)

def save_session(memory_id, user_sub, session_id, measurement):
    """Saves the measurements of one session as an event.

    Args:
        user_sub: The Cognito sub. This value isolates the user, not the name.
        session_id: The session identifier.
        measurement: The normalized measurements (dict).
    """
    summary = {
        "weight_kg": measurement["body_composition_analysis"]["weight_kg"],
        "body_fat_mass_kg": measurement["body_composition_analysis"]["body_fat_mass_kg"]["value"],
        "skeletal_muscle_mass_kg": measurement["muscle_fat_analysis"]["skeletal_muscle_mass_kg"]["value"],
        "pbf_percent": measurement["obesity_analysis"]["pbf_percent"]["value"],
    }
    # TODO ③: Save the event. Put user_sub in actor_id, not the name
    client.create_event(
        memory_id=memory_id,
        actor_id=________,
        session_id=session_id,
        messages=[(json.dumps(summary, ensure_ascii=False), "USER")],
    )
```

### Step 3: Retrieve the trend — delta between sessions

```python
# lab3/memory_store.py (continued)

def get_trend(memory_id, user_sub, session_id):
    """Retrieves the stored summaries and runs a trend query."""
    # TODO ④: Retrieve the trend summary from the namespace
    # - namespace is the strategy template with the user and session substituted in
    memories = client.________(
        memory_id=memory_id,
        namespace=f"/trend/{user_sub}/{session_id}/",
        query="Summarize the trend in weight, body fat, and skeletal muscle mass across sessions",
    )
    return memories


def compute_delta(first, latest):
    """Computes the difference between two session summaries in code (deterministic)."""
    return {
        "weight_delta_kg": round(latest["weight_kg"] - first["weight_kg"], 1),
        "body_fat_mass_delta_kg": round(
            latest["body_fat_mass_kg"] - first["body_fat_mass_kg"], 1),
        "skeletal_muscle_mass_delta_kg": round(
            latest["skeletal_muscle_mass_kg"] - first["skeletal_muscle_mass_kg"], 1),
    }
```

### Step 4: Save Session 3 and check the delta

Save user-a's Session 3, then wait a moment for the summary to be extracted.

`memory_store.py` reads `os.environ["MEMORY_ROLE"]`, so you must pass this environment variable
when you run it (the `MEMORY_ROLE` value you looked up at the start of the lab).

```bash
MEMORY_ROLE=$MEMORY_ROLE uv run python -c "
import json, time, memory_store as ms
mid = ms.create_trend_memory()
print('memory_id:', mid)   # Reuse this value in Step 5 — copy it from the screen

SUB = 'user-a-sub-0001'   # In practice this is the Cognito sub. Do not use the name
gt = '../sample-data/ground-truth'
for seq in ('01','02','03'):
    m = json.load(open(f'{gt}/user-a-session-{seq}.json'))
    ms.save_session(mid, SUB, f'session-{seq}', m)
    print('saved session', seq)

# Code-based delta (deterministic) — can be checked against the ground truth
first = json.load(open(f'{gt}/user-a-session-01.json'))
latest = json.load(open(f'{gt}/user-a-session-03.json'))
def brief(d):
    return {
        'weight_kg': d['body_composition_analysis']['weight_kg'],
        'body_fat_mass_kg': d['body_composition_analysis']['body_fat_mass_kg']['value'],
        'skeletal_muscle_mass_kg': d['muscle_fat_analysis']['skeletal_muscle_mass_kg']['value'],
    }
print('delta:', ms.compute_delta(brief(first), brief(latest)))
# Expected: {'weight_delta_kg': -4.2, 'body_fat_mass_delta_kg': -4.0, 'skeletal_muscle_mass_delta_kg': -0.1}
"
```

**Expected result**: `compute_delta` returns weight −4.2 / body fat −4.0 / skeletal muscle −0.1
(matching `expected_trend_vs_session_01` in the ground-truth JSON). The Memory summary takes time to
extract, so if the retrieval comes back empty, try again after a moment.

### Step 5: Verify user isolation — another sub sees nothing

The isolation key is `actor_id` (= the Cognito `sub`), and the retrieval namespace `/trend/{sub}/...` also
embeds that `sub`. So **retrieving with another user's `sub` must not return someone else's sessions.**
This app lets people view only their own result sheets, so if this isolation breaks, another person's health history
is exposed. Do not stop at saying so. Check it yourself.

Reuse the Memory you created in Step 4. Do not create a new one and do not save Session 3 again
— the user-a data was already saved in Step 4. Pass the `memory_id` that Step 4 printed as the
environment variable `MEMORY_ID`. Retrieving with user-a's `sub` should return results, and retrieving with the `sub` of user-b,
who has saved nothing, should return nothing.

```bash
# Paste the memory_id from the Step 4 output as is
export MEMORY_ID=<the memory_id printed by Step 4>

MEMORY_ID=$MEMORY_ID uv run python -c "
import os, memory_store as ms

mid = os.environ['MEMORY_ID']   # Reuse the memory_id printed in Step 4
A_SUB, B_SUB = 'user-a-sub-0001', 'user-b-sub-0002'   # Two different Cognito subs

# Retrieve both users' namespaces with the same session_id and compare
a_hits = ms.get_trend(mid, A_SUB, 'session-03')   # user-a's own — should have results
b_hits = ms.get_trend(mid, B_SUB, 'session-03')   # user-b — must not see user-a's data

def count(hits):
    # Count the length whatever the retrieve_memories response shape (list or dict)
    if isinstance(hits, dict):
        hits = hits.get('memoryRecords') or hits.get('memories') or []
    return len(hits or [])

print('user-a sub hit count:', count(a_hits))
print('user-b sub hit count:', count(b_hits))
assert count(b_hits) == 0, 'Isolation failure: user-a data was returned for the user-b sub'
print('Isolation check OK — other subs cannot retrieve it')
"
```

> If `MEMORY_ID` is empty or wrong, the retrieval fails. Check that you pasted the value after
> `memory_id:` in the Step 4 output as is.

**Expected result**: It prints `user-b sub hit count: 0` and the `assert` passes. Because user-a was saved in
Step 4, the count rises to 1 or more once the summary is extracted (if extraction is delayed, user-a may be
0, but the point of the isolation check is that **user-b is always 0**).

> Note: `session_id` separates sessions, and user isolation is handled by `actor_id` (`sub`).
> So even if you retrieve the same `session-03`, a different `sub` gives a different namespace.

---

## Verification

- [ ] `create_trend_memory` returns a `memory_id` and the Memory is `ACTIVE`
- [ ] You filled in the `memory_execution_role_arn` argument to pass the execution role (required for the summary strategy, TODO ⑤)
- [ ] `save_session` puts the `sub`, not the name, in `actor_id`
- [ ] user-a Session 3 is saved
- [ ] The `compute_delta` result is weight −4.2 / body fat −4.0 / skeletal muscle −0.1
- [ ] user-a's sessions are not retrieved with user-b's `sub` (the Step 5 isolation check passes, `assert` OK)

---

## Troubleshooting

| Symptom | Cause | Fix |
|------|------|------|
| `create_memory_and_wait` fails with AccessDenied | The execution role ARN was not passed | Check that you passed the environment variable when running, as `MEMORY_ROLE=$MEMORY_ROLE uv run python ...` |
| `KeyError: 'MEMORY_ROLE'` | The environment variable was not passed | Same as above. Also check that you looked up `MEMORY_ROLE` at the start of the lab |
| The `retrieve_memories` result is empty | Summary extraction is still in progress | Retry after 30–60 seconds. Short-term events are immediate, long-term summaries are delayed |
| Another user's data is mixed in | `actor_id` was set to a fixed value | Check that you put a different `sub` for each user |
| The Step 5 `assert` stops with an isolation failure | The `sub` is not reflected in the save or retrieval namespace | Check that both `actor_id` in `create_event` and `namespace` in `get_trend` use the `sub` |
| Retrieval fails because of a `namespace` mismatch | The template and the retrieval string differ | Use the same format for the strategy's `namespaceTemplates` and the retrieval `namespace` |
| The delta sign is reversed | The first/latest order is swapped | Check the argument order of `compute_delta(first, latest)` |
| `ThrottlingException` | Many events in a short time | Add a delay between saves or retry |

---

## 🏆 Challenge Task

1. **Inject the trend into the agent** — Extend the prompt so that Lab 2's `analysis_specialist` receives the
   `compute_delta` result as well as the current measurements, and gives findings "compared with last time."
2. **Pace estimate** — Use the average monthly weight-loss rate to calculate the remaining months until the target weight,
   and include it in the findings (the `assessment_ko` in the ground-truth JSON states about 27 months).

---

When you finish, go to [Lab 4: Guardrail + Cache](./04_guardrail_cache.md).

---

## Appendix: Answer Code

<details>
<summary>memory_store.py TODO ①–⑤ answers (click to expand)</summary>

**TODO ① — Import the Memory client**

```python
from bedrock_agentcore.memory import MemoryClient
```

This is the high-level SDK client in the `bedrock-agentcore` package. It is more concise than low-level boto3 calls.

**TODO ② — Create Memory (with waiting)**

```python
memory = client.create_memory_and_wait(
```

`create_memory_and_wait` polls until the Memory becomes `ACTIVE`. You can save events right away,
which suits the lab. You fill in the execution role ARN argument in TODO ⑤.

**TODO ③ — sub as actor_id**

```python
actor_id=user_sub,
```

`actor_id` is the user isolation key. Putting the Cognito `sub` in it instead of the name avoids misreading and exposure of personal information.

**TODO ④ — Retrieve the trend**

```python
memories = client.retrieve_memories(
```

`retrieve_memories` fetches the summaries extracted into the namespace through semantic search.

**TODO ⑤ — Name of the execution role argument** (it goes inside the `create_memory_and_wait` call of TODO ②)

```python
memory_execution_role_arn=os.environ["MEMORY_ROLE"],
```

When `summaryMemoryStrategy` creates summaries, Memory calls a Bedrock model in your account, so you must pass
the execution role ARN that grants that permission as the `memory_execution_role_arn` argument. The value is read from
`os.environ["MEMORY_ROLE"]`, and `MEMORY_ROLE` is the value you got at the start of the lab from the core stack output
(`MemoryExecutionRoleArn`). When you run it, pass the environment variable in the form `MEMORY_ROLE=$MEMORY_ROLE uv run python ...`
(Step 4). If you leave it out, the `os.environ` lookup fails with `KeyError`.

### Summary

| # | Answer | Explanation |
|---|------|------|
| ① | `MemoryClient` | The high-level AgentCore Memory SDK client |
| ② | `create_memory_and_wait` | Creation that waits until ACTIVE |
| ③ | `user_sub` | The Cognito sub, not the name, as the isolation key |
| ④ | `retrieve_memories` | Retrieves summaries from the namespace |
| ⑤ | `memory_execution_role_arn` | The summary strategy calls a model, so it needs the execution role argument |

</details>
