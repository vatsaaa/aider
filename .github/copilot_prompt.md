# GitHub Copilot — Digital Equity Analyst Build Agent

## How to Use This Prompt

Paste the entire contents of this file as your first message to GitHub Copilot
Workspace (or Copilot Chat in agent mode). Then in every subsequent session,
paste the "Session Start Protocol" block at the top, followed by the specific
sub-phase you want built that session.

---

## System Context — Read Before Every Session

You are building the **Digital Equity Analyst** — an agentic pipeline that
autonomously produces institutional-grade equity research reports. The system
ingests financial data, runs a multi-stage analysis pipeline across specialised AI
agents, subjects every draft report to a three-critic GAN-style review loop,
and publishes a PDF report via git commit and SMTP email.

### Architecture in one paragraph

A **trigger layer** (SEC EDGAR poller, FRED macro watcher, earnings calendar,
price movement detector) publishes events to a **Redis Streams event bus**.
Nine agents read from and write to named streams in sequence:
RS1 (macro regime) → RS2 (sector thesis) → RS3 (company screen) →
AV1 (data collection) → AV2 (three-statement financial model) →
AV3 (DCF + peer multiple valuation) → PM1 (report draft) →
[Quant Critic + Logic Critic + Data Critic → Arbiter (revision or pass)] →
PM2 (compliance clearance) → PM3 (PDF + git + email publish).
All agent state is persisted to **PostgreSQL**. Failed messages route to a
**DLQ** stream. A **coverage monitor** daemon re-triggers the pipeline on
price moves or thesis expiry.

### Stream topology (memorise this — every agent depends on it)

```
trigger:events          → RS1, RS3
stage:rs1:output        → RS2
stage:rs2:output        → RS3
stage:rs3:output        → AV1
stage:av1:output        → AV2
stage:av2:output        → AV3
stage:av3:output        → PM1
stage:pm1:draft         → quant_critic, logic_critic, data_critic (fan-out)
critic:verdict:input    → Arbiter
critic:revision:input   → PM1 (on FATAL verdict)
critique:verdict        → PM2 (on PASS verdict)
stage:pm2:output        → PM3
stage:pm3:output        → coverage monitor / audit log
dlq:failed              → dead letter queue
```
# GitHub Copilot — Digital Equity Analyst Reference

This file is a durable reference for architecture, standards, and working
rules. It is not a phase backlog.

## System Context

The **Digital Equity Analyst** is an agentic pipeline that produces
institutional-grade equity research reports. It ingests financial and macro
data, runs a multi-stage analysis pipeline across specialised AI agents,
subjects every draft report to a three-critic review loop, and publishes a PDF
report via git commit and SMTP email.

### Architecture

A trigger layer (SEC EDGAR poller, FRED macro watcher, earnings calendar, price
movement detector) publishes events to a Redis Streams bus. The agents read and
write named streams in sequence:

```
trigger:events          → RS1, RS3
stage:rs1:output        → RS2
stage:rs2:output        → RS3
stage:rs3:output        → AV1
stage:av1:output        → AV2
stage:av2:output        → AV3
stage:av3:output        → PM1
stage:pm1:draft         → quant_critic, logic_critic, data_critic (fan-out)
critic:verdict:input    → Arbiter
critic:revision:input   → PM1 (on FATAL verdict)
critique:verdict        → PM2 (on PASS verdict)
stage:pm2:output        → PM3
stage:pm3:output        → coverage monitor / audit log
dlq:failed              → dead letter queue
```

All agent state is persisted to PostgreSQL. Failed messages route to the DLQ.
A coverage monitor daemon re-triggers the pipeline on price moves or thesis
expiry.

### Message Envelope

Every message on every stream uses the same wrapper:

```json
{
  "message_id": "<uuid4>",
  "pipeline_run_id": "<uuid4>",
  "trigger_type": "8-K | 10-Q | 10-K | earnings | fred_release | price_move | thesis_expiry | manual",
  "ticker": "AAPL",
  "timestamp": "<ISO8601>",
  "payload": { "<stage-specific content — see schemas.py>" },
  "metadata": {
    "llm_used": "ollama/gemma4:e4b | anthropic/claude-sonnet-4-20250514",
    "confidence_score": 0.87,
    "retry_count": 0
  }
}
```

## Standards

### Technology Stack

| Concern | Choice |
|---------|--------|
| Language | Python 3.12 |
| Event bus | Redis Streams (redis-py >= 5.0) |
| Database | PostgreSQL 16 (psycopg2-binary + SQLAlchemy 2.0) |
| LLM primary | Ollama — gemma4:e4b (local, zero cost) |
| LLM fallback | Anthropic Claude claude-sonnet-4-20250514 |
| Data — filings | sec-edgar-downloader + XML/XBRL parsing |
| Data — market | yfinance |
| Data — macro | FRED API (fredapi) |
| Scheduling | APScheduler |
| Report rendering | pandoc + xelatex → PDF |
| Templates | Jinja2 |
| Validation | Pydantic v2 |
| Containerisation | Docker Compose |
| Testing | pytest + fakeredis + pytest-mock |

### LLM Routing Rule

```
if agent is pm1_thesis:
    always use Claude
elif agent has no LLM (av1, av2, pm2):
    do not call any LLM
else:
    try Ollama first
    compute confidence score on the JSON response
    if confidence < 0.75: escalate to Claude
    log every call to llm_calls table
```

### Confidence Scoring Rule

```python
score = 1.0
score -= len(missing_required_fields) * 0.15
score -= len(null_required_fields) * 0.10
score -= 0.25 if domain_logic_check_fails else 0
score = max(0.0, min(1.0, score))
```

### Non-Negotiable Constraints

1. No secrets hardcoded. Every key, URL, and credential comes from `.env` via
   `python-dotenv`.
2. No agent imports `redis` directly. All bus access goes through `core/bus.py`.
3. No agent imports `anthropic` or `httpx` directly. All LLM access goes
   through `llm/router.py`.
4. The AV2 balance check is a hard stop. If `|Assets - Liabilities - Equity| >=
   $1000` for any projected year, raise `FatalError("model_balance_failure")`
   and route to DLQ.
5. MNPI detection is a hard stop. Any keyword match in PM2 routes immediately
   to DLQ. No PDF, no git commit, no email.
6. Every published PDF must contain the `pipeline_run_id` in the footer.
7. All tests must pass before any change is considered complete.

## Working Preferences

### Session Start Protocol

Before writing code, state:
1. Which files will be created or modified.
2. Which existing files the task depends on.
3. The acceptance criteria.
4. Ask for confirmation before proceeding.

After confirmation:
- Write complete, production-ready code.
- No stubs or placeholder TODO comments.
- Every function must have a docstring.
- Every file must have a module-level docstring.
- Use type hints throughout.
- Write the tests needed for the change.
- Validate the change before handing off.

### Handoff Block

When a task is complete, output a handoff block in this exact format:

```text
---HANDOFF---
COMPLETED: [task name]
FILES CREATED: [list]
FILES MODIFIED: [list]
TESTS WRITTEN: [list]
NEXT TASK: [task name]
DEPENDS ON: [list]
---END HANDOFF---
```

## Open Work

Keep this section for work that is still genuinely pending. Do not add completed
phase plans back into this file.

- Keep prompt templates, schemas, and routing config synchronized as the codebase
  evolves.
- Add regression tests whenever behavior changes in the pipeline or watchdogs.
- Update coverage universe, valuation assumptions, and prompt assets as market
  conventions or policy changes.
- Record new build work here only if it is not already captured by the codebase or task tracker.
alembic>=1.13
