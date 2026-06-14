---
marp: true
theme: default
paginate: true
backgroundColor: #fdfdfd
style: |
  :root {
    --brand-primary: #d40707;
    --brand-secondary: #8b0000;
    --brand-accent: #ff6b35;
    --brand-light: #fffafa;
    --text-dark: #333;
    --text-medium: #666;
    --text-light: #999;
    --background: #fdfdfd;
    --white: #ffffff;
    --border-light: #ddd;
  }

  section {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    color: var(--text-dark);
    font-size: 26px;
    padding: 55px 65px 75px 65px;
    line-height: 1.5;
    background-size: cover;
    background-position: center;
  }

  h1 {
    color: var(--brand-primary);
    border-bottom: 3px solid var(--brand-primary);
    font-size: 1.5em;
    margin-top: 0;
    margin-bottom: 28px;
    padding-bottom: 14px;
    font-weight: 700;
    letter-spacing: -0.5px;
  }

  h2 {
    color: var(--brand-primary);
    font-size: 1.05em;
    margin-top: 26px;
    margin-bottom: 12px;
    font-weight: 600;
  }

  h3 {
    color: var(--brand-secondary);
    font-size: 0.92em;
    margin-top: 18px;
    margin-bottom: 8px;
    font-weight: 600;
  }

  p { margin: 12px 0; line-height: 1.6; }

  strong { color: var(--brand-secondary); font-weight: 600; }

  em { color: var(--brand-accent); font-style: italic; }

  ul, ol { margin: 12px 0; padding-left: 28px; }

  li { margin: 7px 0; line-height: 1.5; }

  li::marker { color: var(--brand-primary); font-weight: bold; }

  blockquote {
    background: var(--brand-light);
    border-left: 7px solid var(--brand-primary);
    padding: 18px 28px;
    font-style: italic;
    font-size: 0.88em;
    margin: 20px 0;
    color: var(--text-medium);
    line-height: 1.6;
  }

  code {
    background: #f5f5f5;
    padding: 2px 7px;
    border-radius: 4px;
    font-family: 'Monaco', 'Courier New', monospace;
    font-size: 0.82em;
    color: var(--brand-secondary);
  }

  pre {
    background: #f5f5f5;
    padding: 18px;
    border-radius: 8px;
    border-left: 4px solid var(--brand-primary);
    overflow-x: auto;
    font-size: 0.72em;
    line-height: 1.4;
    margin: 18px 0;
  }

  pre code { background: transparent; padding: 0; border-radius: 0; }

  table {
    width: 100%;
    border-collapse: collapse;
    margin: 20px 0;
    font-size: 0.76em;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  }

  th {
    background: linear-gradient(135deg, var(--brand-primary) 0%, var(--brand-secondary) 100%);
    color: white;
    padding: 12px 14px;
    text-align: left;
    vertical-align: top;
    font-weight: 600;
    letter-spacing: 0.4px;
  }

  td {
    border: 1px solid var(--border-light);
    padding: 11px 14px;
    text-align: left;
    background-color: var(--white);
    vertical-align: top;
  }

  tr:hover td { background-color: var(--brand-light); }

  .text-center { text-align: center; }
  .text-muted { color: var(--text-medium); font-size: 0.88em; }
  .text-small { font-size: 0.82em; }

  .badge {
    display: inline-block;
    background: var(--brand-primary);
    color: white;
    padding: 3px 11px;
    border-radius: 12px;
    font-size: 0.68em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .badge-secondary { background: var(--brand-accent); }

  .footnote {
    position: absolute;
    bottom: 35px;
    left: 65px;
    right: 65px;
    font-size: 0.62em;
    color: var(--text-medium);
    font-style: italic;
    border-top: 1px solid var(--border-light);
    padding-top: 9px;
  }

  .callout {
    background: var(--brand-light);
    border: 2px solid var(--brand-primary);
    padding: 20px 24px;
    border-radius: 10px;
    margin: 20px 0;
    box-shadow: 0 4px 12px rgba(212,7,7,0.08);
  }

  .callout-title {
    color: var(--brand-primary);
    font-weight: 700;
    font-size: 1em;
    margin-bottom: 8px;
  }

  .metric { text-align: center; padding: 16px; }

  .metric-value {
    font-size: 2.2em;
    font-weight: 700;
    color: var(--brand-primary);
    line-height: 1;
    margin-bottom: 5px;
  }

  .metric-label {
    font-size: 0.72em;
    color: var(--text-medium);
    text-transform: uppercase;
    letter-spacing: 1px;
  }

  .step { display: flex; align-items: flex-start; margin: 16px 0; }

  .step-number {
    background: var(--brand-primary);
    color: white;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 1.1em;
    flex-shrink: 0;
    margin-right: 18px;
  }

  .step-content { flex: 1; padding-top: 4px; }

  .info-box {
    background: #e3f2fd;
    border-left: 4px solid #2196f3;
    padding: 16px 20px;
    margin: 16px 0;
    border-radius: 4px;
    font-size: 0.88em;
  }

  .warning-box {
    background: #fff3e0;
    border-left: 4px solid #ff9800;
    padding: 16px 20px;
    margin: 16px 0;
    border-radius: 4px;
    font-size: 0.88em;
  }

  .success-box {
    background: #e8f5e9;
    border-left: 4px solid #4caf50;
    padding: 16px 20px;
    margin: 16px 0;
    border-radius: 4px;
    font-size: 0.88em;
  }

  .layout-2col {
    width: 100%;
    border-collapse: collapse;
    border: none;
    font-size: 0.88em;
    table-layout: fixed;
  }

  .layout-2col th {
    border: none;
    text-align: left;
    padding: 8px 14px;
    font-weight: 600;
    vertical-align: top;
    width: 50%;
    background: transparent;
    color: var(--brand-primary);
    box-shadow: none;
  }

  .layout-2col td {
    border: none;
    vertical-align: top;
    padding: 12px 14px;
    width: 50%;
    background: transparent;
    box-shadow: none;
  }

  .layout-3col {
    width: 100%;
    border-collapse: collapse;
    border: none;
    font-size: 0.82em;
    table-layout: fixed;
  }

  .layout-3col th {
    border: none;
    text-align: left;
    padding: 8px 11px;
    font-weight: 600;
    width: 33.33%;
    background: transparent;
    color: var(--brand-primary);
    box-shadow: none;
  }

  .layout-3col td {
    border: none;
    vertical-align: top;
    padding: 10px 11px;
    width: 33.33%;
    background: transparent;
    box-shadow: none;
  }

  .layout-boxed {
    width: 100%;
    border-collapse: collapse;
    border: 1px solid var(--border-light);
    font-size: 0.84em;
    table-layout: fixed;
  }

  .layout-boxed td {
    border: 1px solid var(--border-light);
    vertical-align: top;
    padding: 16px 18px;
    background: var(--white);
    width: 50%;
    box-shadow: none;
  }

  section.title-slide {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: flex-start;
    background: linear-gradient(135deg, var(--brand-primary) 0%, var(--brand-secondary) 100%);
    color: white;
    padding: 80px;
  }

  section.title-slide h1 {
    color: white;
    border-bottom: 3px solid rgba(255,255,255,0.5);
    font-size: 2.2em;
    margin-bottom: 18px;
    letter-spacing: -1px;
  }

  section.title-slide h2 {
    color: rgba(255,255,255,0.88);
    font-size: 1.15em;
    font-weight: 400;
    margin-top: 8px;
  }

  section.title-slide p {
    color: rgba(255,255,255,0.75);
    font-size: 0.88em;
    margin-top: 40px;
  }

  section.section-divider {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: flex-start;
    background: linear-gradient(135deg, var(--brand-secondary) 0%, var(--brand-primary) 100%);
    color: white;
    padding: 80px;
  }

  section.section-divider h1 {
    color: white;
    border-bottom: 2px solid rgba(255,255,255,0.35);
    font-size: 2em;
    margin-bottom: 16px;
  }

  section.section-divider h2 {
    color: rgba(255,255,255,0.78);
    font-size: 1em;
    font-weight: 400;
    margin-top: 6px;
  }

  section.title-slide header,
  section.section-divider header,
  section.title-slide footer,
  section.section-divider footer { display: none; }
---

<!-- ============================================================
     SLIDE 1 — TITLE
     ============================================================ -->

<!-- _class: title-slide -->
<!-- _paginate: false -->

# How an Equity Research Report Gets Made

## A first-principles guide for founders who want to understand how institutional money thinks

**Ankur Vatsa** &nbsp;|&nbsp; Equity Research Process &nbsp;|&nbsp; 2025

---

<!-- ============================================================
     SLIDE 2 — THE CORE PROBLEM
     ============================================================ -->

# The Problem the Report Is Solving

> "The market is a voting machine in the short run and a weighing machine over the long run." — Benjamin Graham

A stock price is simply the last price at which a buyer and seller exchanged one share. That number reflects the *collective opinion* of millions of participants about future cash flows. The collective opinion is frequently **wrong**.

<table class="layout-2col">
<tr>
<th>What creates the mispricing?</th>
<th>What the research delivers</th>
</tr>
<tr>
<td>
<ul>
<li>Overreaction to bad news</li>
<li>Underreaction to structural change</li>
<li>Index rebalancing and fund flows</li>
<li>Sentiment and narrative drift</li>
</ul>
</td>
<td>
<ul>
<li><strong>Investment thesis</strong> — why market is wrong</li>
<li><strong>12-month target price</strong> — from a model, not instinct</li>
<li><strong>Rating</strong> — Buy, Hold, or Sell. No hedging.</li>
</ul>
</td>
</tr>
</table>

<div class="footnote">Graham, B. & Dodd, D. (1934). Security Analysis. McGraw-Hill. The foundational text on value investing and market mispricing.</div>

---

<!-- ============================================================
     SLIDE 3 — WHO READS THESE REPORTS
     ============================================================ -->

# Who Uses Equity Research — and How

Research reports are not news articles. They are operational inputs for institutions managing **hundreds of millions of dollars** in allocation decisions.

<table class="layout-3col">
<tr>
<th>🏦 Who reads them</th>
<th>📋 What they decide</th>
<th>⚖️ What they demand</th>
</tr>
<tr>
<td>
<strong>Mutual Funds</strong><br>Fidelity, BlackRock, Vanguard<br><br>
<strong>Insurance Companies</strong><br>Float invested in equities<br><br>
<strong>Pension & Sovereign Funds</strong><br>Long-duration, low-tolerance for error
</td>
<td>
<strong>Position sizing</strong><br>How much capital to allocate<br><br>
<strong>Entry / exit timing</strong><br>When to buy or sell<br><br>
<strong>Risk management</strong><br>When to cut a losing position
</td>
<td>
<strong>Rigour</strong><br>Every number traces to a source<br><br>
<strong>Transparency</strong><br>Assumptions are explicit<br><br>
<strong>Defensibility</strong><br>The analyst owns the call
</td>
</tr>
</table>

<div class="callout">
<div class="callout-title">The standard</div>
Analysts are not expected to be right on every call. They are expected to be <strong>rigorous, transparent, and defensible</strong> on every call.
</div>

---

<!-- ============================================================
     SLIDE 4 — SECTION DIVIDER: THE PRODUCTION PIPELINE
     ============================================================ -->

<!-- _class: section-divider -->

# Part 1
## The Production Pipeline

*From macro signal to client inbox — what actually happens at each step*

---

<!-- ============================================================
     SLIDE 5 — THE 11-STEP PIPELINE
     ============================================================ -->

# The Report Production Pipeline

```
📡 Macro Signal → 🧠 Sector Thesis → 🔎 Company Selection → 📂 Data Collection
       ↓
📊 Three-Statement Model → 📐 Scenario Analysis → ✍️ Thesis Formulation
       ↓
🔍 Compliance Review → 📤 Publication → 📞 Client Meetings → 🔄 Ongoing Monitoring
                                                                       ↑_____________|
```

<table class="layout-2col">
<tr>
<th>Steps 1–4: Setup</th>
<th>Steps 5–11: Execution</th>
</tr>
<tr>
<td>
<ul>
<li><strong>Macro Signal</strong> — rate hike, regulatory change, commodity move</li>
<li><strong>Sector Thesis</strong> — directional view on who benefits / suffers</li>
<li><strong>Company Screen</strong> — which name is most mispriced?</li>
<li><strong>Data Collection</strong> — filings, calls, terminals, alt data</li>
</ul>
</td>
<td>
<ul>
<li><strong>Model Build</strong> — 3-statement integrated forecast</li>
<li><strong>Scenarios</strong> — bear, base, bull with explicit assumptions</li>
<li><strong>Thesis Write-Up</strong> — why wrong, what catalyst, when</li>
<li><strong>Compliance → Publish → Defend → Monitor</strong></li>
</ul>
</td>
</tr>
</table>

<div class="footnote">The loop is perpetual. Publication opens the coverage relationship; it does not close it. Every quarterly earnings cycle restarts from Data Collection.</div>

---

<!-- ============================================================
     SLIDE 6 — THE MOST COMMON MISTAKE
     ============================================================ -->

# The Mistake Every New Analyst Makes

<div class="warning-box">
<strong>❌ They jump straight to the company.</strong> They build a model, fall in love with the numbers, and wonder why the stock sells off despite solid business execution. The macro environment handed the entire sector a headwind. The company did not matter.
</div>

## The Correct Sequence: Top-Down, Always

<div class="step">
<div class="step-number">1</div>
<div class="step-content"><strong>Global Macro Regime</strong> — Interest rates, inflation, credit availability. Where is the cycle?</div>
</div>
<div class="step">
<div class="step-number">2</div>
<div class="step-content"><strong>Sector Identification</strong> — Which sectors does this macro regime reward? Where is institutional capital moving?</div>
</div>
<div class="step">
<div class="step-number">3</div>
<div class="step-content"><strong>Sub-Sector Dynamics</strong> — Supply chain structure, pricing power, barriers to entry within that sector</div>
</div>
<div class="step">
<div class="step-number">4</div>
<div class="step-content"><strong>Individual Company</strong> — Only now: business model, management track record, financial health</div>
</div>
<div class="step">
<div class="step-number">5</div>
<div class="step-content"><strong>Stock Valuation</strong> — The 12-month target price, derived from the model</div>
</div>

---

<!-- ============================================================
     SLIDE 7 — MACRO REGIMES AND SECTOR ROTATION
     ============================================================ -->

# Macro Regimes Drive Where Capital Flows

Different macroeconomic environments reward different sectors. This is "sector rotation" — practitioners move capital based on the regime, not just company fundamentals.

| Macro Regime | Rate / Inflation Profile | Capital Moves **Toward** | Capital Moves **Away From** |
|---|---|---|---|
| **High Inflation / Rate Hiking** | Rates rising, CPI elevated | Financials, Energy, Commodities | Pre-revenue Tech, long-duration growth |
| **Deflationary / Low-Growth** | Rates falling, GDP contracting | Consumer Staples, Healthcare, Utilities | Cyclicals, Industrials |
| **Early-Cycle Recovery** | Rates bottoming, credit loosening | Industrials, Materials, Consumer Discretionary | Defensives |
| **Late Cycle / Peak Growth** | Rates rising again, growth slowing | Quality + pricing power, Defensives | High-leverage, low-quality cyclicals |

<div class="callout">
<div class="callout-title">Primary input source</div>
US Federal Reserve published statements and FOMC minutes. Ray Dalio's "How the Economic Machine Works" (Bridgewater, 2013) is the clearest first-principles explanation of how credit cycles drive these flows.
</div>

---

<!-- ============================================================
     SLIDE 8 — CYCLICAL vs STRUCTURAL
     ============================================================ -->

# Cyclical vs. Structural: Two Completely Different Bets

<table class="layout-2col">
<tr>
<th>⏱️ Cyclical Upswing</th>
<th>🏗️ Structural Shift</th>
</tr>
<tr>
<td>
<strong>Temporary.</strong> Driven by commodity prices, inventory restocking, short-term credit conditions. When conditions reverse, the upswing ends.<br><br>
<em>Example:</em> A steel company posting record profits because iron ore prices spiked. Those profits disappear when iron ore normalises.<br><br>
<strong>Data signature:</strong> Commodity price indices, capacity utilisation statistics.
</td>
<td>
<strong>Permanent.</strong> Driven by regulation, technology adoption, demographic change that cannot be reversed.<br><br>
<em>Example:</em> An EV manufacturer gaining share because combustion engine bans are now legislated across multiple jurisdictions.<br><br>
<strong>Data signature:</strong> Legislative text, patent filing trends, UN World Population Prospects.
</td>
</tr>
</table>

These two situations produce **completely different** thesis durations, valuation multiples, and position sizing decisions.

<div class="footnote">Allocate ~70% of coverage capacity to structural inflections or deep cyclical dislocations. Reserve ~30% for idiosyncratic stories mispriced for company-specific reasons.</div>

---

<!-- ============================================================
     SLIDE 9 — SECTION DIVIDER: DATA STACK
     ============================================================ -->

<!-- _class: section-divider -->

# Part 2
## The Data Stack

*Where information comes from — and why the source order matters*

---

<!-- ============================================================
     SLIDE 10 — THE DATA STACK
     ============================================================ -->

# Four Layers of Research Data

<table class="layout-boxed">
<tr>
<td>
<strong>🔒 Primary Sources — Ground Truth</strong><br>
<span class="text-small text-muted">Always start here. Every aggregator derives from these.</span>
<ul style="font-size:0.85em;margin-top:8px;">
<li>SEC EDGAR — 10-K, 10-Q, 8-K filings</li>
<li>Expert network calls — GLG, AlphaSights, Guidepoint</li>
<li>Management calls, investor days, site visits</li>
</ul>
</td>
<td>
<strong>💻 Institutional Platforms — Aggregated Data</strong><br>
<span class="text-small text-muted">Fast access to normalised historical data.</span>
<ul style="font-size:0.85em;margin-top:8px;">
<li>Bloomberg Terminal — real-time prices, consensus</li>
<li>S&P Capital IQ / FactSet — model-building, screeners</li>
</ul>
</td>
</tr>
<tr>
<td>
<strong>🌐 Free Public Sources — Macro</strong><br>
<span class="text-small text-muted">800,000+ economic time series, all free.</span>
<ul style="font-size:0.85em;margin-top:8px;">
<li>FRED — Federal Reserve Economic Data</li>
<li>Company investor relations portals</li>
<li>SEC EDGAR (free — see Primary above)</li>
</ul>
</td>
<td>
<strong>📡 Alternative Data — Edge</strong><br>
<span class="text-small text-muted">Where differentiation actually originates.</span>
<ul style="font-size:0.85em;margin-top:8px;">
<li>Web scraping — Beautiful Soup / Scrapy</li>
<li>App store trackers — Sensor Tower, data.ai</li>
<li>Web traffic — SimilarWeb</li>
<li>Satellite imagery — parking lots, shipping yards</li>
</ul>
</td>
</tr>
</table>

---

<!-- ============================================================
     SLIDE 11 — SEC FILINGS DEEP DIVE
     ============================================================ -->

# Primary Filings: Go to the Source, Not the Aggregator

Every third-party aggregator derives from primary filings. Derivation introduces transcription errors, aggregation lags, and classification inconsistencies. The notes to financial statements — where the real information hides — are systematically misclassified.

<table class="layout-3col">
<tr>
<th>📄 10-K Annual Report</th>
<th>📋 10-Q Quarterly Report</th>
<th>⚡ 8-K Material Event</th>
</tr>
<tr>
<td>
Full-year financials, MD&A, risk factors.<br><br>
<strong>Key section:</strong> Notes to financial statements — off-balance-sheet obligations, lease liabilities, related-party transactions.
</td>
<td>
Same as 10-K, 90-day cycle.<br><br>
<strong>Value:</strong> Sequential tracking of accounts receivable, inventory, deferred revenue reveals acceleration or deterioration <em>before</em> headline numbers.
</td>
<td>
Filed within <strong>4 business days</strong> of any material event.<br><br>
CEO departure · acquisition · credit rating change · regulatory investigation<br><br>
<strong>These move prices on publication day.</strong>
</td>
</tr>
</table>

<div class="info-box">
<strong>Bloomberg Terminal functions that matter:</strong> &nbsp; <code>EE &lt;GO&gt;</code> — consensus estimates &nbsp;|&nbsp; <code>ANR &lt;GO&gt;</code> — all analyst ratings &nbsp;|&nbsp; <code>DDIS &lt;GO&gt;</code> — institutional ownership
</div>

---

<!-- ============================================================
     SLIDE 12 — EXPERT NETWORKS AND ALT DATA
     ============================================================ -->

# Expert Networks and Alternative Data

## Expert Networks: What No Filing Will Ever Tell You

Speaking to former operations managers and key suppliers reveals ground-level operational reality. GLG, AlphaSights, and Guidepoint are the three primary networks used by institutional research desks.

<table style="font-size:0.78em;">
<tr>
<th>Network</th>
<th>Client pays per hour (2024–25)</th>
<th>Expert receives</th>
</tr>
<tr>
<td>GLG, AlphaSights, Guidepoint</td>
<td><strong>$800–$1,500</strong> (standard experts)</td>
<td>~30–50% of client rate</td>
</tr>
<tr>
<td>Senior executives / rare specialists</td>
<td><strong>$2,000+</strong></td>
<td>Negotiated individually</td>
</tr>
</table>

<div class="warning-box">
<strong>⚠️ The MNPI boundary is absolute.</strong> If a former CFO discloses that the company missed its quarterly numbers before the official announcement, using that information constitutes insider trading under the US Securities Exchange Act Section 10(b). Criminal penalties apply. Run every call question through a compliance-approved framework first.
</div>

## Alternative Data is Where Differentiation Originates

Reading the same 10-K as 15 other analysts produces research indistinguishable from theirs. E-commerce price scrapers, app store trackers, web traffic analytics, and satellite imagery give a read on operational reality **weeks before earnings calls**.

---

<!-- ============================================================
     SLIDE 13 — SECTION DIVIDER: FINANCIAL DIAGNOSTICS
     ============================================================ -->

<!-- _class: section-divider -->

# Part 3
## The Core Financial Diagnostics

*Three statements, one linked system — and the ratios that matter before anything else*

---

<!-- ============================================================
     SLIDE 14 — THE THREE STATEMENTS
     ============================================================ -->

# Three Statements, One Linked System

The financial statements are not three separate documents. Every number in one traces to another. A model that does not balance without a manual plug contains an error.

```
📊 INCOME STATEMENT          🏦 BALANCE SHEET              💰 CASH FLOW STATEMENT
Revenue – Costs = Profit     Assets = Liabilities + Equity  Operating + Investing + Financing
  │ Period of time              │ Snapshot in time             │ Period of time
  │                             │                              │
  ├──→ Net Profit ──────────────→ Retained Earnings (Equity)  │
  │                             │                              │
  ├──→ Revenue drives ──────────→ Accounts Receivable         │
  │                             │                              │
  │    CapEx ───────────────────→ PP&E (Asset base) ──────────→ Cash outflow
  │                             │                              │
  └──← Depreciation ←───────────┤                             │
                                └─────────────────────────────→ Ending cash = Balance sheet cash ✓
```

<div class="callout">
<div class="callout-title">The analyst's primary truth-telling tool</div>
A company can book revenue before receiving payment and defer costs by capitalising them as assets. The <strong>income statement can look strong while the business consumes cash rapidly.</strong> The cash flow statement is structurally harder to manipulate — which is why analysts read it first.
</div>

<div class="footnote">Penman, S.H. (2013). Financial Statement Analysis and Security Valuation, 5th Ed., McGraw-Hill.</div>

---

<!-- ============================================================
     SLIDE 15 — SURVIVAL SCREEN
     ============================================================ -->

# The Survival Screen: Three Mandatory Metrics

Before assessing growth prospects, verify the company can survive. Every covered company passes through these three checks first.

<table class="layout-3col">
<tr>
<th>📊 Net Debt / EBITDA</th>
<th>📈 Interest Coverage</th>
<th>⏱️ Cash Conversion Cycle</th>
</tr>
<tr>
<td>
<code>(Total Debt – Cash) / EBITDA</code><br><br>
How many years of operating cash generation to retire all debt.<br><br>
<strong>Red flag: above 3.0×</strong><br>
Exception: regulated infrastructure with contracted long-duration cash flows.
</td>
<td>
<code>EBIT / Interest Expense</code><br><br>
A ratio of 2.5× means the company earns 2.5× its interest obligations from operating profit.<br><br>
<strong>Below 2.5× = financial stress approaching.</strong>
</td>
<td>
<code>DIO + DSO – DPO</code><br><br>
A <strong>negative CCC</strong> means the company collects cash from customers before paying suppliers.<br><br>
D-Mart, Walmart, and SaaS annual billing all achieve this. It is a structural competitive advantage.
</td>
</tr>
</table>

<table style="margin-top:12px;font-size:0.74em;">
<tr>
<th>Component</th>
<th>Measures</th>
<th>Formula</th>
</tr>
<tr>
<td>Days Inventory Outstanding (DIO)</td>
<td>How long goods sit before selling</td>
<td>Inventory ÷ (COGS ÷ 365)</td>
</tr>
<tr>
<td>Days Sales Outstanding (DSO)</td>
<td>How long to collect after a sale</td>
<td>Accounts Receivable ÷ (Revenue ÷ 365)</td>
</tr>
<tr>
<td>Days Payable Outstanding (DPO)</td>
<td>How long company takes to pay suppliers</td>
<td>Accounts Payable ÷ (COGS ÷ 365)</td>
</tr>
</table>

---

<!-- ============================================================
     SLIDE 16 — ROIC, WACC, FCF
     ============================================================ -->

# ROIC, WACC, and Why Fast Growth Can Destroy Value

<table class="layout-2col">
<tr>
<th>📐 The ROIC / WACC Relationship</th>
<th>💵 Free Cash Flow</th>
</tr>
<tr>
<td>
<strong>ROIC</strong> = NOPAT / Invested Capital<br>
<span class="text-small text-muted">NOPAT = EBIT × (1 – Tax Rate)</span><br><br>
<strong>WACC</strong> = blended required return of all capital providers<br>
<code>= (E/V × Ke) + (D/V × Kd × (1–Tax))</code><br><br>
<strong>The rule:</strong> ROIC > WACC = value creation. ROIC &lt; WACC = value destruction — regardless of how fast revenue grows.<br><br>
A company growing at 30% annually with ROIC below WACC is getting <em>larger and poorer simultaneously.</em>
</td>
<td>
<strong>FCF</strong> = Operating Cash Flow – CapEx<br><br>
The cash the business generates after maintaining and expanding its asset base. Every form of shareholder value creation — dividends, buybacks, debt repayment, acquisitions — requires sustained FCF.<br><br>
<strong>FCF Yield</strong> = FCF / Enterprise Value<br><br>
High net income with near-zero FCF signals either structural capital intensity or aggressive revenue recognition. The cash flow statement exposes this. The income statement cannot hide it indefinitely.
</td>
</tr>
</table>

<div class="footnote">Koller, T., Goedhart, M., & Wessels, D. (2020). Valuation: Measuring and Managing the Value of Companies, 7th Ed., McKinsey & Wiley.</div>

---

<!-- ============================================================
     SLIDE 17 — SECTION DIVIDER: SECTOR VALUATION
     ============================================================ -->

<!-- _class: section-divider -->

# Part 4
## Sector Valuation Frameworks

*One multiple applied to all sectors is analytically wrong — here is why each sector demands its own lens*

---

<!-- ============================================================
     SLIDE 18 — SECTOR MULTIPLE MATRIX
     ============================================================ -->

# One Framework Cannot Value Every Sector

A retail bank and a SaaS company share no meaningful financial architecture. A pharma company's most valuable asset — a drug in Phase III trials — does not appear on the balance sheet. Forcing them into the same valuation framework produces results that are precisely wrong.

| Sector | Primary Multiple | Why Not P/E | Key Non-GAAP Metrics |
|---|---|---|---|
| **Technology / SaaS** | EV / Fwd NTM Revenue | Profitability lags design; P/E penalises correctly | NRR >110%, Rule of 40, LTV/CAC >3× |
| **Banking / Financials** | Price-to-Book, P/E | EV is meaningless — debt is the raw material | NIM, CET1 >12%, GNPA%, PCR >70% |
| **Energy / Oil & Gas** | EV/EBITDAX, EV/BOE | Normalises for exploration accounting differences | RRR >100%, Lifting Cost per barrel |
| **Healthcare / Pharma** | Risk-Adjusted NPV, SOTP | Binary pipeline outcomes need probability weighting | Phase III count, Patent expiry calendar |
| **Retail / Consumer** | EV/EBITDA, P/E | Store economics are the operational driver | SSSG, GMV, Inventory Turnover |
| **Real Estate (REITs)** | Price/FFO, Dividend Yield | Depreciation distorts net income; FFO is the cash proxy | Occupancy, Cap Rate, NAV per unit |

---

<!-- ============================================================
     SLIDE 19 — SAAS VALUATION
     ============================================================ -->

# SaaS Valuation: Revenue First, Profitability Second

Traditional accounting fails software companies. Customer acquisition costs are expensed immediately, while subscription revenue materialises over 3–5 year contract periods. Penalising a SaaS company on P/E is analytically incorrect — the earnings metric is distorted by design.

<table class="layout-3col">
<tr>
<th>📊 ARR Growth</th>
<th>🔄 Net Revenue Retention</th>
<th>⚖️ Rule of 40</th>
</tr>
<tr>
<td>
Track <strong>sequential quarter-on-quarter</strong> ARR growth, not just year-on-year. Early inflections appear in the sequential signal first.
</td>
<td>
<code>NRR = (Start MRR + Expansion – Contraction – Churn) / Start MRR</code><br><br>
<strong>&gt;110%:</strong> Existing customers expand spend faster than some leave. Product grows within accounts.<br>
<strong>&lt;100%:</strong> New customers merely replace those leaving.
</td>
<td>
<code>YoY Revenue Growth % + EBITDA Margin %</code><br><br>
Score <strong>&gt;40 = healthy.</strong><br><br>
Growing 60% at –20% margin → scores 40 ✓<br>
Growing 10% at +15% margin → scores 25 ✗
</td>
</tr>
</table>

<div class="info-box">
<strong>For tech founders:</strong> NRR, Rule of 40, and ARR growth rate are the three metrics institutional analysts use to assess whether a SaaS business deserves a revenue multiple premium. Know your numbers before any investor conversation.
</div>

<div class="footnote">Andreessen Horowitz formalised the Rule of 40 as the canonical SaaS health benchmark. See a16z.com/the-rule-of-40-for-a-healthy-saas-company/</div>

---

<!-- ============================================================
     SLIDE 20 — PHARMA VALUATION
     ============================================================ -->

# Pharma Valuation: Probability-Weighted Binary Outcomes

A drug molecule either gets FDA approval or it does not. Standard DCF cannot handle binary probability distributions — which is why pharma demands its own framework.

## Risk-Adjusted Net Present Value (rNPV)

```
rNPV = (P(approval) × Peak Annual Revenue × Patent-Protected Duration)
         – Development and Commercialisation Costs
         [All discounted at WACC]
```

<table style="margin-top:12px;">
<tr>
<th>Trial Stage</th>
<th>Probability of reaching final approval</th>
<th>Implication for valuation</th>
</tr>
<tr>
<td>Phase I</td>
<td><strong>~9.6%</strong></td>
<td>A Phase I asset contributes very little to rNPV; it is an option, not a product</td>
</tr>
<tr>
<td>Phase II</td>
<td><strong>~20.9%</strong></td>
<td>Still heavily discounted; Phase II failures are common and expensive</td>
</tr>
<tr>
<td>Phase III</td>
<td><strong>~58.1%</strong></td>
<td>The valuation step change happens here — the majority of rNPV accretes at Phase III entry</td>
</tr>
</table>

<div class="footnote">Source: Biotechnology Innovation Organisation (BIO, 2016). Clinical Development Success Rates 2006–2015.</div>

---

<!-- ============================================================
     SLIDE 21 — SECTION DIVIDER: BUILDING THE MODEL
     ============================================================ -->

<!-- _class: section-divider -->

# Part 5
## Building the Financial Model

*How the three-statement model is constructed and stress-tested*

---

<!-- ============================================================
     SLIDE 22 — MODEL ARCHITECTURE
     ============================================================ -->

# Model Architecture: Revenue Down to Free Cash Flow

**Build revenue from components, not a single growth rate.** Volume drivers are company-specific — active subscribers, square footage operated, gigabytes consumed. Disaggregating forces explicit reasoning and makes the model auditable when fund managers challenge your assumptions.

```
📊 INCOME STATEMENT                 🏦 BALANCE SHEET                💰 CASH FLOW STATEMENT
─────────────────────────           ────────────────────────        ─────────────────────────
Revenue                             Accounts Receivable             Net Income
(Volume × Price)                    = DSO × Revenue ÷ 365          + Depreciation (add back)
    ↓                                   ↑ from IS                  ± Working Capital Changes
Gross Profit (Rev – COGS)          Inventory                           ↓
    ↓                               = DIO × COGS ÷ 365             Operating Cash Flow
EBITDA (– Opex)                    PP&E                                ↓
    ↓                               = Prior + CapEx – Depr         – Capital Expenditure
EBIT (– Depreciation)              Shareholders' Equity                ↓
    ↓                               = Prior + Net Income – Divs    Free Cash Flow
Net Income (– Interest – Tax)      Cash Balance ←──────────────────────────────────────────┘
    └───────────────────────────────────→ Retained Earnings
```

<div class="warning-box">
<strong>The balance sheet must balance automatically.</strong> If it only balances because of a manual plug, the model contains an error. Compliance reviewers and senior analysts will find it.
</div>

---

<!-- ============================================================
     SLIDE 23 — THREE SCENARIOS
     ============================================================ -->

# Three Scenarios Are Non-Negotiable

A single base case communicates almost nothing about risk. Institutional research requires explicit scenario architecture. The bear case matters as much as the bull case.

| Parameter | 🔴 Bear Case | 🟡 Base Case | 🟢 Bull Case |
|---|---|---|---|
| **Revenue Growth** | GDP rate or below | Management guidance achieved | 150–200% of guidance |
| **EBITDA Margin** | Contracts 200–400 bps | Holds flat or +50–100 bps | Expands 200–300 bps |
| **Capital Expenditure** | Elevated — defensive / maintenance-heavy | Maintenance + targeted growth CapEx | Efficiency gains reduce CapEx intensity |
| **Exit Multiple** | 20–30% discount to sector median | At current sector median | 20–30% premium to sector median |

<div class="callout">
<div class="callout-title">Why the bear case is the most important slide</div>
The bear case defines the exact conditions under which the thesis breaks and quantifies the capital destruction that follows. If the bear case still produces an acceptable return, risk/reward is asymmetric in the investor's favour. If it produces severe capital loss, position sizing must reflect that — regardless of how compelling the bull case looks.
</div>

---

<!-- ============================================================
     SLIDE 24 — DCF AND PEER MULTIPLES
     ============================================================ -->

# Two-Method Target Price: DCF + Peer Multiples

<table class="layout-2col">
<tr>
<th>📐 Discounted Cash Flow (DCF)</th>
<th>📊 Relative / Peer Multiples</th>
</tr>
<tr>
<td>
Derives intrinsic value from projected future cash flows, discounted at WACC.<br><br>
<code>EV = Σ [FCFt/(1+WACC)^t] + Terminal Value/(1+WACC)^n</code><br>
<code>Terminal Value = FCFn × (1+g) / (WACC – g)</code><br><br>
<strong>g (terminal growth)</strong> = 2–3% for US / developed economies<br><br>
<strong>Critical:</strong> Terminal value is 60–80% of total DCF output. A 0.5% change in <em>g</em> or WACC produces a dramatically different answer. Always present a sensitivity table.
</td>
<td>
Identify 6–10 genuinely comparable peers — similar growth profiles, capital structures, geographic exposure.<br><br>
<strong>Do not</strong> value a high-growth fintech using a mature payment processor's P/E — the growth rate differential alone makes the comparison indefensible.<br><br>
Pull each peer's current trading multiples → compute median → apply to subject company's NTM projected metric.<br><br>
Use peer multiples as the anchor for early-stage companies where near-term FCF is speculative.
</td>
</tr>
</table>

<div class="success-box">
<strong>Combined target price:</strong> <code>(60% × DCF Value) + (40% × Peer Multiple Value)</code> &nbsp;—&nbsp; The 60/40 split is a judgment call that shifts based on company maturity and cash flow visibility.
</div>

<div class="footnote">Damodaran, A. (2012). Investment Valuation, 3rd Ed., Wiley. The canonical reference for DCF across all asset classes. pages.stern.nyu.edu/~adamodar/</div>

---

<!-- ============================================================
     SLIDE 25 — SECTION DIVIDER: THE REPORT
     ============================================================ -->

<!-- _class: section-divider -->

# Part 6
## The Report Structure and the Rating

*What goes where — and how the final call gets made*

---

<!-- ============================================================
     SLIDE 26 — REPORT STRUCTURE
     ============================================================ -->

# Report Information Hierarchy

Clients read Page 1 with attention and skim everything after. Structure accordingly.

<div class="step">
<div class="step-number">1</div>
<div class="step-content"><strong>Page 1 — Investment Thesis, Rating, Target Price.</strong> Why is this stock mispriced right now? What specific catalyst closes the gap within 12 months? What evidence shows repricing has already begun? <em>This is not a company description.</em></div>
</div>
<div class="step">
<div class="step-number">2</div>
<div class="step-content"><strong>Financial Summary Table.</strong> Revenue, EBITDA, Net Income, EPS, FCF — FY-1 through FY+2. Key valuation multiples at current price and at target price.</div>
</div>
<div class="step">
<div class="step-number">3</div>
<div class="step-content"><strong>Business Model and Competitive Position.</strong> How does this company make money? What prevents replication? Where does pricing power sit in the value chain?</div>
</div>
<div class="step">
<div class="step-number">4</div>
<div class="step-content"><strong>Earnings Review — Actual vs. Consensus.</strong> Line-by-line: revenue, margins, FCF. Structural beats separated from one-time items.</div>
</div>
<div class="step">
<div class="step-number">5</div>
<div class="step-content"><strong>Three-Scenario Model + Sensitivity Tables.</strong> Bear, base, bull with explicit numbered assumptions. WACC / terminal growth sensitivity grid.</div>
</div>
<div class="step">
<div class="step-number">6</div>
<div class="step-content"><strong>Risk Factors — specific and quantified.</strong> Then: Appendix with comps tables, DCF detail, disclosures.</div>
</div>

---

<!-- ============================================================
     SLIDE 27 — RISK FACTORS DONE RIGHT
     ============================================================ -->

# Risk Factors: Specific and Quantified — or Useless

<table class="layout-2col">
<tr>
<th>❌ Wrong — Vague and Unchallengeable</th>
<th>✅ Right — Specific, Quantified, Actionable</th>
</tr>
<tr>
<td style="background:#fff5f5;">
<br>
"Macroeconomic deterioration could negatively impact the business."<br><br>
"The company faces competitive risks in its core markets."<br><br>
"Regulatory changes may affect operations."<br><br>
<em style="font-size:0.85em;">These are disclaimers. They tell the client nothing about when the thesis has broken or what to do when it does.</em>
</td>
<td style="background:#f5fff5;">
<br>
"A 75-basis-point rate hike cycle compresses NIM by 30 bps, reducing FY26E earnings by 18% and contracting the target P/B from 2.1× to 1.7×, eliminating all upside relative to the current price."<br><br>
<em style="font-size:0.85em;">This tells the client exactly what to watch, exactly when the thesis has broken, and exactly what the downside is. That is what risk factors exist to do.</em>
</td>
</tr>
</table>

<div class="callout">
<div class="callout-title">The standard for a valid risk factor</div>
A valid risk factor names the specific event or data point that would break the thesis, quantifies the earnings or multiple impact, and tells the client at what price the upside disappears.
</div>

---

<!-- ============================================================
     SLIDE 28 — THE RATING SYSTEM
     ============================================================ -->

# The Rating: Making the Call Without Hedging

The rating must match the model output. A Hold on a stock where the base case DCF implies 40% upside is analytically incoherent — and compliance will return the report for reconciliation before it publishes.

<table style="margin-top:10px;">
<tr>
<th style="width:22%;">Rating</th>
<th style="width:48%;">Definition</th>
<th style="width:30%;">Return Threshold</th>
</tr>
<tr>
<td><strong>🟢 BUY / OVERWEIGHT</strong></td>
<td>Expected total return (price appreciation + dividends) exceeds the sector hurdle rate or benchmark index</td>
<td><strong>&gt;15% above hurdle</strong> over 12 months</td>
</tr>
<tr>
<td><strong>🟡 HOLD / NEUTRAL</strong></td>
<td>Expected return within ±5% of the benchmark. Stock is fairly priced; capital here generates an opportunity cost relative to better-rated names</td>
<td><strong>±5% of index</strong></td>
</tr>
<tr>
<td><strong>🔴 SELL / UNDERWEIGHT</strong></td>
<td>Expected return is negative or underperforms the hurdle by more than 15%. Structural deterioration or fundamental overvaluation</td>
<td><strong>&gt;15% below hurdle</strong></td>
</tr>
</table>

<div class="info-box" style="margin-top:16px;">
<strong>When 90% of analysts carry a Buy on the same stock,</strong> that crowding is itself information — it tells you how much optimism is already priced in. Use <code>ANR &lt;GO&gt;</code> on Bloomberg to see the distribution. Positioning against a crowded consensus is where differentiated calls live.
</div>

---

<!-- ============================================================
     SLIDE 29 — THE ONGOING COVERAGE LOOP
     ============================================================ -->

# The Coverage Loop Never Closes

Publishing an initiation note opens a coverage relationship. The obligations that follow are fixed and non-negotiable.

<table class="layout-3col">
<tr>
<th>📅 Quarterly Earnings Reviews</th>
<th>📡 Catalyst Monitoring</th>
<th>🔄 Annual Model Reset</th>
</tr>
<tr>
<td>
Within <strong>24–48 hours</strong> of results publication:<br><br>
<ul style="font-size:0.85em;">
<li>Updated note comparing actual vs. model estimates, line by line</li>
<li>Forward estimates revised explicitly</li>
<li>If story has changed materially, the rating changes to match</li>
</ul>
</td>
<td>
Regulatory filings, management commentary, competitor pricing moves, sector data releases.<br><br>
An 8-K announcing a material contract win or supply chain disruption at a key supplier requires <strong>assessment within hours</strong>, and a client note if material.
</td>
<td>
After each Annual Report is published:<br><br>
<strong>Rebuild the three-year forward model from current actuals.</strong><br><br>
Do not roll forward stale assumptions. Reset from the reported base — always.
</td>
</tr>
</table>

<div class="callout">
<div class="callout-title">What builds a research franchise</div>
Analysts who flag problems before the market forces them to, revise estimates ahead of consensus, and own their mistakes publicly rather than burying them in footnote revisions. That track record — accumulated over years of accurate, consistent coverage — is what institutional clients return for.
</div>

---

<!-- ============================================================
     SLIDE 30 — KEY METRICS REFERENCE
     ============================================================ -->

# Core Metrics Reference Card

<table style="font-size:0.72em;">
<tr>
<th>Metric</th>
<th>Formula</th>
<th>Red Flag Threshold</th>
<th>What It Signals</th>
</tr>
<tr>
<td><strong>Net Debt / EBITDA</strong></td>
<td>(Total Debt – Cash) / EBITDA</td>
<td>&gt;3.0×</td>
<td>Leverage stress; debt may not be serviceable from operations</td>
</tr>
<tr>
<td><strong>Interest Coverage</strong></td>
<td>EBIT / Interest Expense</td>
<td>&lt;2.5×</td>
<td>Financial stress approaching; earnings absorbed by interest</td>
</tr>
<tr>
<td><strong>ROIC vs WACC</strong></td>
<td>NOPAT / Invested Capital vs blended cost of capital</td>
<td>ROIC &lt; WACC</td>
<td>Growth destroys value; company getting larger and poorer</td>
</tr>
<tr>
<td><strong>FCF Yield</strong></td>
<td>Free Cash Flow / Enterprise Value</td>
<td>Persistently negative</td>
<td>Income statement divorced from cash reality</td>
</tr>
<tr>
<td><strong>NRR (SaaS)</strong></td>
<td>(Start MRR + Expansion – Churn) / Start MRR</td>
<td>&lt;100%</td>
<td>New customers only replacing those leaving — no organic growth</td>
</tr>
<tr>
<td><strong>Rule of 40 (SaaS)</strong></td>
<td>Revenue Growth % + EBITDA Margin %</td>
<td>&lt;40</td>
<td>Growth-to-profitability balance is off</td>
</tr>
<tr>
<td><strong>GNPA% (Banks)</strong></td>
<td>Gross NPA / Total Loan Book</td>
<td>Rising 3 qtrs consecutive</td>
<td>Underwriting deterioration; credit losses incoming</td>
</tr>
<tr>
<td><strong>SSSG (Retail)</strong></td>
<td>Same-store sales YoY, stores &gt;12 months open</td>
<td>Negative while total rev grows</td>
<td>Expanding footprint while existing business deteriorates</td>
</tr>
<tr>
<td><strong>RRR (Energy)</strong></td>
<td>New Proved Reserves / Reserves Produced</td>
<td>&lt;100%</td>
<td>Company depleting faster than it replaces — reserves shrinking</td>
</tr>
</table>

---

<!-- ============================================================
     SLIDE 31 — CLOSING SLIDE
     ============================================================ -->

<!-- _class: title-slide -->
<!-- _paginate: false -->

# The Process in One Sentence

## Top-down macro → sector selection → company screening → integrated three-statement model → three scenarios → two-method valuation → one defensible rating.

**Ankur Vatsa**

[ankur.vatsa@gmail.com](mailto:ankur.vatsa@gmail.com) &nbsp;|&nbsp; [LinkedIn](https://www.linkedin.com/in/ankurvatsa/) &nbsp;|&nbsp; [Medium](https://medium.com/@ankur.vatsa)
