# The Digital Analyst: Agentic AI for Autonomous Equity Research

## Architecture Specification — US Equities, Zero Human Intervention

---

> **Scope:** US equity markets (NYSE/NASDAQ). Fully autonomous. Free data sources only. Open-source LLMs primary, Claude API as quality fallback. Event-driven and scheduled triggers. Every stage is an isolated agent with a strict JSON I/O contract.

---

## 1. Architecture Overview

The system is a **multi-agent autonomous pipeline** where each agent is a self-contained process that:
1. Reads from a named Redis Stream (its input channel)
2. Executes its task using tools, data APIs, and LLMs
3. Publishes a structured JSON payload to the next stream (its output channel)
4. Updates pipeline state in PostgreSQL

No agent knows what came before it beyond its declared input schema. No agent knows what comes after. The orchestrator manages routing, retries, and error recovery.

```mermaid
flowchart TD
    subgraph TRIGGERS["🔔 TRIGGER LAYER"]
        T1["⏰ APScheduler\nWeekly macro · Post-earnings · Quarterly refresh"]
        T2["📄 EDGAR RSS Monitor\n8-K · 10-Q · 10-K filed for tracked stocks"]
        T3["📈 Price Alert Monitor\nIntraday moves >5% on coverage universe"]
    end

    subgraph BUS["📨 REDIS STREAMS — Message Bus"]
        S0["trigger.events"]
        S1["macro.signal"]
        S2["sector.thesis"]
        S3["company.shortlist"]
        S4["data.package"]
        S5["financial.model"]
        S6["valuation.output"]
        S7["report.draft"]
        S8["report.reviewed"]
    end

    subgraph AGENTS["🤖 AGENT PIPELINE"]
        A1["Stage 1\nMacroSignalAgent"]
        A2["Stage 2\nSectorThesisAgent"]
        A3["Stage 3\nScreenerAgent"]
        A4["Stage 4\nDataCollectionAgent"]
        A5["Stage 5\nFinancialModelingAgent"]
        A6["Stage 6\nValuationAgent"]
        A7["Stage 7\nThesisWriterAgent"]
        A8["Stage 8\nQualityReviewAgent"]
        A9["Stage 9\nPublisherAgent"]
    end

    subgraph INFRA["🏗 INFRASTRUCTURE"]
        DB[("PostgreSQL\nPipeline state · Reports · Coverage")]
        CACHE[("Redis\nMessage broker · Ephemeral cache")]
        FILES[("MinIO / S3\nReport PDFs · Charts")]
        LLM["LLM Backend\nOllama → Claude API fallback"]
    end

    T1 & T2 & T3 --> S0

    S0 --> A1
    A1 --> S1 --> A2
    A2 --> S2 --> A3
    A3 --> S3 --> A4
    T2 --> A4
    A4 --> S4 --> A5
    A5 --> S5 --> A6
    A6 --> S6 --> A7
    A7 --> S7 --> A8
    A8 --> S8 --> A9
    A8 -->|"quality_score < 0.70 → retry"| A7

    A1 & A2 & A3 & A4 & A5 & A6 & A7 & A8 & A9 --> DB
    A7 & A9 --> FILES
    A1 & A2 & A4 & A7 & A8 --> LLM
```

---

## 2. Design Principles

**Strict stage isolation.** Each agent is independently deployable, independently restartable, and independently testable. A failure in Stage 6 does not corrupt data in Stages 1–5.

**Idempotent operations.** Every agent can be re-run with the same input and produce the same output. Duplicate trigger events do not generate duplicate reports — the orchestrator deduplicates by (ticker, trigger_type, fiscal_period).

**Two trigger flows, one pipeline.** A full scheduled run starts at Stage 1. An event-driven run (new SEC filing for a tracked stock) enters at Stage 4 and runs through to Stage 9. The pipeline handles both without modification.

**LLM as reasoner, not calculator.** All numerical work (DCF, ratio calculations, model balancing) runs in Python. LLMs are used exclusively for: regime classification, written narrative generation, document data extraction, and quality review. This prevents hallucinated numbers from entering the financial model.

**Fail loudly, recover gracefully.** Every agent emits structured error events. The orchestrator applies exponential backoff retry logic. After 3 failures, the run is marked FAILED and a human-readable error report is published to the distribution channel.

---

## 3. The Two Pipeline Flows

### Flow A — Full Scheduled Run (Weekly)
Triggers every Monday 06:00 ET, plus after each FOMC meeting and major economic release (CPI, NFP, PCE).

```
Trigger → Stage 1 → Stage 2 → Stage 3 → Stage 4 → Stage 5 → Stage 6 → Stage 7 → Stage 8 → Stage 9
```

Output: Fresh research reports for the 3–5 highest-conviction stocks identified by the screener.

### Flow B — Incremental Event Run (EDGAR Filing or Price Alert)
Triggers when SEC EDGAR RSS emits a new 8-K, 10-Q, or 10-K for a stock already in the coverage universe. Also triggers on price moves > 5% intraday.

```
Trigger → Stage 4 (re-collect) → Stage 5 (re-model) → Stage 6 (re-value) → Stage 7 (update) → Stage 8 → Stage 9
```

Output: Updated research note for the specific stock. The Publisher marks it as an "Earnings Update" or "Event-Driven Update" rather than a fresh initiation.

---

## 4. Agent Specifications

Each specification includes: trigger conditions, input contract, core logic, tools, LLM usage, output contract, and failure handling.

---

### Stage 1 — MacroSignalAgent

**Purpose:** Read the US macroeconomic environment and classify the current interest rate regime.

**Trigger:** Scheduled (Monday 06:00 ET, post-FOMC, post-CPI/NFP/PCE releases). Calendar of scheduled releases is maintained in the database and checked by APScheduler.

**Input Contract:**
```json
{
  "trigger_id": "sched_20240115_0600",
  "trigger_type": "SCHEDULED | FOMC | CPI_RELEASE | NFP_RELEASE",
  "timestamp": "2024-01-15T06:00:00Z"
}
```

**Core Logic:**
1. Fetch from FRED API: `FEDFUNDS` (Fed Funds Rate), `T10Y2Y` (10Y–2Y yield spread), `CPIAUCSL` (CPI YoY), `UNRATE` (unemployment), `PCE` (PCE index), `INDPRO` (industrial production).
2. Fetch current Treasury yields: `DGS10`, `DGS2`, `DGS3MO` from FRED.
3. Classify regime using LLM (Llama 3.1 8B — simple classification task): input is the data points, output is one of four states with confidence score.
4. Apply rule-based sector rotation matrix to regime (see `sector_rotation_matrix.json` in config).
5. Identify upcoming macro catalyst events from FRED release calendar.

**Tools:** `fredapi` Python library, `pandas`, LLM (Ollama Llama 3.1 8B).

**LLM Prompt Strategy:**
```
System: You are a macroeconomic analyst. Classify the current regime as one of:
LATE_CYCLE_PEAK | RATE_HIKING | RATE_EASING | EARLY_CYCLE_RECOVERY.
Return JSON only: {"regime": "...", "confidence": 0.0-1.0, "reasoning": "2 sentences max"}.

User: [Fed Funds Rate, yield curve shape, CPI, unemployment numbers injected here]
```

**Output Contract:**
```json
{
  "signal_id": "macro_20240115_001",
  "timestamp": "2024-01-15T06:00:00Z",
  "regime": "LATE_CYCLE_PEAK",
  "regime_confidence": 0.83,
  "regime_reasoning": "Fed Funds at 5.25%, yield curve inverted 30bps, CPI at 3.4% still above target.",
  "macro_data": {
    "fed_funds_rate": 5.25,
    "yield_10y": 4.80,
    "yield_2y": 5.10,
    "yield_spread_10y2y": -0.30,
    "cpi_yoy_pct": 3.4,
    "unemployment_pct": 3.7,
    "industrial_production_mom": -0.1
  },
  "sector_bias": {
    "XLF": "OVERWEIGHT",
    "XLK": "UNDERWEIGHT",
    "XLV": "OVERWEIGHT",
    "XLP": "OVERWEIGHT",
    "XLE": "NEUTRAL",
    "XLI": "UNDERWEIGHT",
    "XLRE": "UNDERWEIGHT",
    "XLU": "NEUTRAL"
  },
  "upcoming_catalysts": [
    {"event": "FOMC_MEETING", "date": "2024-01-31"},
    {"event": "CPI_RELEASE", "date": "2024-02-13"}
  ]
}
```

**Failure Handling:** FRED API outage → retry 3× with exponential backoff. If FRED unavailable after 3 retries, fetch from `Treasury.gov` direct API as fallback. Never use stale data older than 7 days.

---

### Stage 2 — SectorThesisAgent

**Purpose:** Translate the macro call into a specific sector direction with quantified evidence.

**Trigger:** New `macro.signal` message in Redis Stream.

**Input Contract:** MacroSignal JSON from Stage 1.

**Core Logic:**
1. Take the top 2 OVERWEIGHT sectors from `sector_bias`.
2. Fetch 90-day price performance of sector ETFs (XLF, XLV, etc.) via `yfinance`.
3. Calculate sector momentum vs SPY: relative strength over 20-day, 50-day, 90-day windows.
4. Fetch recent sector-level news via Yahoo Finance RSS (`https://finance.yahoo.com/rss/headline?s={etf_ticker}`).
5. Classify thesis type: STRUCTURAL (regulatory, demographic, technology) vs CYCLICAL (commodity, credit, inventory).
6. LLM (Llama 3.1 70B) generates written sector thesis memo per sector.

**Tools:** `yfinance`, `feedparser` (RSS), `pandas`, LLM (Ollama Llama 3.1 70B).

**LLM Prompt Strategy:**
```
System: You are a sector research analyst. Write a concise sector thesis (200 words max) that:
1. States why this sector benefits from the current macro regime.
2. Identifies whether the opportunity is structural or cyclical.
3. Names the specific catalyst that will drive outperformance in the next 12 months.
Return JSON: {"thesis": "...", "type": "STRUCTURAL|CYCLICAL", "primary_catalyst": "..."}

User: [Macro regime, sector ETF momentum data, recent news headlines injected]
```

**Output Contract:**
```json
{
  "thesis_id": "sector_20240115_001",
  "macro_signal_id": "macro_20240115_001",
  "timestamp": "2024-01-15T06:00:00Z",
  "priority_sectors": [
    {
      "sector_name": "Healthcare",
      "etf_ticker": "XLV",
      "bias": "OVERWEIGHT",
      "thesis_type": "STRUCTURAL",
      "momentum_vs_spy_90d": 0.034,
      "thesis": "Aging US demographics and the GLP-1 drug adoption cycle create durable earnings tailwinds...",
      "primary_catalyst": "GLP-1 market expansion reaching Medicare coverage in 2024",
      "sic_codes_to_screen": ["2836", "8011", "6324"],
      "market_cap_floor_bn": 2.0
    }
  ]
}
```

**Failure Handling:** If yfinance rate-limits, wait 60 seconds and retry once. If LLM produces non-JSON output, extract with regex and retry with stricter prompt.

---

### Stage 3 — ScreenerAgent

**Purpose:** Find the 3–5 most mispriced candidate stocks in the priority sectors.

**Trigger:** New `sector.thesis` message in Redis Stream.

**Input Contract:** SectorThesis JSON from Stage 2.

**Core Logic:**
1. Build initial universe: query SEC EDGAR company search API by SIC code to get all listed companies in the sector. Typically 100–400 companies.
2. Fetch basic financials for all universe companies via `yfinance` (market cap, P/E, EV/EBITDA, revenue, debt/equity).
3. Apply hard filters:
   - Market cap ≥ floor set in SectorThesis (default $2B)
   - Revenue growth (TTM) > −5%
   - Net Debt/EBITDA ≤ 4.0×
   - Data available (yfinance has at least 3 years of history)
4. Score remaining companies: valuation discount vs sector median, momentum divergence, analyst estimate revision direction.
5. LLM (Llama 3.1 70B) reviews top 10 scored companies and selects final 3–5 with preliminary mispricing hypothesis for each.
6. Check coverage universe in PostgreSQL — skip stocks with a report generated in the last 30 days (unless event-triggered).

**Tools:** `yfinance`, `requests` (EDGAR company search API), `pandas`, LLM (Ollama Llama 3.1 70B).

**EDGAR Company Search API (free):**
```
GET https://efts.sec.gov/LATEST/search-index?q=%22{sic_code}%22&dateRange=custom&startdt=2020-01-01&forms=10-K
GET https://data.sec.gov/submissions/CIK{cik_padded}.json
```

**Output Contract:**
```json
{
  "shortlist_id": "screen_20240115_001",
  "sector_thesis_id": "sector_20240115_001",
  "timestamp": "2024-01-15T06:00:00Z",
  "candidates": [
    {
      "ticker": "UNH",
      "cik": "0000072971",
      "company_name": "UnitedHealth Group Inc.",
      "sector": "Healthcare",
      "sub_sector": "Managed Care",
      "market_cap_bn": 450.2,
      "current_price": 524.30,
      "pe_ttm": 22.4,
      "sector_median_pe": 19.8,
      "ev_ebitda_ntm": 13.2,
      "net_debt_ebitda": 0.8,
      "revenue_growth_yoy_pct": 14.6,
      "preliminary_thesis": "Market is overweighting short-term GLP-1 cost headwinds while underpricing Optum Health's durable 15%+ EBIT growth trajectory.",
      "mispricing_direction": "UNDERVALUED",
      "priority_rank": 1
    }
  ]
}
```

**Failure Handling:** EDGAR API unavailable → use yfinance sector classification as fallback universe. yfinance rate limit → distribute requests with 2-second delay between tickers.

---

### Stage 4 — DataCollectionAgent

**Purpose:** Build the complete data package for each candidate company from primary sources.

**Triggers:**
- New `company.shortlist` message (Flow A — full run)
- New EDGAR RSS event for a tracked ticker (Flow B — event run): `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K&dateb=&owner=include&count=10&search_text=&output=atom`

**Input Contract (Full Run):**
```json
{
  "shortlist_id": "screen_20240115_001",
  "candidates": [{"ticker": "UNH", "cik": "0000072971", ...}]
}
```

**Input Contract (Event Run):**
```json
{
  "trigger_type": "EDGAR_FILING",
  "ticker": "UNH",
  "cik": "0000072971",
  "filing_type": "10-Q",
  "filing_url": "https://www.sec.gov/Archives/edgar/data/...",
  "filed_date": "2024-01-15"
}
```

**Core Logic (per ticker):**
1. **SEC Filings:** Fetch last 3× 10-K and last 8× 10-Q from EDGAR. Use `python-edgar` or direct EDGAR API:
   ```
   GET https://data.sec.gov/submissions/CIK{cik}.json → get filing list
   GET https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json → structured XBRL financial data
   ```
2. **XBRL Data (key insight):** SEC requires XBRL filings since 2009. `data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` returns fully structured income statement, balance sheet, and cash flow data — no parsing required. This is the cleanest free financial data available anywhere.
3. **Price History:** 5-year daily OHLCV from `yfinance`.
4. **Earnings Estimates:** Analyst consensus from `yfinance` (`Ticker.get_earnings_estimate()`).
5. **News Feed:** Last 90 days from Yahoo Finance RSS per ticker.
6. **Recent 8-K Earnings Releases:** Fetch and parse text of the earnings press release. LLM extracts management guidance statements.
7. **Peer Universe:** Fetch CIK list for same SIC code from EDGAR; used in Stage 6.
8. **Data Quality Check:** Score completeness (0–1.0). Flag if < 0.75.

**Tools:** `requests`, `yfinance`, `feedparser`, `sec-api` (free tier), `pandas`, LLM (Llama 3.1 70B for 8-K text extraction).

**LLM Task — Guidance Extraction:**
```
System: Extract management guidance from this earnings press release.
Return JSON: {
  "revenue_guidance_low": number | null,
  "revenue_guidance_high": number | null,
  "eps_guidance_low": number | null,
  "eps_guidance_high": number | null,
  "qualitative_statements": ["...", "..."],
  "fiscal_year": "FY2024"
}
User: [8-K earnings release text]
```

**Output Contract (one per ticker):**
```json
{
  "package_id": "data_UNH_20240115_001",
  "ticker": "UNH",
  "cik": "0000072971",
  "collection_timestamp": "2024-01-15T07:30:00Z",
  "xbrl_facts": {
    "revenue_annual": [{"year": 2021, "value": 287597000000}, ...],
    "net_income_annual": [...],
    "total_assets_annual": [...],
    "operating_cash_flow_annual": [...],
    "capex_annual": [...],
    "revenue_quarterly": [...],
    "shares_outstanding": 951000000
  },
  "price_history": {
    "start_date": "2019-01-01",
    "end_date": "2024-01-15",
    "data_points": 1258,
    "current_price": 524.30,
    "52w_high": 556.30,
    "52w_low": 445.80,
    "beta_5y": 0.54
  },
  "consensus_estimates": {
    "revenue_fy_current": 395000000000,
    "eps_fy_current": 27.50,
    "eps_fy_next": 30.20,
    "analyst_count": 24,
    "buy_ratings": 18,
    "hold_ratings": 5,
    "sell_ratings": 1
  },
  "management_guidance": {
    "revenue_guidance_low": 400000000000,
    "revenue_guidance_high": 403000000000,
    "eps_guidance_midpoint": 27.75,
    "fiscal_year": "FY2024",
    "qualitative_statements": ["Optum continues to execute on its long-term plan..."]
  },
  "news_items": [
    {"date": "2024-01-10", "headline": "UnitedHealth raises FY2024 outlook...", "source": "Yahoo Finance"}
  ],
  "peer_ciks": ["0000078814", "0001071739"],
  "data_quality_score": 0.94,
  "filing_urls": {
    "latest_10k": "https://www.sec.gov/Archives/edgar/data/...",
    "latest_10q": "https://www.sec.gov/Archives/edgar/data/..."
  }
}
```

**Failure Handling:** XBRL API unavailable → fall back to parsing financial tables from 10-K HTML filing using `BeautifulSoup`. If both fail, mark data_quality_score < 0.50 and skip to next candidate.

---

### Stage 5 — FinancialModelingAgent

**Purpose:** Build a linked 3-statement financial model with 5-year forward projections.

**Trigger:** New `data.package` message in Redis Stream.

**Input Contract:** DataPackage JSON from Stage 4.

**Core Logic:**
1. **Normalize historical data:** Map XBRL facts to standard model rows (Revenue, COGS, Gross Profit, SG&A, R&D, EBITDA, D&A, EBIT, Interest, EBT, Tax, Net Income; Assets, Liabilities, Equity; OCF, CapEx, FCF).
2. **Compute historical KPIs:**
   - Revenue CAGR (3-year)
   - EBITDA margins (3-year trend)
   - FCF conversion (FCF / Net Income)
   - ROIC (NOPAT / Invested Capital)
   - DSO, DIO, DPO → CCC
3. **Build projections (Base Case):**
   - Revenue: average of (a) 3-year historical CAGR, (b) management guidance midpoint, (c) sector growth from Damodaran dataset. Weighted 30/40/30.
   - EBITDA margin: trend + convergence to Damodaran sector median over 5 years.
   - D&A: % of PP&E, trend.
   - CapEx: % of revenue, using historical trend and guidance.
   - Working capital changes: driven by CCC assumption.
4. **Link statements:** Revenue → COGS → Gross Profit → EBITDA → EBIT → EBT → Net Income → Retained Earnings → Balance Sheet equity → Cash reconciliation → FCF.
5. **Balance sheet check:** Assert `assets = liabilities + equity` for each projection year. Fail loudly if not.
6. **WACC calculation:**
   - Risk-free rate: current 10Y Treasury from FRED `DGS10`
   - Equity Risk Premium: from Damodaran's `damodaran.com/New_Home_Page/datafile/implprem.html` (scraped monthly, cached)
   - Beta: 5-year monthly beta from `yfinance`
   - Cost of debt: interest expense / average total debt from XBRL
   - Capital structure weights: market cap / (market cap + book debt)
7. **LLM interprets management guidance** and adjusts revenue growth assumption if guidance is materially different from trend.

**Tools:** `pandas`, `numpy`, `yfinance` (beta), `fredapi` (risk-free rate), cached Damodaran dataset (ERP, sector margins — downloaded weekly), LLM (Ollama Llama 3.1 70B for guidance interpretation).

**Damodaran Data Access (free):**
```python
# Downloaded weekly, cached in PostgreSQL
damodaran_url = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/indname.xlsx"
erp_url = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/implprem.html"
margins_url = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/margin.xls"
```

**Output Contract:**
```json
{
  "model_id": "model_UNH_20240115_001",
  "package_id": "data_UNH_20240115_001",
  "ticker": "UNH",
  "model_timestamp": "2024-01-15T08:00:00Z",
  "historical": {
    "years": [2021, 2022, 2023],
    "revenue": [287597000000, 324162000000, 371622000000],
    "ebitda": [24200000000, 27100000000, 30800000000],
    "ebitda_margin": [0.084, 0.084, 0.083],
    "fcf": [18500000000, 20200000000, 22800000000],
    "roic": [0.145, 0.148, 0.152],
    "ccc_days": [-12, -14, -16]
  },
  "projections": {
    "years": [2024, 2025, 2026, 2027, 2028],
    "base": {
      "revenue": [399000000000, 432000000000, 468000000000, 505000000000, 541000000000],
      "revenue_growth_pct": [7.4, 8.3, 8.3, 7.9, 7.1],
      "ebitda_margin": [0.085, 0.087, 0.088, 0.089, 0.090],
      "ebitda": [33900000000, 37600000000, 41200000000, 44900000000, 48700000000],
      "fcf": [24800000000, 27600000000, 30300000000, 33200000000, 36100000000],
      "roic": [0.155, 0.158, 0.161, 0.164, 0.166]
    }
  },
  "wacc": {
    "risk_free_rate": 0.0480,
    "equity_risk_premium": 0.0452,
    "beta": 0.54,
    "cost_of_equity": 0.0724,
    "cost_of_debt_pretax": 0.0385,
    "tax_rate": 0.215,
    "debt_weight": 0.12,
    "equity_weight": 0.88,
    "wacc": 0.0675
  },
  "assumptions": {
    "revenue_growth_source": "Blend: historical CAGR (3yr: 9.1%) + guidance midpoint ($401.5B) + Damodaran sector (6.8%)",
    "margin_driver": "Optum segment mix shift toward higher-margin services; partially offset by MLR normalization",
    "capex_pct_revenue": 0.012
  },
  "model_balanced": true,
  "model_quality_score": 0.91
}
```

**Failure Handling:** If `model_balanced = false` after 3 auto-fix attempts, emit a `model.error` event and skip this ticker. Log detailed error for debugging. Continue pipeline with remaining candidates.

---

### Stage 6 — ValuationAgent

**Purpose:** Derive a 12-month target price from DCF and peer multiple valuation across three scenarios.

**Trigger:** New `financial.model` message in Redis Stream.

**Input Contract:** FinancialModel JSON from Stage 5.

**Core Logic:**
1. **DCF Calculation (Base Case):**
   - Explicit forecast: discount FCFs for years 1–5 at WACC.
   - Terminal value: `TV = FCF_5 × (1 + g) / (WACC − g)`, where `g = min(long_run_nominal_gdp, risk_free_rate − 150bps)` ≈ 3.0–3.5% for US.
   - Enterprise Value = PV of FCFs + PV of Terminal Value.
   - Equity Value = EV − Net Debt.
   - Price per share = Equity Value / Shares Outstanding.
2. **DCF Sensitivity Matrix:** Calculate price per share across a 5×5 grid of WACC (WACC−2% to WACC+2%) × terminal growth (1.5% to 4.5%).
3. **Peer Multiple Valuation:**
   - Fetch peers from `package.peer_ciks`. Get each peer's EV/EBITDA (NTM) and P/E (NTM) from `yfinance`.
   - Compute median peer multiple.
   - Apply to subject company's NTM EBITDA/EPS from Stage 5 projections.
4. **Three Scenarios:**
   - Bear: revenue −20% from base, EBITDA margin −150bps, exit multiple −1.5 turns.
   - Base: as modeled.
   - Bull: revenue +15% from base, EBITDA margin +150bps, exit multiple +1.5 turns.
5. **Weighted Target Price:** 60% DCF + 40% peer multiple.
6. **Rating Assignment:**
   - Upside > 15% → BUY
   - Upside −5% to +15% → HOLD
   - Upside < −5% → SELL

**Tools:** `numpy`, `yfinance` (peer market data), `pandas`.

**No LLM for calculations.** LLM (Llama 3.1 70B) is used only to generate 2-sentence scenario narratives for the report.

**Output Contract:**
```json
{
  "valuation_id": "val_UNH_20240115_001",
  "model_id": "model_UNH_20240115_001",
  "ticker": "UNH",
  "valuation_timestamp": "2024-01-15T08:30:00Z",
  "current_price": 524.30,
  "dcf_equity_value_per_share": 612.50,
  "peer_multiple_value_per_share": 588.20,
  "weighted_target_price_12m": 603.40,
  "upside_pct": 15.1,
  "implied_rating": "BUY",
  "dcf_breakdown": {
    "pv_explicit_fcfs": 98500000000,
    "pv_terminal_value": 482000000000,
    "enterprise_value": 580500000000,
    "net_debt": 23800000000,
    "equity_value": 556700000000,
    "shares_outstanding": 951000000,
    "terminal_growth_rate": 0.032,
    "terminal_value_pct_of_ev": 83.0
  },
  "peer_valuation": {
    "peers_used": ["CVS", "CI", "HUM", "ELV"],
    "median_ev_ebitda_ntm": 9.8,
    "applied_ev_ebitda_ntm": 9.8,
    "subject_ntm_ebitda": 35200000000,
    "implied_equity_value_per_share": 588.20
  },
  "sensitivity_matrix": {
    "wacc_range": [0.0475, 0.0575, 0.0675, 0.0775, 0.0875],
    "g_range": [0.015, 0.020, 0.030, 0.035, 0.045],
    "price_grid": [[720, 680, 640, 608, 575], [695, 655, 617, 584, 552], ...]
  },
  "scenarios": {
    "bear": {
      "target_price": 462.00,
      "upside_pct": -11.9,
      "revenue_delta_pct": -20,
      "margin_delta_bps": -150,
      "narrative": "GLP-1 drug costs accelerate Medical Loss Ratio expansion beyond management guidance; Optum faces pricing pressure from Medicare Advantage rate cuts."
    },
    "base": {
      "target_price": 603.40,
      "upside_pct": 15.1,
      "narrative": "Optum Health executes on 15% EBIT growth; UHC MLR normalizes to historical range; EPS beat of 4–5% on execution."
    },
    "bull": {
      "target_price": 712.00,
      "upside_pct": 35.8,
      "narrative": "GLP-1 headwinds prove transitory; Optum accelerates market share capture in primary care; buybacks accelerate above consensus."
    }
  }
}
```

---

### Stage 7 — ThesisWriterAgent

**Purpose:** Convert all pipeline outputs into a publication-ready research report.

**Trigger:** New `valuation.output` message in Redis Stream.

**Input Contract:** ValuationOutput ID (agent retrieves all prior stage outputs from PostgreSQL by ticker + run_id).

**Core Logic:**
1. **Retrieve full context:** Pull MacroSignal, SectorThesis, DataPackage, FinancialModel, ValuationOutput from PostgreSQL.
2. **Generate charts:**
   - Revenue + EBITDA margin trend (historical + projected) — `matplotlib`
   - FCF bridge waterfall — `matplotlib`
   - DCF sensitivity heatmap — `seaborn`
   - Peer multiple scatter — `matplotlib`
   Save as PNG to MinIO.
3. **Generate report sections via LLM:** Each section is a separate LLM call to keep context focused:
   - **Page 1 thesis:** "In 200 words, answer exactly: (1) why is the market wrong about {ticker} right now? (2) what specific catalyst closes the mispricing within 12 months? (3) what is the first piece of evidence that the repricing has begun?"
   - **Financial summary table:** Template-filled from model data (no LLM).
   - **Business model section:** "In 300 words, explain how {company} makes money, where its pricing power sits, and what prevents replication."
   - **Earnings review:** "Compare actual reported {revenue, EBITDA, EPS, FCF} to consensus estimates. Identify which beats are structural vs one-time."
   - **Risk factors:** "List exactly 4 risk factors. Each must name a specific event, quantify the earnings impact in dollar or percentage terms, and name the condition that breaks the investment thesis."
4. **Assemble Jinja2 HTML template.** Export to PDF via `WeasyPrint`.
5. **LLM selection:** Attempt Ollama Llama 3.1 70B first. If response does not parse or quality_hint_score (assessed by a separate Llama 3.1 8B call) < 0.65, fall back to Claude API (`claude-sonnet-4-6`).

**Tools:** `jinja2`, `matplotlib`, `seaborn`, `weasyprint`, LLM (Ollama Llama 3.1 70B → Claude API fallback), `boto3` / MinIO SDK.

**Output Contract:**
```json
{
  "draft_id": "draft_UNH_20240115_001",
  "valuation_id": "val_UNH_20240115_001",
  "ticker": "UNH",
  "report_type": "INITIATION | EARNINGS_UPDATE | EVENT_UPDATE",
  "draft_timestamp": "2024-01-15T09:00:00Z",
  "llm_used": "ollama_llama31_70b",
  "sections": {
    "page1_thesis": "UnitedHealth trades at a 12% discount to its intrinsic value because the market is pricing GLP-1 drug cost inflation as a permanent structural margin headwind...",
    "rating": "BUY",
    "target_price": 603.40,
    "current_price": 524.30,
    "upside_pct": 15.1,
    "business_model": "...",
    "earnings_review": "...",
    "risk_factors": [
      {"risk": "GLP-1 cost acceleration", "event": "Q2 2024 MLR > 85.5%", "earnings_impact_pct": -8},
      ...
    ]
  },
  "report_html": "<html>...",
  "report_pdf_s3_key": "reports/UNH/UNH_20240115_BUY_603.pdf",
  "chart_s3_keys": ["charts/UNH/revenue_trend.png", "charts/UNH/dcf_sensitivity.png"],
  "word_count": 3842
}
```

---

### Stage 8 — QualityReviewAgent

**Purpose:** Validate factual consistency, rating/model alignment, and writing quality before publication.

**Trigger:** New `report.draft` message in Redis Stream.

**Input Contract:** ReportDraft JSON from Stage 7.

**Core Logic:**
1. **Automated checks (rule-based, no LLM):**
   - `rating_alignment`: If upside > 15% → rating must be BUY. If upside < −5% → SELL. Assert.
   - `number_consistency`: Extract all numbers mentioned in the report text via regex. Cross-check against FinancialModel and ValuationOutput. Flag any discrepancy > 2%.
   - `risk_factors_quantified`: Assert each risk factor contains a number (%, $, bps).
   - `target_price_present`: Assert Page 1 contains an explicit 12-month price target.
2. **LLM review (Claude API — always for this step):**
   ```
   You are a senior equity research editor. Review this research report draft.
   Return JSON with: {
     "page1_answers_all_three_questions": true|false,
     "thesis_is_specific_not_generic": true|false,
     "issues": ["list of specific problems with text references"],
     "suggested_fixes": ["one-line fix per issue"],
     "overall_quality_score": 0.0-1.0
   }
   ```
3. **Auto-fix minor issues:** Swap vague risk factor language for quantified versions. Round numbers consistently. Fix "macro deterioration" → specific rate scenario.
4. **Fail conditions:** If `rating_alignment = false` OR `quality_score < 0.70` → emit `report.revision_required` event → re-trigger Stage 7 with fix instructions. Maximum 2 revision cycles before human-flag.

**Tools:** `re` (regex), LLM (Claude API — always for QA review, not Ollama).

**Why Claude API here specifically:** Quality review requires nuanced judgment about whether a thesis is specific vs generic, whether risk factors are truly quantified, and whether the writing would survive scrutiny from an institutional fund manager. This is the one task where Llama 3.1's reasoning is materially weaker than Claude.

**Output Contract:**
```json
{
  "review_id": "review_UNH_20240115_001",
  "draft_id": "draft_UNH_20240115_001",
  "ticker": "UNH",
  "review_timestamp": "2024-01-15T09:30:00Z",
  "review_passed": true,
  "automated_checks": {
    "rating_alignment": true,
    "numbers_consistent": true,
    "risk_factors_quantified": true,
    "target_price_present": true
  },
  "llm_review": {
    "page1_complete": true,
    "thesis_specific": true,
    "quality_score": 0.88,
    "issues_found": ["Risk factor 3 lacks specific trigger condition"],
    "auto_fixed": ["Risk factor 3 rewritten with Q3 earnings trigger"]
  },
  "revision_count": 0,
  "final_report_html": "<html>... (post-fix version)",
  "final_report_pdf_s3_key": "reports/UNH/UNH_20240115_BUY_603_FINAL.pdf"
}
```

---

### Stage 9 — PublisherAgent

**Purpose:** Distribute the final report, update the coverage database, and set up ongoing monitoring.

**Trigger:** New `report.reviewed` message where `review_passed = true`.

**Input Contract:** ReviewedReport JSON from Stage 8.

**Core Logic:**
1. **Store report:** Copy final PDF to MinIO with versioned key. Insert report metadata into PostgreSQL `reports` table.
2. **Update coverage universe:** Insert/update row in `coverage` table: ticker, current_rating, target_price, last_report_date, last_report_pdf_key.
3. **Email distribution:**
   - Use Python `smtplib` with Gmail SMTP (free) or AWS SES free tier (62K emails/month from EC2).
   - Send plain-text summary + PDF attachment to subscriber list.
   - Format: "NEW RESEARCH: UNH — BUY, $603 Target (+15.1% upside) | [View PDF]"
4. **Update web dashboard:** Write report metadata to `reports` table; the FastAPI dashboard polls this.
5. **Set up event monitoring for this ticker:**
   - Add ticker's CIK to the EDGAR RSS watchlist (the Trigger Layer's EDGAR Monitor now watches for new 8-K/10-Q/10-K filings).
   - Set a PostgreSQL alert row: if `price_move_pct > 5%` in `price_alerts` table, trigger Flow B re-analysis.
6. **Log performance tracking:** Record `{ticker, report_date, rating, target_price_at_report, current_price_at_report}`. A daily cron job updates `current_price` to track accuracy over time.

**Tools:** `smtplib`, `boto3` / MinIO SDK, `psycopg2`, FastAPI (web dashboard).

**Output Contract:**
```json
{
  "publication_id": "pub_UNH_20240115_001",
  "review_id": "review_UNH_20240115_001",
  "ticker": "UNH",
  "published_timestamp": "2024-01-15T10:00:00Z",
  "distribution_channels": ["email", "web_portal", "file_storage"],
  "email_sent_count": 47,
  "pdf_public_url": "https://reports.digitalanalyst.internal/UNH/UNH_20240115_BUY_603_FINAL.pdf",
  "monitoring_set": {
    "edgar_cik_watching": "0000072971",
    "price_alert_threshold_pct": 5.0,
    "next_scheduled_refresh": "2024-04-15"
  }
}
```

---

## 5. Message Bus Design

**Technology:** Redis Streams (not pub/sub — Streams provide persistence and consumer groups for exactly-once delivery).

**Stream Naming Convention:** `{domain}.{event_type}` — e.g., `macro.signal`, `data.package`.

**Consumer Group Pattern:** Each agent runs as a consumer group `{stage_name}_group`. On startup, agents use `XREADGROUP` with `>` to claim new messages and `XACK` after successful processing. Redis retains unacknowledged messages for retry.

**Message Retention:** 7 days on all streams. This allows replaying any stage from the last 7 days without re-fetching external data.

**Ordering Guarantee:** Each stream is append-only and ordered by timestamp. Stages process one message at a time per worker (configurable concurrency per stage).

---

## 6. LLM Strategy

```
┌─────────────────────────────────────────────────────────────────────┐
│ Task                          │ Model            │ Why               │
├─────────────────────────────────────────────────────────────────────┤
│ Macro regime classification   │ Llama 3.1 8B     │ Simple classify   │
│ Sector thesis generation      │ Llama 3.1 70B    │ Requires reasoning│
│ Company screening & ranking   │ Llama 3.1 70B    │ Requires reasoning│
│ SEC 8-K guidance extraction   │ Llama 3.1 70B    │ Document parsing  │
│ Revenue assumption reasoning  │ Llama 3.1 70B    │ Numerical context │
│ Scenario narrative generation │ Llama 3.1 70B    │ Writing           │
│ Full report writing           │ Llama 3.1 70B    │ Writing (primary) │
│ Report writing (fallback)     │ Claude API       │ Quality threshold │
│ Quality review (always)       │ Claude API       │ Nuanced judgment  │
└─────────────────────────────────────────────────────────────────────┘
```

**Ollama Setup:** Deploy Ollama as a Docker container. Minimum hardware: 16GB VRAM GPU (A10G on AWS, or 2× A6000 on-premise) for Llama 3.1 70B with 4-bit quantization (Q4_K_M). Alternatively: `ollama run mistral:7b` on CPU for cost-zero local testing.

**Fallback Logic (Stage 7):**
```python
async def call_llm(prompt: str, task: str) -> str:
    try:
        response = await ollama_client.generate(model="llama3.1:70b", prompt=prompt)
        quality = await quick_quality_check(response.text, task)  # Llama 3.1 8B
        if quality.score >= 0.65:
            return response.text
    except (OllamaUnavailable, TimeoutError):
        pass
    # Fallback to Claude API
    return await claude_client.messages.create(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": prompt}]
    ).content[0].text
```

---

## 7. Free Data Sources Registry

| Stage | Data Need | Source | API / Method | Rate Limit |
|---|---|---|---|---|
| 1 | Fed Funds Rate, yields, CPI | FRED API | `fredapi` Python lib | 120 req/min |
| 1 | Economic release calendar | FRED API | `fred.get_release_dates()` | 120 req/min |
| 2 | Sector ETF prices | Yahoo Finance | `yfinance` | ~2,000/hr |
| 2 | Sector news | Yahoo Finance RSS | `feedparser` | Unlimited |
| 3 | Company universe by SIC | SEC EDGAR | `data.sec.gov/submissions/` | 10 req/sec |
| 3 | Preliminary financials | Yahoo Finance | `yfinance` | ~2,000/hr |
| 4 | Full SEC filings list | SEC EDGAR | `data.sec.gov/submissions/CIK{}.json` | 10 req/sec |
| 4 | XBRL financial facts | SEC EDGAR | `data.sec.gov/api/xbrl/companyfacts/` | 10 req/sec |
| 4 | Price history, estimates | Yahoo Finance | `yfinance` | ~2,000/hr |
| 4 | Filing text (8-K, 10-K) | SEC EDGAR | Direct HTTPS fetch | 10 req/sec |
| 5 | Industry betas, ERP | Damodaran | HTTPS download (cached weekly) | No limit |
| 5 | Industry margins, multiples | Damodaran | HTTPS download (cached weekly) | No limit |
| 5 | Beta | Yahoo Finance | `yfinance` | ~2,000/hr |
| 6 | Peer market data | Yahoo Finance | `yfinance` | ~2,000/hr |
| All | EDGAR filing alerts | SEC EDGAR RSS | `feedparser` | No limit |

**EDGAR User-Agent Requirement:** SEC requires a valid `User-Agent` header on all EDGAR API requests: `User-Agent: DigitalAnalyst research@yourdomain.com`. Failure to include this results in IP blocks.

---

## 8. Technology Stack

```
Language:         Python 3.11+
Agent Framework:  LangGraph 0.2+ (state machine orchestration)
LLM Primary:      Ollama + Llama 3.1 70B (4-bit quantized)
LLM Fallback:     Anthropic Claude API (claude-sonnet-4-6)
Message Bus:      Redis 7+ (Streams)
Database:         PostgreSQL 15+
Object Storage:   MinIO (self-hosted S3-compatible)
Scheduler:        APScheduler 3.10+
Web Framework:    FastAPI 0.110+
Report PDF:       WeasyPrint 60+
Charts:           Matplotlib 3.8+, Seaborn 0.13+
Templates:        Jinja2 3.1+
Data:             pandas 2.0+, numpy 1.26+
HTTP:             httpx (async), requests
RSS:              feedparser 6.0+
SEC Data:         sec-api (free tier), direct EDGAR API
Finance:          yfinance 0.2+
Fed Data:         fredapi 3.1+
Email:            smtplib (stdlib) or boto3 (SES)
Containers:       Docker 24+, Docker Compose 2.24+
```

---

## 9. Project Directory Structure

```
digital-analyst/
│
├── agents/                         # One module per pipeline stage
│   ├── base.py                     # BaseAgent class with Redis Streams I/O
│   ├── stage1_macro.py             # MacroSignalAgent
│   ├── stage2_sector.py            # SectorThesisAgent
│   ├── stage3_screener.py          # ScreenerAgent
│   ├── stage4_data.py              # DataCollectionAgent
│   ├── stage5_modeling.py          # FinancialModelingAgent
│   ├── stage6_valuation.py         # ValuationAgent
│   ├── stage7_writer.py            # ThesisWriterAgent
│   ├── stage8_review.py            # QualityReviewAgent
│   └── stage9_publisher.py         # PublisherAgent
│
├── orchestrator/
│   ├── pipeline.py                 # LangGraph pipeline definition
│   ├── scheduler.py                # APScheduler jobs (Full Run, Event Check)
│   ├── edgar_monitor.py            # EDGAR RSS feed watcher
│   └── price_monitor.py            # Intraday price alert monitor
│
├── llm/
│   ├── client.py                   # Unified LLM client (Ollama + Claude fallback)
│   ├── prompts/                    # Prompt templates per task
│   │   ├── macro_classify.txt
│   │   ├── sector_thesis.txt
│   │   ├── guidance_extract.txt
│   │   ├── report_page1.txt
│   │   ├── report_risks.txt
│   │   └── quality_review.txt
│   └── quality_check.py            # Quick quality scorer (Llama 3.1 8B)
│
├── data/
│   ├── edgar.py                    # EDGAR API wrapper (submissions, XBRL facts)
│   ├── yfinance_client.py          # yfinance wrapper with rate limiting
│   ├── fred_client.py              # FRED API wrapper
│   ├── damodaran.py                # Damodaran dataset downloader / cache
│   └── rss_reader.py               # Generic RSS feed reader
│
├── models/
│   ├── schemas.py                  # Pydantic models for all I/O contracts
│   ├── financial_model.py          # 3-statement model logic (pure Python/pandas)
│   ├── dcf.py                      # DCF and sensitivity calculation
│   └── valuation.py                # Peer multiple valuation
│
├── reporting/
│   ├── chart_generator.py          # All matplotlib chart generation
│   ├── templates/
│   │   ├── report_full.html        # Jinja2 HTML template
│   │   └── report_update.html      # Shorter template for update notes
│   └── pdf_renderer.py             # WeasyPrint PDF generation
│
├── storage/
│   ├── postgres.py                 # DB connection and query helpers
│   ├── minio_client.py             # Object storage for reports/charts
│   └── migrations/                 # SQL migration files
│       ├── 001_create_tables.sql
│       └── 002_coverage_universe.sql
│
├── api/
│   ├── main.py                     # FastAPI application
│   ├── routes/
│   │   ├── reports.py              # GET /reports, GET /reports/{id}
│   │   ├── coverage.py             # GET /coverage (current ratings)
│   │   └── pipeline.py             # GET /pipeline/status, POST /pipeline/trigger
│   └── templates/
│       └── dashboard.html          # Simple HTML dashboard
│
├── config/
│   ├── settings.py                 # Pydantic settings (env-based)
│   ├── sector_rotation_matrix.json # Regime → sector bias mapping
│   └── coverage_universe.json      # Initial seed list of tickers to cover
│
├── tests/
│   ├── unit/                       # Per-agent unit tests
│   ├── integration/                # End-to-end pipeline tests with fixtures
│   └── fixtures/                   # Cached EDGAR/yfinance responses for testing
│
├── docker-compose.yml
├── Dockerfile.agents
├── Dockerfile.ollama
├── requirements.txt
└── README.md
```

---

## 10. Deployment (Docker Compose)

```yaml
version: "3.9"

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: digital_analyst
      POSTGRES_USER: analyst
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./storage/migrations:/docker-entrypoint-initdb.d

  redis:
    image: redis:7-alpine
    command: redis-server --save 60 1 --loglevel warning
    volumes:
      - redis_data:/data

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_PASSWORD}
    volumes:
      - minio_data:/data
    ports:
      - "9000:9000"   # S3 API
      - "9001:9001"   # Console

  ollama:
    image: ollama/ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    volumes:
      - ollama_models:/root/.ollama
    # Post-start: docker exec ollama ollama pull llama3.1:70b-instruct-q4_K_M

  orchestrator:
    build:
      context: .
      dockerfile: Dockerfile.agents
    command: python -m orchestrator.scheduler
    depends_on: [postgres, redis, ollama]
    environment:
      POSTGRES_DSN: postgresql://analyst:${POSTGRES_PASSWORD}@postgres/digital_analyst
      REDIS_URL: redis://redis:6379
      OLLAMA_URL: http://ollama:11434
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      FRED_API_KEY: ${FRED_API_KEY}
      MINIO_ENDPOINT: minio:9000

  edgar_monitor:
    build:
      context: .
      dockerfile: Dockerfile.agents
    command: python -m orchestrator.edgar_monitor
    depends_on: [postgres, redis]

  # One container per agent — scale independently
  agent_macro:
    build: { context: ., dockerfile: Dockerfile.agents }
    command: python -m agents.stage1_macro --worker
    depends_on: [postgres, redis, ollama]

  agent_sector:
    build: { context: ., dockerfile: Dockerfile.agents }
    command: python -m agents.stage2_sector --worker
    depends_on: [postgres, redis, ollama]

  # ... agents 3–9 follow same pattern ...

  api:
    build: { context: ., dockerfile: Dockerfile.agents }
    command: uvicorn api.main:app --host 0.0.0.0 --port 8080
    ports:
      - "8080:8080"
    depends_on: [postgres, minio]

volumes:
  postgres_data:
  redis_data:
  minio_data:
  ollama_models:
```

**Environment Variables (.env):**
```
POSTGRES_PASSWORD=...
MINIO_USER=...
MINIO_PASSWORD=...
ANTHROPIC_API_KEY=...      # Used only by Stage 8 QA, Stage 7 fallback
FRED_API_KEY=...           # Free at fred.stlouisfed.org/api
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=youraddr@gmail.com
SMTP_PASSWORD=...          # App password (not account password)
REPORT_SUBSCRIBERS=addr1@x.com,addr2@x.com
```

---

## 11. Database Schema (Core Tables)

```sql
-- Pipeline run tracking
CREATE TABLE pipeline_runs (
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_type    VARCHAR(50),       -- SCHEDULED, EDGAR_FILING, PRICE_ALERT
    trigger_payload JSONB,
    status          VARCHAR(30),       -- TRIGGERED, STAGE_1..9_COMPLETE, PUBLISHED, FAILED
    failed_stage    INTEGER,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    tickers_covered TEXT[]
);

-- Coverage universe (stocks the system actively monitors)
CREATE TABLE coverage_universe (
    ticker          VARCHAR(10) PRIMARY KEY,
    cik             VARCHAR(20),
    company_name    VARCHAR(200),
    sector          VARCHAR(100),
    current_rating  VARCHAR(10),       -- BUY, HOLD, SELL
    target_price    NUMERIC(10,2),
    current_price   NUMERIC(10,2),
    last_report_id  UUID,
    last_report_date DATE,
    watching_since  DATE DEFAULT CURRENT_DATE
);

-- Published reports
CREATE TABLE reports (
    report_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID REFERENCES pipeline_runs(run_id),
    ticker          VARCHAR(10),
    report_type     VARCHAR(30),       -- INITIATION, EARNINGS_UPDATE, EVENT_UPDATE
    rating          VARCHAR(10),
    target_price    NUMERIC(10,2),
    current_price   NUMERIC(10,2),
    upside_pct      NUMERIC(6,2),
    quality_score   NUMERIC(4,2),
    pdf_s3_key      VARCHAR(500),
    published_at    TIMESTAMPTZ DEFAULT NOW(),
    llm_used        VARCHAR(50)
);

-- Performance tracking
CREATE TABLE rating_performance (
    report_id       UUID REFERENCES reports(report_id),
    ticker          VARCHAR(10),
    rating          VARCHAR(10),
    target_price    NUMERIC(10,2),
    price_at_publish NUMERIC(10,2),
    price_30d       NUMERIC(10,2),
    price_90d       NUMERIC(10,2),
    price_180d      NUMERIC(10,2),
    price_365d      NUMERIC(10,2),
    hit_target      BOOLEAN,
    updated_at      TIMESTAMPTZ
);

-- Cached external data (Damodaran, FRED macro)
CREATE TABLE data_cache (
    cache_key       VARCHAR(200) PRIMARY KEY,
    data            JSONB,
    fetched_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ
);
```

---

## 12. Error Handling and Resilience

**Retry Policy (per agent):**
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=60),
    retry=retry_if_exception_type((HTTPError, TimeoutError, RedisConnectionError))
)
async def execute_with_retry(self, input_payload):
    ...
```

**Circuit Breaker (EDGAR / yfinance):**
If 5 consecutive requests to a data source fail within 60 seconds, the circuit breaker opens for 5 minutes. The agent proceeds with cached data (if available) or skips the affected tickers and logs a warning.

**Stage Idempotency Key:** Every Redis Stream message carries a `(ticker, run_id, stage)` composite key. Before processing, each agent checks PostgreSQL for an existing successful output with this key. If found, it publishes the cached output to the next stream without re-processing. This prevents re-running expensive LLM calls on duplicate messages.

**Dead Letter Queue:** Messages that fail all 3 retries are moved to `{stream}.dlq` (a separate Redis Stream). A background process inspects the DLQ daily and alerts via email.

**Model Balance Failure:** If Stage 5's 3-statement model fails to balance after 3 auto-fix attempts, the agent emits a `model.error` event with a detailed diagnostic payload. Stage 6 is skipped for this ticker. The error is logged and included in the daily operations digest.

---

## 13. Observability

**Metrics (emitted to PostgreSQL `metrics` table, visualized via Grafana or simple FastAPI endpoint):**
- Pipeline run duration by stage
- LLM call latency (Ollama vs Claude API)
- Data quality scores by ticker
- Report quality scores over time
- Rating accuracy (% of BUY recommendations that hit target within 12 months)
- EDGAR RSS lag (time from filing to pipeline trigger)

**Structured Logging (all agents):**
```python
logger.info("stage_complete", extra={
    "stage": 5,
    "ticker": "UNH",
    "run_id": run_id,
    "duration_seconds": 47.3,
    "model_quality_score": 0.91,
    "llm_calls": 2,
    "llm_tokens_used": 4820
})
```

---

## 14. Implementation Roadmap

**Phase 1 — Data Pipeline Foundation (Weeks 1–3)**
Build Stages 4, 5, 6 only. Manually trigger with a single ticker. Validate XBRL data quality, 3-statement model accuracy vs published financials, DCF output sanity check. No LLM yet — hardcode assumptions.

**Phase 2 — LLM Integration (Weeks 4–6)**
Add Ollama. Implement Stage 7 (Writer) and Stage 8 (QA) using local Llama 3.1. Tune prompts against 10 test reports. Define quality score thresholds. Add Claude API fallback.

**Phase 3 — Full Pipeline (Weeks 7–9)**
Add Stages 1, 2, 3. Wire Redis Streams. Implement the orchestrator. Run end-to-end with the scheduled trigger on 5 test tickers. Validate pipeline runs without manual intervention.

**Phase 4 — Event Triggers (Weeks 10–11)**
Add EDGAR RSS Monitor and price alert monitor. Test Flow B (incremental update). Validate that a new 10-Q filing triggers a report update within 2 hours of filing.

**Phase 5 — Distribution and Monitoring (Week 12)**
Add Stage 9 (Publisher), email distribution, MinIO storage, FastAPI dashboard. Add performance tracking. Deploy to cloud (AWS EC2 g4dn.xlarge for GPU, or on-premise with GPU server).

---

*This architecture specification is version 1.0. The system is designed for US equity markets with free data sources. The entire operational cost reduces to: (1) cloud compute for Ollama inference, (2) Claude API costs for Stage 8 QA and Stage 7 fallback (estimated $0.50–$2.00 per report at current pricing), and (3) infrastructure hosting. All data acquisition costs are zero.*




---

Summary — overall verdict

The repository already implements the architecture's core ideas (Redis Streams bus, consumer-groups, strict stage isolation via BaseAgent, Pydantic message schemas, idempotent DB writes, LLM routing with fallback, critic/arbiter + compliance + publisher). This is generally better than a pure high-level spec because it is concrete, tested, and pragmatic.
The architecture spec is stronger where it prescribes certain operational controls and explicit artifacts the codebase should have (an orchestrator that enforces run-level retries/backoff/alerts; sector-rotation matrix config; object storage for large artifacts; explicit dedupe-by-(ticker,trigger_type,fiscal_period)). These are missing or only partially implemented.
Fast comparison (high level)

What repo does better:
Practical Bus abstraction and test-friendly InMemoryBus: bus.py
Solid BaseAgent lifecycle, structured logging, audit hooks: agent_base.py
Strong Pydantic contracts for stage payloads: schemas.py
LLM router with confidence gating and ledger: router.py
Idempotent DB helpers and dedupe on trigger-watcher side (Redis keys): idempotent_writes.py, earnings_watcher.py
What the spec is stronger at (and mostly missing / partially implemented):
A central orchestrator that tracks run-level retries, applies exponential backoff, marks runs FAILED after N attempts, and publishes human-readable error reports (spec-level run orchestration).
Explicit rule files and configs referenced by spec (e.g., sector_rotation_matrix.json) and some infra choices (MinIO/S3 for PDFs) expected in spec but not present in code.
Explicit run-level dedupe by (ticker, trigger_type, fiscal_period) beyond per-watcher Redis keys.
Centralized alerting/monitoring (spec says orchestrator handles retry/alerting).
Recommended prioritized implementation plan (what to do first → next)

Implement a lightweight Orchestrator service (HIGH priority)

Why: provides the biggest reliability and product-safety improvement (explicit retries/backoff, run lifecycle, human alerts). It enforces the spec's operational guarantees and prevents silent failure loops.
What to add: a small process that monitors pipeline_runs and stream DLQ entries, tracks stage failures and retry counts, applies exponential backoff, and pushes "run failed" notifications after 3 attempts.
Where: add new module orchestrator/scheduler.py and a CLI, integrate with pipeline_runs table and dlq:failed stream, and send human-readable reports (email or a Slack webhook).
Quick next step: scaffold scanner.py-style process but reading pipeline state and DLQ to orchestrate retries.
Add the explicit Sector Rotation Matrix config and use it in RS1 (MEDIUM–HIGH)

Why: makes sector bias deterministic, auditable, and config-driven instead of ad-hoc lists.
What to add: config/sector_rotation_matrix.json (or YAML) and change rs1_macro.py to map regime→ETF bias using that file and persist the bias object in DB.
Quick next step: create config file and update RS1's _persist_regime to include the mapping currently described in the architecture doc.
Move report binary storage from git -> MinIO/S3 and update publisher (MEDIUM)

Why: repo-git is convenient for small teams, but S3/MinIO scales, is efficient for large files, and matches the spec (MinIO/S3).
What to modify: update pm3_publisher.py to upload PDFs to MinIO via boto3 (or MinIO SDK) and store S3 keys in DB; keep a lightweight git commit if desired for audit metadata only.
Quick next step: add MinIO client code and configuration variables; update render() to return bytes/path to upload.
Strengthen dedupe for EDGAR/event triggers by fiscal period (MEDIUM)

Why: watchers currently use Redis TTL keys (good), but the spec requires dedupe by (ticker, trigger_type, fiscal_period). This prevents duplicate reports across filing cycles.
What to change: in EDGAR watcher and trigger publication, compute a canonical dedupe key including fiscal period (extracted from filing metadata) and claim it atomically in Redis; also ensure pipeline_run_id encoding stores fiscal_period for downstream idempotency.
Files: update edgar_watcher.py and triggers/* and ensure ensure_pipeline_run or run creation includes fiscal_period metadata.
Add run-level alerting/observability and dashboard (LOW–MEDIUM)

Why: once orchestrator exists, add a dashboard or simple HTTP endpoint for run state and DLQ listings; add alerting to ops (email/SMS/Slack) when a run is FAILED.
Where: orchestrator + small FastAPI or static page that reads DB.
Schema versioning and more explicit schema registry (LOW)

Why: to support upgrades across running agents and make message contracts explicit/versioned.
What: add schema_version to MessageEnvelope and a small registry/compatibility checker in schemas.py or llm/router.
Add tests and budget controls for LLM fallback behavior (LOW)

Why: ensure Claude fallback and daily spend limit behaviors are tested and controlled.
Where: extend tests to mock Ollama downtime and assert router calls Claude and writes llm_calls ledger; add spend-limiter in router.py.
If you'd like, I can:

Scaffold the orchestrator service with the minimal retry/backoff logic and a CLI (I recommend starting here). (I will create orchestrator/monitor.py, wire DLQ/pipeline_runs checks, and provide unit tests.)
Or start with the sector rotation matrix config and patch rs1_macro.py to use it.
Which of the two should I implement first for you now: orchestrator service or sector_rotation_matrix config?