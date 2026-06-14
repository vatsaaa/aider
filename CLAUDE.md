# Digital Equity Analyst — System Architecture and Constraints

## System Context
The **Digital Equity Analyst** is an agentic pipeline that produces institutional-grade equity research reports. It ingests financial and macro data, runs a multi-stage analysis pipeline across specialised AI agents, subjects every draft report to a three-critic review loop, and publishes a PDF report via git commit and SMTP email.

### Architecture Topology
A trigger layer (SEC EDGAR poller, FRED macro watcher, earnings calendar, price movement detector) publishes events to a Redis Streams bus. The agents read and write named streams in sequence:

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

All agent state is persisted to PostgreSQL. Failed messages route to the DLQ. A coverage monitor daemon re-triggers the pipeline on price moves or thesis expiry.

### Message Envelope Schema
Every message on every stream uses the same wrapper:
{
  "message_id": "<uuid4>",
  "pipeline_run_id": "<uuid4>",
  "trigger_type": "8-K | 10-Q | 10-K | earnings | fred_release | price_move | thesis_expiry | manual",
  "ticker": "AAPL",
  "timestamp": "<ISO8601>",
  "payload": { "<stage-specific content>" },
  "metadata": {
    "llm_used": "ollama/gemma4:e4b | anthropic/claude-sonnet-4-20250514",
    "confidence_score": 0.87,
    "retry_count": 0
  }
}

## Build Standards

### Technology Stack
* Language: Python 3.12
* Event bus: Redis Streams (redis-py >= 5.0)
* Database: PostgreSQL 16 (psycopg2-binary + SQLAlchemy 2.0)
* LLM primary: Ollama — gemma4:e4b (local, zero cost)
* LLM fallback: Anthropic Claude claude-sonnet-4-20250514
* Data (filings): sec-edgar-downloader + XML/XBRL parsing
* Data (market): yfinance
* Data (macro): FRED API (fredapi)
* Scheduling: APScheduler
* Report rendering: pandoc + xelatex → PDF
* Validation: Pydantic v2
* Testing: pytest + fakeredis + pytest-mock

### LLM Routing Rule
if agent is pm1_thesis:
    always use Claude
elif agent has no LLM (av1, av2, pm2):
    do not call any LLM
else:
    try Ollama first
    compute confidence score on the JSON response
    if confidence < 0.75: escalate to Claude
    log every call to llm_calls table

### Non-Negotiable Constraints
1. No secrets hardcoded. Every key, URL, and credential comes from `.env` via `python-dotenv`.
2. No agent imports `redis` directly. All bus access goes through `core/bus.py`.
3. No agent imports `anthropic` or `httpx` directly. All LLM access goes through `llm/router.py`.
4. The AV2 balance check is a hard stop. If `|Assets - Liabilities - Equity| >= $1000` for any projected year, raise `FatalError("model_balance_failure")` and route to DLQ.
5. MNPI detection is a hard stop. Any keyword match in PM2 routes immediately to DLQ. No PDF, no git commit, no email.
6. Every published PDF must contain the `pipeline_run_id` in the footer.
7. All tests must pass before any change is considered complete.

### Code Execution Rules
* Write complete, production-ready code. No stubs or placeholder TODO comments.
* Every function must have a docstring.
* Every file must have a module-level docstring.
* Use type hints throughout.
* Write the tests needed for the change and validate them via `pytest` before completing a task.