# Lab 2: Specialist Agents + Supervisor (45 min)

## Learning Objectives

With the Strands Agents SDK, you build three specialist agents for body composition analysis,
exercise prescription, and meal suggestion. You wrap each one in `@tool` so that a Supervisor
orchestrates them, which completes the Agent-as-Tool structure. You also add sequential chaining
from exercise to meals and a consistency check.

> **Code state at the start of this Lab**: In Lab 1, the `extract_body_composition` tool returns
> normalized measurements (a dict). This Lab writes agents that take those measurements as input.
> The Runtime is not deployed yet, so you run everything locally.

---

## Theory: Agent-as-Tool and Sequential Chaining (12 min)

### Why four agents

| Agent | Role | Nature of judgment |
|----------|------|-----------|
| **Supervisor** | Routing · consistency check · final synthesis | Orchestration |
| analysis (body composition analysis) | measurements → findings | Interpretation |
| exercise (exercise prescription) | findings → exercise plan | Prescription |
| nutrition (meal suggestion) | findings + **exercise plan** → meal plan | Prescription |

As you saw in Lab 1, extraction is a **tool** (deterministic). All four of these need judgment, so they are **agents**.

### The Agent-as-Tool pattern

The Supervisor **calls specialist agents like tools**. When you wrap a specialist agent in a `@tool` function,
the Supervisor's model calls that function when it decides "I need to analyze the body composition." Everything
runs inside the same Python process.

```
Supervisor Agent
   │ tools=[analysis_specialist, exercise_specialist, nutrition_specialist]
   ▼
@tool analysis_specialist(measurement)          -> findings
@tool exercise_specialist(findings)             -> exercise plan
@tool nutrition_specialist(findings, exercise)  -> meal plan   # takes the exercise plan as input
```

### Chain exercise → meals sequentially

If you run the two agents independently, they produce contradictory plans. If the meal plan suggests a large
calorie deficit while the exercise plan prescribes high-intensity strength training, the result is muscle loss.
So the order is fixed as **analysis → exercise → meals**, and the nutrition agent takes the exercise plan as
input. At the end, the Supervisor checks consistency.

### The name is not sent to the agents

The measurements contain a name, but **the name plays no role in the analysis.** Following the privacy boundary
design (00_setup · README), the name is excluded from the agent context. If it is never sent to the LLM in
the first place, no masking is needed.

### The D-shape trap (user-b)

The textbook description of the D-shape body shape classification is "an ideal state with a lot of muscle and little fat."
But user-b is a D-shape whose three percent-of-standard indicators are **all below 100%** (underweight + low muscle mass).
Answering "ideal" from the shape alone is a misjudgment. The analysis agent must not fall for the shape pattern. It has to read
the absolute percent-of-standard values as well. You check this case at the end of the lab.

---

## Start the Lab

Work separately from `lab1/` of Lab 1. Install Strands and the AgentCore SDK.

```bash
mkdir -p lab2 && cd lab2
uv init --python 3.13 .
uv add strands-agents boto3
```

### Step 1: System prompts for the specialist agents

Create `lab2/agents.py`. First import the SDK and define the shared model.

```python
# lab2/agents.py
import json

# TODO ①: Import Agent and tool from Strands
from strands import ________, ________
from strands.models import BedrockModel

MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"

# The model shared by the specialist agents. A low temperature keeps the prescriptions consistent.
model = BedrockModel(model_id=MODEL_ID, temperature=0.2)

DISCLAIMER = (
    "This analysis is health reference information, not a medical diagnosis. "
    "It does not give a definitive diagnosis or prescribe drugs or supplements."
)

ANALYSIS_PROMPT = (
    "You are a body composition analysis expert. Receive the normalized measurements (JSON) and present your findings.\n"
    "- The body type classification (C/I/D) describes shape only. Always read the absolute percent-of-standard values as well.\n"
    "- Even for a D-shape, if all three indicators are below standard, this is underweight and low muscle mass, not 'ideal'.\n"
    "- Point out any upper-lower or left-right imbalance in segmental lean mass.\n"
    f"- Do not give a definitive diagnosis. End every finding with the following: {DISCLAIMER}"
)

EXERCISE_PROMPT = (
    "You are an exercise prescription expert. Receive the analysis findings and present an exercise plan.\n"
    "- If there is a segmental imbalance, prioritize exercises that strengthen the weaker segments.\n"
    "- Specify the ratio of aerobic to strength training, the weekly frequency, and the intensity.\n"
    "- Do not give a definitive diagnosis or prescribe drugs."
)

NUTRITION_PROMPT = (
    "You are a meal planning expert. Receive the analysis findings together with the 'exercise plan' and present a meal plan.\n"
    "- Do not contradict the intensity of the exercise plan. Never combine high-intensity strength training with an extreme calorie deficit.\n"
    "- Do not recommend extreme calorie restriction. Do not prescribe drugs or supplements."
)
```

### Step 2: Wrap the analysis agent as a tool

Create and call each specialist agent inside a `@tool` function. The function's docstring and type hints
become the tool specification that the Supervisor sees.

```python
# lab2/agents.py (continued)

def _strip_pii(measurement: dict) -> dict:
    """Remove the name before passing the measurements to an agent (privacy boundary)."""
    # TODO ⑥: Build a new dict from measurement without the 'name' key
    # - The name is not needed for the analysis, so it never goes into the LLM context
    return {k: v for k, v in measurement.items() if k != ________}


# TODO ②: Add the decorator that turns this function into a Strands tool
@________
def analysis_specialist(measurement: dict) -> str:
    """Analyzes the body composition measurements (JSON) and returns the findings.

    Args:
        measurement: Normalized body composition measurements. Passed without the name.
    Returns:
        Findings text about body shape, obesity, and segmental balance.
    """
    safe = _strip_pii(measurement)
    # TODO ③: Create an Agent with the analysis system prompt
    # - model=model, system_prompt=ANALYSIS_PROMPT, tools=[] (no tools needed)
    agent = ________(model=model, system_prompt=ANALYSIS_PROMPT, tools=[])
    response = agent(f"Analyze the following measurements:\n{json.dumps(safe, ensure_ascii=False)}")
    return str(response)
```

### Step 3: Exercise and meal agents — sequential chaining

The exercise agent takes the findings as input. The meal agent takes the findings **and the exercise plan** as input.

```python
# lab2/agents.py (continued)

@tool
def exercise_specialist(findings: str) -> str:
    """Takes the analysis findings and returns an exercise plan.

    Args:
        findings: The findings text produced by analysis_specialist.
    Returns:
        An exercise plan with the aerobic/strength mix, frequency, and intensity.
    """
    agent = Agent(model=model, system_prompt=EXERCISE_PROMPT, tools=[])
    return str(agent(f"Present an exercise plan that fits the following findings:\n{findings}"))


# TODO ④: Complete the signature so the meal agent takes the 'exercise plan' as input
# - Sequential chaining: this makes the meal plan consistent with the exercise plan
@tool
def nutrition_specialist(findings: str, ________: str) -> str:
    """Takes the analysis findings and the exercise plan and returns a meal plan.

    Args:
        findings: The analysis findings.
        exercise_plan: The exercise plan produced by exercise_specialist.
    Returns:
        A meal plan consistent with the exercise plan.
    """
    agent = Agent(model=model, system_prompt=NUTRITION_PROMPT, tools=[])
    prompt = (
        f"Findings:\n{findings}\n\nExercise plan:\n{exercise_plan}\n\n"
        "Present a meal plan that does not contradict the exercise plan above."
    )
    return str(agent(prompt))
```

### Step 4: Supervisor orchestration

The Supervisor registers the three specialist agents as tools. Its system prompt tells it the order
(analysis → exercise → meals) and the consistency check.

```python
# lab2/agents.py (continued)

SUPERVISOR_PROMPT = (
    "You are the Supervisor that orchestrates body composition coaching. Follow this order without exception.\n"
    "1) Get the findings from analysis_specialist.\n"
    "2) Get the exercise plan from exercise_specialist.\n"
    "3) Pass both the findings and the exercise plan to nutrition_specialist to get the meal plan.\n"
    "4) If the exercise and meal plans contradict each other (for example, high-intensity strength training + an extreme calorie deficit), point it out and adjust.\n"
    "In the final answer, organize the findings, exercise, and meals, and include a disclaimer that this is health reference information."
)


def build_supervisor() -> "Agent":
    # TODO ⑤: Register the three specialist agents as the Supervisor's tools
    return Agent(
        model=model,
        system_prompt=SUPERVISOR_PROMPT,
        tools=[________, ________, ________],
    )


def coach(measurement: dict) -> str:
    """Takes the measurements, runs the Supervisor, and returns the final coaching."""
    supervisor = build_supervisor()
    return str(supervisor(
        "Run the coaching with the following measurements. Always in the order analysis → exercise → meals."
        f"\n{json.dumps(measurement, ensure_ascii=False)}"
    ))
```

### Step 5: Run locally — user-a and the D-shape trap (user-b)

Use the Lab 1 ground-truth JSON as the measurements and run each person.

```bash
uv run python -c "
import json, agents
# user-a-session-03 (C-shape, obese) — weight-loss direction
m_a = json.load(open('../sample-data/ground-truth/user-a-session-03.json'))
print('=== user-a ===')
print(agents.analysis_specialist({
    'body_type': m_a['muscle_fat_analysis']['body_type'],
    'bmi': m_a['obesity_analysis']['bmi']['value'],
    'pbf_percent': m_a['obesity_analysis']['pbf_percent']['value'],
}))
# user-b-session-01 (D-shape trap) — must point to weight gain
m_b = json.load(open('../sample-data/ground-truth/user-b-session-01.json'))
print('=== user-b (D-shape trap) ===')
print(agents.analysis_specialist({
    'body_type': m_b['muscle_fat_analysis']['body_type'],
    'muscle_fat_analysis': m_b['muscle_fat_analysis'],
}))
"
```

**Expected result**: The user-a findings point toward body fat reduction. The user-b findings do not call the D-shape
"ideal." They point out underweight and low muscle mass and recommend **weight gain**. Both sets of findings
must end with the disclaimer text.

---

## Verification

- [ ] `agents.py` loads without import errors
- [ ] The dict passed to `analysis_specialist` has no `name` key (privacy boundary)
- [ ] The Supervisor calls the tools in the order analysis → exercise → meals
- [ ] `nutrition_specialist` takes the exercise plan as input (2 arguments in the signature)
- [ ] The user-a findings point toward weight loss and the user-b findings toward weight gain
- [ ] Every set of findings includes the health reference information disclaimer

---

## Troubleshooting

| Symptom | Cause | Fix |
|------|------|------|
| `ImportError: cannot import name 'tool'` | Package not installed | Run `uv add strands-agents`, then run with `uv run` |
| `AccessDeniedException` (bedrock) | Model access not approved | Enable Claude Sonnet 4.5 model access in the console |
| The Supervisor calls the meal agent first | The order instruction is weak | Check that `SUPERVISOR_PROMPT` states the order with numbers |
| Exercise and meal plans contradict each other | The sequential chain is broken | Check that `nutrition_specialist` actually receives `exercise_plan` (TODO ④) |
| The user-b findings say "ideal body type" | The judgment looked at the shape only | Check the "absolute percent-of-standard values" instruction in `ANALYSIS_PROMPT` |
| The name appears in the response | PII removal is missing | Check that `_strip_pii` is actually called (TODO ⑥) |
| `ThrottlingException` | Many calls in a short time | Retry or add a delay between calls. Keep the workshop account limits in mind |

---

## 🏆 Challenge Task

1. **Routing branch** — First branch into a "weight-loss track / weight-gain track" from the body shape and PBF of the measurements,
   and put that in the Supervisor prompt as a hint. Check that user-a and user-b take opposite tracks.
2. **Automatic consistency check** — Add a code-based check (`check_consistency`) that returns a warning when the
   exercise plan contains "high intensity" and the meal plan contains "calorie deficit" at the same time.

---

When you finish, go to [Lab 3: Memory Trend Analysis](./03_memory.md).

---

## Appendix: Answer Code

<details>
<summary>agents.py TODO ①–⑥ answers (click to expand)</summary>

**TODO ① — SDK import**

```python
from strands import Agent, tool
```

`Agent` is the agent itself, and `tool` is the decorator that turns a function into a tool.

**TODO ② — Tool decorator**

```python
@tool
def analysis_specialist(measurement: dict) -> str:
```

`@tool` automatically generates the tool specification (name, description, input schema) from the docstring and type hints.

**TODO ③ — Create the analysis Agent**

```python
agent = Agent(model=model, system_prompt=ANALYSIS_PROMPT, tools=[])
```

A specialist agent needs no other tools, so `tools=[]`. It only makes judgments.

**TODO ④ — Meal agent signature**

```python
def nutrition_specialist(findings: str, exercise_plan: str) -> str:
```

Sequential chaining works only if the meal agent takes the exercise plan as input. The name of the second argument must match the
`exercise_plan` used in the function body.

**TODO ⑤ — Register the Supervisor's tools**

```python
tools=[analysis_specialist, exercise_specialist, nutrition_specialist],
```

Register the three specialist agents (tools) with the Supervisor. The Supervisor's model decides the order and calls them.

**TODO ⑥ — Exclude the name**

```python
return {k: v for k, v in measurement.items() if k != "name"}
```

The name is not used in the analysis, so it does not go into the LLM context. This separates the boundary instead of masking.

### Summary

| # | Answer | Explanation |
|---|------|------|
| ① | `Agent, tool` | The Strands agent itself and the tool decorator |
| ② | `tool` | Turns the function into a tool the Supervisor can call |
| ③ | `Agent` | Creates the specialist agent (no tools) |
| ④ | `exercise_plan` | Sequential chaining: the meal agent receives the exercise plan |
| ⑤ | `analysis_specialist, exercise_specialist, nutrition_specialist` | The Supervisor's 3 tools |
| ⑥ | `"name"` | Exclude the name from the context (privacy boundary) |

</details>
