-- Schema for Digital Equity Analyst
-- Extension for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Stores every pipeline run end-to-end
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker          TEXT NOT NULL,
    trigger_type    TEXT NOT NULL,
    status          TEXT NOT NULL,
    started_at      TIMESTAMPTZ DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    git_commit_hash TEXT
);

-- Persists the AV1 data package (SEC filings, financials)
CREATE TABLE IF NOT EXISTS data_packages (
    data_package_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID REFERENCES pipeline_runs,
    ticker          TEXT NOT NULL,
    fetched_at      TIMESTAMPTZ DEFAULT now(),
    payload         JSONB NOT NULL,
    auditor_flags   JSONB DEFAULT '[]'
);

-- Persists the AV2 financial model outputs
CREATE TABLE IF NOT EXISTS financial_models (
    model_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID REFERENCES pipeline_runs,
    ticker          TEXT NOT NULL,
    built_at        TIMESTAMPTZ DEFAULT now(),
    wacc            NUMERIC,
    scenarios       JSONB NOT NULL,
    balance_ok      BOOLEAN NOT NULL,
    payload         JSONB NOT NULL,
    sensitivity_table JSONB
);

ALTER TABLE financial_models ADD COLUMN IF NOT EXISTS sensitivity_table JSONB;

-- Persists every draft and final report
CREATE TABLE IF NOT EXISTS reports (
    report_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID REFERENCES pipeline_runs,
    model_id        UUID REFERENCES financial_models,
    ticker          TEXT NOT NULL,
    iteration       INTEGER NOT NULL DEFAULT 1,
    status          TEXT NOT NULL,
    draft_md        TEXT,
    final_md        TEXT,
    pdf_path        TEXT,
    artifact_uri    TEXT,
    rating          TEXT,
    target_price    NUMERIC,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Persists macro regime classifications from RS1
CREATE TABLE IF NOT EXISTS macro_regime (
    id                  SERIAL PRIMARY KEY,
    regime              TEXT NOT NULL,
    confidence          NUMERIC NOT NULL,
    sector_overweights   JSONB NOT NULL DEFAULT '[]',
    sector_underweights  JSONB NOT NULL DEFAULT '[]',
    reasoning           TEXT,
    classified_at       TIMESTAMPTZ DEFAULT now()
);

-- Audit log for every critic verdict and compliance decision
CREATE TABLE IF NOT EXISTS audit_log (
    id              SERIAL PRIMARY KEY,
    run_id          UUID REFERENCES pipeline_runs,
    stage           TEXT NOT NULL,
    verdict         TEXT,
    issues          JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- DLQ entries
CREATE TABLE IF NOT EXISTS dlq_entries (
    id              SERIAL PRIMARY KEY,
    run_id          UUID,
    stream          TEXT NOT NULL,
    message_id      TEXT,
    reason          TEXT,
    payload         JSONB,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Track retries attempted by the orchestrator for DLQ entries
CREATE TABLE IF NOT EXISTS dlq_retries (
    id              SERIAL PRIMARY KEY,
    dlq_entry_id    TEXT NOT NULL,
    retried_at      TIMESTAMPTZ DEFAULT now()
);

-- Record alert send failures after retries exhausted
CREATE TABLE IF NOT EXISTS alerts_failures (
    id              SERIAL PRIMARY KEY,
    channel         TEXT NOT NULL,
    payload         JSONB,
    error_message   TEXT,
    failed_at       TIMESTAMPTZ DEFAULT now()
);

-- LLM calls logging (includes cost tracking used by daily_claude_spend)
CREATE TABLE IF NOT EXISTS llm_calls (
    id              SERIAL PRIMARY KEY,
    run_id          UUID REFERENCES pipeline_runs,
    agent           TEXT NOT NULL,
    provider        TEXT NOT NULL,
    model           TEXT,
    prompt          JSONB,
    response        JSONB,
    confidence      NUMERIC,
    cost_usd        NUMERIC DEFAULT 0.0,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    created_at      TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS input_tokens INTEGER;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS output_tokens INTEGER;

-- Coverage universe: tickers under active monitoring
CREATE TABLE IF NOT EXISTS coverage_universe (
    id              SERIAL PRIMARY KEY,
    ticker          TEXT UNIQUE NOT NULL,
    added_at        TIMESTAMPTZ DEFAULT now(),
    notes           TEXT
);

-- Price snapshots used by coverage monitor
CREATE TABLE IF NOT EXISTS price_snapshots (
    id              SERIAL PRIMARY KEY,
    ticker          TEXT NOT NULL,
    price           NUMERIC NOT NULL,
    snapped_at      TIMESTAMPTZ DEFAULT now(),
    source          TEXT
);

-- Edgar triggers (unique accession number)
CREATE TABLE IF NOT EXISTS edgar_triggers (
    id                SERIAL PRIMARY KEY,
    accession_number  TEXT NOT NULL,
    run_id            UUID REFERENCES pipeline_runs,
    ticker            TEXT,
    form_type         TEXT,
    fiscal_year       INTEGER,
    fiscal_period     TEXT,
    filed_at          TIMESTAMPTZ,
    fetched_at        TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_edgar_triggers_fiscal_period
    ON edgar_triggers (ticker, form_type, fiscal_year, fiscal_period)
    WHERE fiscal_year IS NOT NULL AND fiscal_period IS NOT NULL;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_price_snapshots_ticker_snapped_at ON price_snapshots (ticker, snapped_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_ticker_status ON pipeline_runs (ticker, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_edgar_triggers_accession_number ON edgar_triggers (accession_number);

-- daily_claude_spend view: total Claude spend per day
CREATE OR REPLACE VIEW daily_claude_spend AS
SELECT date_trunc('day', created_at) AS day, COALESCE(SUM(cost_usd), 0.0) AS total_spend
FROM llm_calls
WHERE provider ILIKE 'anthropic' || '%'
GROUP BY day
ORDER BY day DESC;
