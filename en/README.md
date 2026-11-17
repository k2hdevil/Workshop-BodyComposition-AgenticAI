> 🌐 **English** | [Korean](../README.md)

# Body Composition Analysis Agentic AI Workshop

## An app where AI reads your body composition report and suggests exercise and meals (4 hours)

> All body composition result sheets used in this workshop are fictional synthetic data.
> They are unrelated to any real person, organization, or measuring device and are used for education only.

---

## Course Overview

| Item | Details |
|------|---------|
| Course name | Body Composition Analysis Agentic AI Workshop |
| Duration | **4 hours (240 min)** — 187 min of labs (78%) |
| Level | 300 (Advanced) |
| Audience | AI/ML engineers, backend and full-stack developers, solutions architects |
| Core technology | Amazon Bedrock AgentCore, Strands Agents SDK, Claude Sonnet 4.5 |
| Region | us-west-2 (Oregon) |
| IDE | VS Code Server (EC2, browser access) |
| Deliverable | **A deployed web app reachable over HTTPS** |

As you fill in the blanks (`________`), the code accumulates from Lab to Lab, and at the end a working
web application is deployed to AWS. The goal is to reach "I deployed something that runs" within 4 hours.

---

## The App You Build

When a user uploads their own body composition result sheet PDF, several agents work together to analyze it,
track changes between sessions, and suggest an exercise and meal plan.

```
                        User (browser)
                             │
                    Cognito login (OIDC)
                             │
                    ┌────────▼───────────────┐
                    │  Streamlit app         │  ECS Express Mode (HTTPS)
                    │  Upload / trend chart  │
                    │  Report / download     │
                    └────────┬───────────────┘
                             │  access token
                    ┌────────▼───────────────────────────────────────────────────┐
                    │  AgentCore Runtime                                         │
                    │                                                            │
                    │      Supervisor Agent                                      │
                    │      Routing · consistency check · final recommendation    │
                    │        │                                                   │
                    │   ┌────┴──────────────┬─────────────────────┐              │
                    │   ▼                   ▼                     ▼              │
                    │  Body composition   Exercise              Meal             │
                    │  analysis agent     prescription agent    suggestion agent │
                    │   (analysis → exercise → meal sequential chaining)         │
                    └────────┬───────────────────────────────────────────────────┘
                             │
                    ┌────────▼─────────────────┐        ┌──────────────────────────────────┐
                    │  AgentCore Gateway       │        │  AgentCore Memory                │
                    │  Sheet extraction (λ)    │        │  Per-session measurement history │
                    │  Report generation (λ)   │        │  Per-user isolation              │
                    └──────────────────────────┘        └──────────────────────────────────┘
```

There are **4 agents**. Result sheet extraction is a **tool**, not an agent. See the design decisions below for the reason.

---

## Learning Objectives

After this workshop you can:

1. Build a multi-agent system with the Strands Agents SDK and orchestrate it with the Agent-as-Tool pattern
2. Design for the difference between deterministic work (document parsing) and work that requires judgment (interpretation and suggestions)
3. Deploy to AgentCore Runtime with CodeZip and trace it with Observability
4. Manage time-series measurement history with AgentCore Memory and analyze changes between sessions
5. Connect Lambda tools as MCP through AgentCore Gateway and isolate data per user
6. Block definitive diagnoses and medication prescriptions with Bedrock Guardrails, and separate the privacy boundary in code
7. Reduce cost and latency with prompt and tool caching, and understand the conflict between caching and context compression
8. Run a regression check of document extraction accuracy against Ground Truth with AgentCore Evaluations
9. Deploy a Streamlit app to ECS Express Mode and connect Cognito authentication

---

## Timetable (240 min)

This table is the **single source of truth** for time allocation. If the minutes in a Lab document title differ, align them with this table.

| Time | Content | Type | Min | Document |
|------|---------|------|-----|----------|
| 0:00–0:12 | Opening · scenario · check pre-provisioned resources | Theory | 12 | `00_setup.md` |
| 0:12–0:25 | AgentCore components · Agent-as-Tool · **Why result sheet extraction is not an agent** | Theory | 13 | `00_setup.md` |
| 0:25–1:05 | **Lab 1** Result sheet extraction — Gateway MCP tool + value validation + vision fallback | Lab | 40 | `01_extract.md` |
| 1:05–1:50 | **Lab 2** 3 specialist agents + Supervisor orchestration | Lab | 45 | `02_agents.md` |
| 1:50–2:00 | Break | — | 10 | |
| 2:00–2:25 | **Lab 3** Memory trend analysis — delta across 3 sessions | Lab | 25 | `03_memory.md` |
| 2:25–2:40 | **Lab 4** Guardrail + prompt cache + privacy boundary separation | Lab | 15 | `04_guardrail_cache.md` |
| 2:40–3:05 | **Lab 5** Runtime deployment (CodeZip) + Observability | Lab | 25 | `05_deploy.md` |
| 3:05–3:15 | Break | — | 10 | |
| 3:15–3:40 | **Lab 6** Streamlit frontend + ECS Express Mode deployment + Cognito | Lab | 25 | `06_frontend.md` |
| 3:40–3:52 | **Lab 7** Evaluations — extraction accuracy against Ground Truth | Lab | 12 | `07_evaluation.md` |
| 3:52–4:00 | Action Items · resource cleanup · wrap-up | Theory | 8 | `99_cleanup.md` |

| Type | Time | Share |
|------|------|-------|
| Theory | 33 min | 14% |
| **Lab** | **187 min** | **78%** |
| Break | 20 min | 8% |

---

## Pre-provisioned Resources

To finish the app in 4 hours, you cannot spend time on infrastructure setup. The resources below are
**already created** with CloudFormation, and participants only write code.

| Resource | Purpose | What participants do |
|----------|---------|----------------------|
| VS Code Server (EC2) | Lab IDE | Connect with a browser |
| Cognito User Pool + App Client | User authentication | Connect it to Streamlit |
| AgentCore Gateway | Expose tools as MCP | Call the tools |
| Lambda — sheet extraction | PDF parsing + vision fallback | Call it and validate the result |
| Lambda — report generation | PDF report | Call it |
| AgentCore Memory | Store measurement history | Connect with a Hook |
| Bedrock Guardrail | Block diagnoses and prescriptions | Attach it to the agent |
| S3 bucket | Result sheets and outputs | Use the upload path |
| IAM roles | Least-privilege execution roles | Use as they are |
| 5 sample result sheet PDFs | Lab data | Read from S3 |

**Building Gateway, Cognito, and Cedar policies yourself is not part of the labs.** The labs cover only
connecting to what already exists and checking that it works. This is a deliberate choice made because of the 4-hour limit.

---

## Sample Data

The core scenario uses 4 documents (3 sessions of one person + 1 session of another person); a fifth sample,
`user-a-session-04`, is included as an extra. Trend analysis cannot be validated with two different people.

| Document | Person | Measured | Format | Role |
|----------|--------|----------|--------|------|
| `user-a-session-01` | Dohyun Kim, 44, male | 2026-02-14 | **Scanned** | Trend baseline · obesity |
| `user-a-session-02` | Dohyun Kim | 2026-05-16 | Digital | Improvement in progress |
| `user-a-session-03` | Dohyun Kim | 2026-08-14 | Digital | Latest · delta analysis |
| `user-b-session-01` | Jieun Park, 32, female | 2026-08-18 | Digital | Different user · underweight |
| `user-a-session-04` | Dohyun Kim | 2026-11-13 | Digital | Extra sample · crosses into Obesity Stage 1 (not used by the labs) |

Some traps are planted on purpose.

- **Session 1 is a scanned copy with no text layer.** A structural parser alone fails, and only the vision fallback passes.
- **user-b is a D-shape, but all three indicators are below standard.** Answering "D-shape = ideal" is a misjudgment.
  The actual findings are underweight plus low muscle mass, and the recommended direction must be the opposite of user-a's.

See [sample-data/README.md](./sample-data/README.md).

---

## Result Sheet Layout (4 Sections)

| Section | Contents |
|---------|----------|
| Body Composition Analysis | Total Body Water / Protein / Minerals / Body Fat Mass |
| Muscle-Fat Analysis | Weight / Skeletal Muscle Mass / Body Fat Mass → C·I·D body type classification |
| Obesity Analysis | BMI (apparent obesity) / PBF (actual body fat percentage) |
| Segmental Lean Analysis | Right Arm / Left Arm / Trunk / Right Leg / Left Leg |

The body shape classification is read from the shape formed by connecting the ends of the three bars.

- **C-shape** Low muscle relative to weight and fat
- **I-shape** All three indicators balanced within the standard range
- **D-shape** High muscle and low fat relative to weight

The standard body fat percentage is **male 10~20%**, **female 18~28%**.

---

## Key Design Decisions

These are the reasons behind the choices this workshop makes. They are also teaching points.

### Result sheet extraction is a tool, not an agent

Opening a PDF, extracting values, and validating them is deterministic work. Wrapping it in an LLM loop adds only latency, cost, and non-determinism
and gains nothing. However, result sheet layouts differ by device and model year, so when structural parsing fails,
the tool falls back to a vision model. That fallback is also **a tool that calls a model once**, not an agent with an autonomous loop.

```
@tool extract_body_composition(s3_key)
 ├─ 1st   pdfplumber structural parsing   text-layer PDF · no LLM call · deterministic
 ├─ 2nd   Converse document fallback      scanned copy · Bedrock analyzes the pages visually
 └─ Check component sum = weight, BMI recomputation (code)
```

**Both paths are pure Python, so there are no native dependencies.** This is confirmed by measurement: the Bedrock
Converse document block reads even a scanned copy with no text layer **automatically, with no extra configuration**.
So you need no rasterization library (PyMuPDF, poppler) and no Code Interpreter.

The reason for putting `pdfplumber` first is that extracting from a text PDF deterministically, without an LLM call, is better on cost, latency, and
reproducibility. In Lab 1 you compare the token usage of the two paths yourself
(the same result sheet: 3,181 tokens on the text path / 1,654 tokens on the image path; measured on the Korean-language sheet).

### Do not make security decisions from names extracted from a sheet

To verify identity, the app compares the logged-in user's name with the name on the sheet. **Names are the least reliable field on a scanned sheet.** In testing with the Korean-language edition of the sheet, the vision model misread one syllable of the name in 5 of 5 runs at temperature=0, while every number was correct. Retrying does not fix it. Latin-letter names can fail the same way (for example `Dohyun` read as `Dohyum`), and one changed character is enough to break an exact match. Blocking on exact match would lock out legitimate users.

| Verdict | Handling |
|---------|----------|
| Exact match | Pass |
| Edit distance 1 or less | **Warn and continue** — ask the user to confirm it is their own sheet |
| Anything else | Block |

The teaching point: **never make a security decision from OCR output.** Excluding the name from the agent context follows the same reasoning. The name is the least trustworthy field.

### Exercise and meals are chained sequentially

Running the two agents independently produces contradictory plans. If the meal plan suggests a large calorie deficit while the exercise plan
prescribes high-intensity strength training, it causes muscle loss. So the order is fixed as **analysis → exercise → meals (takes the exercise plan as input)**,
and the Supervisor checks consistency.

### Personal information is handled with boundaries, not masking

This is an app where people view their own result sheets, so the name must appear on screen. Instead, the app separates boundaries.

| Boundary | Name | Age | Handling |
|----------|------|-----|----------|
| Screen (user) | Shown | Shown | Uses the name from the Cognito profile |
| Agent (LLM context) | **Excluded** | Needed | The name plays no role in the analysis |
| Logs · traces · Memory | **Excluded** | Excluded | Replaced by the Cognito `sub` |

If you never send it to the LLM, there is nothing to mask. Guardrails are the last line of defense, not the first.

The name extracted from the sheet is **for identity checks, not for display**. If the name differs between the logged-in user and the sheet,
the app treats it as an upload of someone else's sheet and warns.

### Guardrails block risks that actually exist

| Risk | What happens in this app | Response |
|------|--------------------------|----------|
| Definitive diagnosis | Body fat 32.5% + visceral fat 15 → "You have metabolic syndrome" | Denied topic (DENY) |
| Medication/supplement prescription | Naming a specific drug or dose | Denied topic (DENY) |
| Indirect prompt injection | **Malicious text inserted into an uploaded PDF** | `PROMPT_ATTACK` filter |

The third is the attack surface unique to this app. The contents of a user-uploaded file go straight into the LLM context.

### Caching and context compression need a boundary between them

Caching requires a stable prefix, and compression rewrites the conversation history and breaks that prefix.
If you use them together naively, the cache hit rate drops to 0.

```
[ System prompt + tool definitions ]   <- cache (never changes)
[ Normalized measurement data ]        <- cache (fixed within a session)
[ Conversation history ]               <- compression target (after the cache boundary)
```

Claude Sonnet 4.5's minimum cache size is **1,024** tokens, and a request can have at most 4 checkpoints.

### Runtime deployment uses CodeZip; frontend deployment uses ECS Express Mode

For the agent Runtime, Docker builds and ECR pushes are a failure point in a 4-hour session, so it is deployed with **CodeZip (Direct
Code Deploy)**. Uploading a zip is enough to deploy, and the cold start is shorter too.

The frontend (Streamlit) was originally planned for App Runner, but **App Runner stopped accepting new
customers**, so temporary workshop accounts cannot use it. The replacement is **ECS Express Mode**. From a single container image it
configures a Fargate service, an HTTPS load balancer, autoscaling, and a URL automatically. It needs a container, but
**only the frontend is containerized, thinly** (a 6-line Dockerfile, one ECR push), so it does not conflict with the CodeZip decision for the Runtime.

---

## Prerequisites

**Required**

- Intermediate Python or above (type hints, decorators, `dict`/`json` handling)
- Basic understanding of AWS services (IAM, S3, Lambda)
- Basic generative AI concepts (prompts, tokens, context window)

**Recommended**

- AWS Skill Builder — Generative AI Fundamentals
- Conceptual understanding of MCP (Model Context Protocol)

---

## Action Items (After the Workshop)

These are items left out of the labs because of the 4-hour limit. They continue in each Lab's Challenge Task and in `99_cleanup.md`.

| Item | Details |
|------|---------|
| External health data integration | Use AgentCore Identity **outbound** authentication to handle OAuth for Samsung Health, Apple Health, and others. This workshop covers inbound (login) only |
| Context compression | Apply Strands `SummarizingConversationManager`. Lab 4 provides the code only, and the exercise stops at caching |
| Build Gateway and Cognito yourself | Create the pre-provisioned resources yourself. Fine-grained authorization with Cedar policies |
| More evaluation axes | Safety (code-based evaluator), exercise↔meal contradiction detection, routing accuracy. Lab 7 covers only one axis, extraction accuracy |
| Production readiness | VPC private subnets + ALB, Multi-AZ, evaluations in CI/CD, long-term retention of audit logs |

---

## Get Started

[Opening: Environment Check →](./content/00_setup.md)

---

## Repository Structure

```
├── README.md                  Curriculum (single source for time allocation)
├── content/                   9 Lab documents
├── sample-data/               5 synthetic result sheets + build and verification tools
└── infra/                     Pre-provisioned templates
```

## Disclaimer

This workshop is for technical learning. Body composition analysis results are health reference information and are not a medical
diagnosis. When you build a service that handles real user data, get a legal review and a security audit.

"InBody" is a registered trademark of InBody Co., Ltd. This repository uses the generic name "body composition analysis".
