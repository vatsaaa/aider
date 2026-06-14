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
    font-size: 28px;
    padding: 60px 70px 80px 70px;
    line-height: 1.5;
  }

  h1 {
    color: var(--brand-primary);
    border-bottom: 3px solid var(--brand-primary);
    font-size: 1.5em;
    margin-top: 0;
    margin-bottom: 30px;
    padding-bottom: 15px;
    font-weight: 600;
    letter-spacing: -0.5px;
  }

  h2 {
    color: var(--brand-primary);
    font-size: 1.1em;
    margin-top: 30px;
    margin-bottom: 15px;
    font-weight: 600;
  }

  h3 {
    color: var(--brand-secondary);
    font-size: 0.95em;
    margin-top: 20px;
    margin-bottom: 10px;
    font-weight: 600;
  }

  p { margin: 15px 0; line-height: 1.6; }

  strong { color: var(--brand-secondary); font-weight: 600; }
  em { color: var(--brand-accent); font-style: italic; }

  ul, ol { margin: 15px 0; padding-left: 30px; }
  li { margin: 8px 0; line-height: 1.5; }
  li::marker { color: var(--brand-primary); font-weight: bold; }

  blockquote {
    background: var(--brand-light);
    border-left: 8px solid var(--brand-primary);
    padding: 20px 30px;
    font-style: italic;
    font-size: 0.9em;
    margin: 25px 0;
    color: var(--text-medium);
    line-height: 1.6;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    margin: 25px 0;
    font-size: 0.8em;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  }

  th {
    background: linear-gradient(135deg, var(--brand-primary) 0%, var(--brand-secondary) 100%);
    color: white;
    padding: 15px;
    text-align: left;
    vertical-align: top;
    font-weight: 600;
    letter-spacing: 0.5px;
  }

  td {
    border: 1px solid var(--border-light);
    padding: 15px;
    text-align: left;
    background-color: var(--white);
    vertical-align: top;
  }

  tr:hover td { background-color: var(--brand-light); }

  .footnote {
    position: absolute;
    bottom: 40px;
    left: 70px;
    right: 70px;
    font-size: 0.65em;
    color: var(--text-medium);
    font-style: italic;
    border-top: 1px solid var(--border-light);
    padding-top: 10px;
  }

  .badge {
    display: inline-block;
    background: var(--brand-primary);
    color: white;
    padding: 4px 12px;
    border-radius: 12px;
    font-size: 0.7em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .badge-green {
    display: inline-block;
    background: #2e7d32;
    color: white;
    padding: 4px 12px;
    border-radius: 12px;
    font-size: 0.7em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .badge-blue {
    display: inline-block;
    background: #1565c0;
    color: white;
    padding: 4px 12px;
    border-radius: 12px;
    font-size: 0.7em;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .callout {
    background: var(--brand-light);
    border: 2px solid var(--brand-primary);
    padding: 25px;
    border-radius: 10px;
    margin: 25px 0;
    box-shadow: 0 4px 12px rgba(212, 7, 7, 0.1);
  }

  .callout-title {
    color: var(--brand-primary);
    font-weight: 600;
    font-size: 1.1em;
    margin-bottom: 10px;
  }

  .info-box {
    background: #e3f2fd;
    border-left: 4px solid #1565c0;
    padding: 20px;
    margin: 20px 0;
    border-radius: 4px;
    font-size: 0.85em;
  }

  .warning-box {
    background: #fff3e0;
    border-left: 4px solid #e65100;
    padding: 20px;
    margin: 20px 0;
    border-radius: 4px;
    font-size: 0.85em;
  }

  .metric {
    text-align: center;
    padding: 20px;
  }

  .metric-value {
    font-size: 2.5em;
    font-weight: 700;
    color: var(--brand-primary);
    line-height: 1;
    margin-bottom: 5px;
  }

  .metric-label {
    font-size: 0.8em;
    color: var(--text-medium);
    text-transform: uppercase;
    letter-spacing: 1px;
  }

  .layout-2col {
    width: 100%;
    border-collapse: collapse;
    border: none;
    font-size: 26px;
    font-family: 'Helvetica Neue', Arial, sans-serif;
    color: var(--text-dark);
    line-height: 1.4;
    table-layout: fixed;
  }

  .layout-2col th {
    border: none;
    text-align: left;
    padding: 8px 15px;
    font-weight: 600;
    vertical-align: top;
    width: 50%;
    background: transparent;
    color: var(--brand-primary);
  }

  .layout-2col td {
    border: none;
    vertical-align: top;
    padding: 15px;
    width: 50%;
    background: transparent;
  }

  .layout-3col {
    width: 100%;
    border-collapse: collapse;
    border: none;
    font-size: 22px;
    table-layout: fixed;
  }

  .layout-3col th {
    border: none;
    text-align: left;
    padding: 8px 12px;
    font-weight: 600;
    width: 33.33%;
    background: transparent;
    color: var(--brand-primary);
  }

  .layout-3col td {
    border: none;
    vertical-align: top;
    padding: 12px;
    width: 33.33%;
    background: transparent;
  }

  .layout-boxed {
    width: 100%;
    border-collapse: collapse;
    border: 1px solid var(--border-light);
    font-size: 24px;
    table-layout: fixed;
  }

  .layout-boxed td {
    border: 1px solid var(--border-light);
    vertical-align: top;
    padding: 20px;
    background: var(--white);
    width: 50%;
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
    border-bottom: 3px solid white;
    font-size: 2.5em;
    margin-bottom: 20px;
  }

  section.title-slide h2 {
    color: rgba(255,255,255,0.9);
    font-size: 1.3em;
    font-weight: 400;
  }

  section.section-divider {
    display: flex;
    justify-content: center;
    align-items: center;
    background: linear-gradient(135deg, var(--brand-secondary) 0%, var(--brand-primary) 100%);
    color: white;
    text-align: center;
  }

  section.section-divider h1 {
    color: white;
    border: none;
    font-size: 3em;
    margin: 0;
  }

  .step {
    display: flex;
    align-items: flex-start;
    margin: 14px 0;
  }

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

  .step-content {
    flex: 1;
    padding-top: 4px;
    font-size: 0.88em;
  }
---

<!-- SLIDE 1: TITLE -->
<!-- _class: title-slide -->

# 9 Stages to Published Equity Research
## Raw Macro Signal to Published Buy or Sell Rating — US Markets Edition

**Ankur Vatsa** | 2025

---

<!-- SLIDE 2: WHAT EVERY REPORT MUST DELIVER -->

# Every Research Report Delivers Exactly Three Things

<table class="layout-3col">
  <tr>
    <th>01 — The Investment Thesis</th>
    <th>02 — A 12-Month Target Price</th>
    <th>03 — A Rating: Buy / Hold / Sell</th>
  </tr>
  <tr>
    <td>
      Specific, evidence-backed argument for why the market is mispricing this stock <em>right now</em>.<br><br>
      <strong>The thesis answers:</strong> Why is the price wrong today? What specific event will correct it? In what time window?
    </td>
    <td>
      A number derived from a quantitative model — not instinct.<br><br>
      Backed by DCF analysis + peer comparable multiples, with explicit Bear / Base / Bull scenario assumptions. Per <strong>Damodaran (2012)</strong>, intrinsic value is a function of cash flows, growth, and risk — not of price momentum.
    </td>
    <td>
      Unambiguous capital allocation instruction for institutional clients.<br><br>
      The rating <em>must</em> match the model output. A Hold when DCF implies 40% upside is analytically incoherent — SEC Reg AC compliance review will return it.
    </td>
  </tr>
</table>

<div class="footnote">* Reports are used by mutual funds (Fidelity, Vanguard, T. Rowe Price), pension funds, insurance companies, and sovereign wealth funds making allocation decisions worth hundreds of millions of dollars.</div>

---

<!-- SLIDE 3: THE 9-STAGE PIPELINE -->

# The 9-Stage Research Production Pipeline

<table class="layout-3col" style="font-size:20px;">
  <tr>
    <th style="background:#f97316;color:white;padding:10px;border-radius:4px 0 0 0;">RESEARCH SETUP</th>
    <th style="background:#f97316;color:white;padding:10px;">RESEARCH SETUP</th>
    <th style="background:#f97316;color:white;padding:10px;border-radius:0 4px 0 0;">RESEARCH SETUP</th>
  </tr>
  <tr>
    <td style="border:2px solid #f97316;"><strong style="color:#f97316;">RS1 — Macro Signal</strong><br><em>Read the environment</em></td>
    <td style="border:2px solid #f97316;"><strong style="color:#f97316;">RS2 — Sector Thesis</strong><br><em>Form the direction call</em></td>
    <td style="border:2px solid #f97316;"><strong style="color:#f97316;">RS3 — Company Screen</strong><br><em>Find mispriced candidates</em></td>
  </tr>
  <tr>
    <th style="background:var(--brand-primary);color:white;padding:10px;">ANALYSIS & VALUATION</th>
    <th style="background:var(--brand-primary);color:white;padding:10px;">ANALYSIS & VALUATION</th>
    <th style="background:var(--brand-primary);color:white;padding:10px;">ANALYSIS & VALUATION</th>
  </tr>
  <tr>
    <td style="border:2px solid var(--brand-primary);"><strong style="color:var(--brand-primary);">AV1 — Data Collection</strong><br><em>Build the data package</em></td>
    <td style="border:2px solid var(--brand-primary);"><strong style="color:var(--brand-primary);">AV2 — Financial Model</strong><br><em>3-statement forecast</em></td>
    <td style="border:2px solid var(--brand-primary);"><strong style="color:var(--brand-primary);">AV3 — Valuation</strong><br><em>DCF + peer multiples</em></td>
  </tr>
  <tr>
    <th style="background:var(--brand-secondary);color:white;padding:10px;">PUBLISH & MONITOR</th>
    <th style="background:var(--brand-secondary);color:white;padding:10px;">PUBLISH & MONITOR</th>
    <th style="background:var(--brand-secondary);color:white;padding:10px;">PUBLISH & MONITOR</th>
  </tr>
  <tr>
    <td style="border:2px solid var(--brand-secondary);"><strong style="color:var(--brand-secondary);">PM1 — Write Thesis</strong><br><em>Draft the research note</em></td>
    <td style="border:2px solid var(--brand-secondary);"><strong style="color:var(--brand-secondary);">PM2 — Review & Comply</strong><br><em>SEC Reg AC + disclosures</em></td>
    <td style="border:2px solid var(--brand-secondary);"><strong style="color:var(--brand-secondary);">PM3 — Publish & Track</strong><br><em>Distribute and monitor</em></td>
  </tr>
</table>

---

<!-- SLIDE 4: STAGE 1 — MACRO SIGNAL -->
<!-- _class: section-divider -->

# Stage 1
## Reading the Macro Environment

---

# Stage 1 — Reading the Macro Environment
*Identify the interest rate regime and sector rotation direction before touching a single stock*

<table class="layout-3col" style="font-size:20px;">
  <tr>
    <th style="background:#f59e0b;color:white;padding:10px;">INPUTS</th>
    <th style="background:var(--brand-primary);color:white;padding:10px;">PAID TOOLS</th>
    <th style="background:#2e7d32;color:white;padding:10px;">OUTPUTS: 1–2 pages</th>
  </tr>
  <tr>
    <td style="border:1px solid #f59e0b;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Fed FOMC statements and dot plot</li>
        <li>CPI / PCE inflation data (BLS)</li>
        <li>10yr–2yr Treasury yield spread</li>
        <li>ISM Manufacturing PMI</li>
        <li>S&P 500 aggregate earnings beat/miss ratios by sector</li>
        <li>Fed H.8 data (bank credit growth)</li>
      </ul>
    </td>
    <td style="border:1px solid var(--brand-primary);">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Bloomberg: WIRP (market-implied rate expectations), ECFC (consensus forecasts)</li>
        <li>Refinitiv Eikon macro dashboards</li>
        <li>BCA Research / ISI Evercore sector reports</li>
      </ul>
    </td>
    <td style="border:1px solid #2e7d32;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Regime classification: Hiking / Easing / Recovery / Peak cycle</li>
        <li>Sector direction call: overweight / underweight</li>
        <li>Capital flow call: what moves where and why</li>
        <li>Written macro memo</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td colspan="3" style="border:1px solid #1565c0;background:#e3f2fd;">
      <strong style="color:#1565c0;">FREE ALTERNATIVES:</strong>
      <span style="font-size:0.82em;">
        FRED (fred.stlouisfed.org) — 800K+ US economic time series &nbsp;|&nbsp;
        Fed H.8 + FDIC call reports &nbsp;|&nbsp;
        Trading Economics for global macro tracker &nbsp;|&nbsp;
        Yahoo Finance for bond yield data, sector ETF performance
      </span>
    </td>
  </tr>
</table>

---

<!-- SLIDE 5: STAGE 2 — SECTOR THESIS -->

# Stage 2 — Forming the Sector Thesis
*Translate the macro call into a specific sector direction with a quantified catalyst timeline*

<table class="layout-3col" style="font-size:20px;">
  <tr>
    <th style="background:#f59e0b;color:white;padding:10px;">INPUTS</th>
    <th style="background:var(--brand-primary);color:white;padding:10px;">PAID TOOLS</th>
    <th style="background:#2e7d32;color:white;padding:10px;">OUTPUTS: 1–2 pages</th>
  </tr>
  <tr>
    <td style="border:1px solid #f59e0b;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Macro regime call from Stage RS1</li>
        <li>SEC rulemaking releases and Congressional legislation</li>
        <li>Historical sector rotation patterns (prior cycles)</li>
        <li>Peer earnings trends — last 4–8 quarters by sector</li>
        <li>Energy / commodity price data (EIA, CME)</li>
      </ul>
    </td>
    <td style="border:1px solid var(--brand-primary);">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Bloomberg sector analytics</li>
        <li>Gartner / IDC for technology sector sizing</li>
        <li>BCA Research / Strategas sector research</li>
      </ul>
    </td>
    <td style="border:1px solid #2e7d32;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Sector thesis memo: why this sector, why now</li>
        <li>Overweight / Underweight call with quantified mispricing estimate</li>
        <li>Catalyst timeline: what specific event closes the pricing gap</li>
        <li>Structural vs. cyclical classification</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td colspan="3" style="border:1px solid #1565c0;background:#e3f2fd;">
      <strong style="color:#1565c0;">FREE ALTERNATIVES:</strong>
      <span style="font-size:0.82em;">
        SEC EDGAR full-text search for regulatory filings &nbsp;|&nbsp;
        EIA.gov for energy sector data &nbsp;|&nbsp;
        Census Bureau for manufacturing and trade statistics &nbsp;|&nbsp;
        Google Trends for early demand signals in consumer-facing sectors &nbsp;|&nbsp;
        UN World Population Prospects for long-duration demographic theses
      </span>
    </td>
  </tr>
</table>

---

<!-- SLIDE 6: MACRO REGIME TABLE -->

# Macro Regimes Drive Sector Rotation

| Macro Regime | Rate / Inflation Profile | Capital Flows Toward | Capital Flows Away From |
|---|---|---|---|
| **High Inflation / Rate Hiking** | Rates rising, CPI elevated | Financials (banks widen NIM), Energy, Commodities | Pre-revenue Tech, long-duration growth |
| **Deflationary / Low-Growth** | Rates near zero, GDP contracting | Consumer Staples, Healthcare, Utilities | Cyclicals, Industrials |
| **Early-Cycle Recovery** | Rates bottoming, credit loosening | Industrials, Materials, Consumer Discretionary | Defensives |
| **Late Cycle / Peak Growth** | Rates rising again, growth decelerating | Quality companies with pricing power | High-leverage, low-quality cyclicals |

<div class="callout" style="margin-top:20px;">
<div class="callout-title">Cyclical vs. Structural: The Thesis Duration Decision</div>
<span style="font-size:0.85em;">A steel company posting record profits because iron ore spiked is a <strong>cyclical story</strong> — thesis duration months, not years. A semiconductor company gaining share because the CHIPS Act mandates domestic fab capacity is a <strong>structural story</strong> — thesis duration years. The distinction drives everything: valuation multiples, position sizing, and how aggressively to defend the call when the market disagrees.</span>
</div>

---

<!-- SLIDE 7: STAGE 3 — COMPANY SCREEN -->

# Stage 3 — Company Screening & Selection
*Find the most mispriced candidate in the favoured sector using quantitative filters*

<table class="layout-3col" style="font-size:20px;">
  <tr>
    <th style="background:#f59e0b;color:white;padding:10px;">INPUTS</th>
    <th style="background:var(--brand-primary);color:white;padding:10px;">PAID TOOLS</th>
    <th style="background:#2e7d32;color:white;padding:10px;">OUTPUTS: 3–5 candidates</th>
  </tr>
  <tr>
    <td style="border:1px solid #f59e0b;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Sector thesis from Stage 2</li>
        <li>Full listed peer universe (all companies in the sector)</li>
        <li>Preliminary valuation benchmarks (what is "cheap" vs. sector history)</li>
        <li>Analyst coverage map (who is followed vs. ignored)</li>
      </ul>
    </td>
    <td style="border:1px solid var(--brand-primary);">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Bloomberg EQS Equity Screener — multi-factor screens across 80K+ securities</li>
        <li>S&P Capital IQ: Financial screeners with normalized 10yr data</li>
        <li>FactSet: Quantitative alpha screening tools</li>
        <li>Refinitiv Alpha Screener</li>
      </ul>
    </td>
    <td style="border:1px solid #2e7d32;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Preliminary thesis on each: why mispriced vs. peers</li>
        <li>Initial comparative valuation snapshot (P/E, EV/EBITDA, P/B)</li>
        <li>Coverage gap identification: unfollowed or thin-coverage names</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td colspan="3" style="border:1px solid #1565c0;background:#e3f2fd;">
      <strong style="color:#1565c0;">FREE ALTERNATIVES:</strong>
      <span style="font-size:0.82em;">
        Finviz.com — comprehensive multi-factor screener for US equities &nbsp;|&nbsp;
        Macrotrends.net — US historical P/E, EV/EBITDA, revenue ratios &nbsp;|&nbsp;
        SEC EDGAR XBRL viewer for structured financial data &nbsp;|&nbsp;
        Simply Wall St for initial coverage gap identification
      </span>
    </td>
  </tr>
</table>

---

<!-- SLIDE 8: STAGE 4 — DATA COLLECTION -->

# Stage 4 — Data Collection
*Build the complete data package — primary filings first, aggregators second*

<table class="layout-3col" style="font-size:20px;">
  <tr>
    <th style="background:#f59e0b;color:white;padding:10px;">INPUTS</th>
    <th style="background:var(--brand-primary);color:white;padding:10px;">PAID TOOLS</th>
    <th style="background:#2e7d32;color:white;padding:10px;">OUTPUTS</th>
  </tr>
  <tr>
    <td style="border:1px solid #f59e0b;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Company shortlist from Stage RS3</li>
        <li>Specific mispricing hypothesis to stress-test</li>
        <li>Expert call budget (if available)</li>
      </ul>
    </td>
    <td style="border:1px solid var(--brand-primary);">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>S&P Capital IQ: 10+ yr normalized financials, notes-to-accounts parsing</li>
        <li>Bloomberg ANR (all analyst ratings + targets) and DDIS (institutional ownership)</li>
        <li>GLG / AlphaSights / Guidepoint: Expert calls @ $500–1,500/hr</li>
        <li>FactSet: Historical consensus estimate time series</li>
      </ul>
    </td>
    <td style="border:1px solid #2e7d32;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>5–10 yr historical financial dataset (IS, B/S, CFS)</li>
        <li>Earnings transcript archive (last 8–12 quarters minimum)</li>
        <li>Analyst consensus snapshot (estimates + revision direction)</li>
        <li>Expert call notes (operational reality check)</li>
        <li>Related-party + auditor notes (accounting quality screen)</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td colspan="3" style="border:1px solid #1565c0;background:#e3f2fd;">
      <strong style="color:#1565c0;">FREE ALTERNATIVES:</strong>
      <span style="font-size:0.82em;">
        <strong>SEC EDGAR</strong> (sec.gov/edgar) — 10-K, 10-Q, 8-K: the source of truth for all US data &nbsp;|&nbsp;
        Company IR websites: earnings call audio, investor day slides &nbsp;|&nbsp;
        Seeking Alpha transcripts (free tier): last 8Q earnings calls &nbsp;|&nbsp;
        Macrotrends: pre-parsed US historical financials, 15yr+
      </span>
    </td>
  </tr>
</table>

<div class="warning-box" style="margin-top:10px;font-size:0.78em;">
<strong>MNPI Boundary — Non-Negotiable:</strong> Material non-public information cannot be traded on or included in research. A former CFO disclosing a revenue miss before the 8-K files is insider trading. SEC Exchange Act Section 10(b) and SEC Reg FD apply criminal penalties. All expert call questions must clear a compliance-approved framework before the call.
</div>

---

<!-- SLIDE 9: US PRIMARY FILINGS REFERENCE -->

# The US Primary Filing Stack

<table class="layout-3col" style="font-size:21px;">
  <tr>
    <th>10-K — Annual Report</th>
    <th>10-Q — Quarterly Report</th>
    <th>8-K — Material Event</th>
  </tr>
  <tr>
    <td>
      Full-year financials, MD&A, risk factors, and — critically — the <strong>notes to financial statements</strong>.<br><br>
      Notes are where the real information lives: off-balance-sheet obligations, operating lease liabilities, contingent liabilities, related-party transactions. Bloomberg and Capital IQ systematically miss or misclassify these.
    </td>
    <td>
      The 10-K on a 90-day cycle. Sequential tracking is the value — changes in accounts receivable, inventory, and deferred revenue across quarters reveal business acceleration or deterioration <em>before</em> they appear in headline numbers.<br><br>
      A company with rising DSO and falling inventory turns is telegraphing a demand problem quarters in advance.
    </td>
    <td>
      Filed within <strong>four business days</strong> of any material corporate event: CEO departure, acquisition announcement, credit rating change, SEC investigation, material contract win.<br><br>
      These move prices the day they publish. Bloomberg 8-K alerts on covered tickers are non-optional. The market reacts; the analyst needs to have already read the filing.
    </td>
  </tr>
</table>

<div class="footnote">* Source: All three filings are free on SEC EDGAR (sec.gov/edgar). Every third-party aggregator derives its data from these filings — derivation introduces transcription errors, aggregation lags, and classification inconsistencies. Always go to the source.</div>

---

<!-- SLIDE 10: STAGE 5 — FINANCIAL MODEL -->

# Stage 5 — Building the Three-Statement Financial Model
*An integrated operating forecast — every output traces to an explicit, documented assumption*

<table class="layout-3col" style="font-size:20px;">
  <tr>
    <th style="background:#f59e0b;color:white;padding:10px;">INPUTS</th>
    <th style="background:var(--brand-primary);color:white;padding:10px;">PAID TOOLS</th>
    <th style="background:#2e7d32;color:white;padding:10px;">OUTPUTS</th>
  </tr>
  <tr>
    <td style="border:1px solid #f59e0b;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Historical data package (Stage AV1)</li>
        <li>Industry growth assumptions (sector-specific benchmarks)</li>
        <li>Macro variables: Fed funds rate, DXY, commodity prices</li>
        <li>Management guidance from earnings call transcripts</li>
        <li>CapEx plans from 10-K and investor day notes</li>
      </ul>
    </td>
    <td style="border:1px solid var(--brand-primary);">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>S&P Capital IQ: Pre-built model templates with auto-populating data feeds</li>
        <li>FactSet: Normalized historical data exports for model population</li>
        <li>Bloomberg: Multi-year normalized financial data exports (standardized across companies)</li>
      </ul>
    </td>
    <td style="border:1px solid #2e7d32;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Integrated 3-statement model: IS → B/S → CFS dynamically linked</li>
        <li>5-year revenue forecast (volume × price, never a single growth rate)</li>
        <li>EBITDA / EBIT / FCF projections with margin assumptions stated explicitly</li>
        <li>ROIC / WACC calculation</li>
        <li>Working capital + CapEx schedules</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td colspan="3" style="border:1px solid #1565c0;background:#e3f2fd;">
      <strong style="color:#1565c0;">FREE ALTERNATIVES:</strong>
      <span style="font-size:0.82em;">
        Microsoft Excel or Google Sheets — the model IS the skill, the tool is just the container &nbsp;|&nbsp;
        <strong>Damodaran datasets</strong> (pages.stern.nyu.edu/~adamodar): industry betas, equity risk premia, margins by sector, updated annually — completely free &nbsp;|&nbsp;
        SEC EDGAR XBRL data for structured financial history
      </span>
    </td>
  </tr>
</table>

---

<!-- SLIDE 11: THREE STATEMENTS LINKED -->

# The Three-Statement Model: One Linked System

<table class="layout-3col" style="font-size:21px;">
  <tr>
    <th>Income Statement</th>
    <th>Balance Sheet</th>
    <th>Cash Flow Statement</th>
  </tr>
  <tr>
    <td style="border:1px solid var(--border-light);">
      Records revenues earned and costs incurred over a reporting period.<br><br>
      <strong>Critical:</strong> Accounting profit ≠ cash. Revenue gets booked before cash arrives; costs get capitalized as assets. A company can post strong net income while consuming cash at speed. <em>Penman (2013, McGraw-Hill)</em> calls the income statement the least reliable of the three.
    </td>
    <td style="border:1px solid var(--border-light);">
      Assets = Liabilities + Equity. Holds at all times without exception.<br><br>
      <strong>Red flag rule:</strong> If a model balances only because of a manual plug, the model contains an error. Find it. A properly constructed model balances automatically — the cash line in the balance sheet equals the ending cash line in the CFS, always.
    </td>
    <td style="border:1px solid var(--border-light);">
      Eliminates the gap between accounting profit and economic reality.<br><br>
      <strong>Operating:</strong> cash from the core business<br>
      <strong>Investing:</strong> CapEx and asset disposals<br>
      <strong>Financing:</strong> debt raised/repaid, equity issued/bought back<br><br>
      Strong net income + deeply negative operating cash flows = accounting quality problem.
    </td>
  </tr>
</table>

<div class="callout" style="margin-top:18px;font-size:0.85em;">
<div class="callout-title">Why FCF is the Number That Cannot Be Fabricated Indefinitely</div>
FCF = Operating Cash Flow − CapEx. The income statement can hide problems for several quarters. The cash flow statement cannot do so indefinitely. High net income with near-zero FCF signals either structural capital intensity or aggressive revenue recognition — both destroy shareholder value on the same timeline.
</div>

---

<!-- SLIDE 12: KEY FINANCIAL METRICS -->

# Core Financial Diagnostics: The Survival Screen

<table style="font-size:0.78em;">
  <tr>
    <th>Metric</th>
    <th>Formula</th>
    <th>US Threshold / Context</th>
    <th>Why It Matters</th>
  </tr>
  <tr>
    <td><strong>Net Debt / EBITDA</strong></td>
    <td>(Total Debt − Cash) / EBITDA</td>
    <td>Red flag above 3.0x for most sectors; regulated utilities can carry higher</td>
    <td>Years of full EBITDA required to retire net debt at zero taxes, zero CapEx</td>
  </tr>
  <tr>
    <td><strong>Interest Coverage</strong></td>
    <td>EBIT / Interest Expense</td>
    <td>Below 2.5x: financial stress approaching. Below 1.5x: covenant risk is real</td>
    <td>Below 2.5x, the company absorbs more than 40 cents of every operating dollar as interest</td>
  </tr>
  <tr>
    <td><strong>Cash Conversion Cycle</strong></td>
    <td>DIO + DSO − DPO</td>
    <td>Negative CCC (Amazon, Costco) is a structural competitive advantage</td>
    <td>Company collects from customers before paying suppliers — self-funds working capital</td>
  </tr>
  <tr>
    <td><strong>ROIC vs. WACC</strong></td>
    <td>NOPAT / Invested Capital vs. blended cost of capital</td>
    <td>ROIC > WACC = value creation. ROIC < WACC = value destruction regardless of revenue growth</td>
    <td><em>Koller, Goedhart & Wessels (McKinsey, 2020)</em>: growth without ROIC > WACC makes the company larger and poorer simultaneously</td>
  </tr>
</table>

---

<!-- SLIDE 13: STAGE 6 — VALUATION -->
<!-- _class: section-divider -->

# Stage 6
## Scenario Analysis & Valuation

---

# Stage 6 — Scenario Analysis & Valuation
*Derive the 12-month target price from three explicit cases — a single base case is not analysis*

<table class="layout-3col" style="font-size:20px;">
  <tr>
    <th style="background:#f59e0b;color:white;padding:10px;">INPUTS</th>
    <th style="background:var(--brand-primary);color:white;padding:10px;">PAID TOOLS</th>
    <th style="background:#2e7d32;color:white;padding:10px;">OUTPUTS</th>
  </tr>
  <tr>
    <td style="border:1px solid #f59e0b;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Financial model from Stage 5</li>
        <li>Comparable company universe (6–10 genuine peers)</li>
        <li>Current sector trading multiples (NTM EV/EBITDA, P/E, P/B)</li>
        <li>WACC inputs: US Treasury risk-free rate, Damodaran ERP, company beta</li>
      </ul>
    </td>
    <td style="border:1px solid var(--brand-primary);">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Bloomberg: Peer multiple data at NTM and LTM levels</li>
        <li>S&P Capital IQ: Comparable company comp sets, M&A transaction comps</li>
        <li>FactSet: Consensus NTM estimates for peer companies</li>
      </ul>
    </td>
    <td style="border:1px solid #2e7d32;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>DCF-derived intrinsic value (5yr explicit + terminal value)</li>
        <li>Peer multiple comp table (EV/EBITDA or P/E × NTM estimates)</li>
        <li>Weighted 12-month target price (60% DCF / 40% peer multiples)</li>
        <li>Bear / Base / Bull scenario table with numbered explicit assumptions</li>
        <li>WACC vs. terminal growth sensitivity matrix (mandatory)</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td colspan="3" style="border:1px solid #1565c0;background:#e3f2fd;">
      <strong style="color:#1565c0;">FREE ALTERNATIVES:</strong>
      <span style="font-size:0.82em;">
        <strong>Damodaran datasets</strong>: sector EV/EBITDA, P/E multiples, betas, ERP — updated January each year, completely free &nbsp;|&nbsp;
        Yahoo Finance: peer EV, market cap, trailing and forward ratios &nbsp;|&nbsp;
        Macrotrends for 15yr historical multiple ranges by company
      </span>
    </td>
  </tr>
</table>

---

<!-- SLIDE 14: DCF MECHANICS -->

# DCF + Peer Multiples: The Two-Method Target Price

<table class="layout-2col" style="font-size:22px;">
  <tr>
    <th>Discounted Cash Flow (DCF)</th>
    <th>Relative Valuation</th>
  </tr>
  <tr>
    <td>
      <code style="font-size:0.75em;background:#f5f5f5;padding:8px;display:block;border-radius:4px;color:#8b0000;">
        DCF EV = Σ [FCFt / (1 + WACC)^t] + TV / (1 + WACC)^n<br>
        TV = FCFn × (1 + g) / (WACC − g)
      </code>
      <br>
      Terminal growth <em>g</em>: US = <strong>2–3%</strong> (nominal GDP trend)<br><br>
      Terminal value typically represents 60–80% of total DCF output. A 50bps move in WACC or <em>g</em> produces a dramatically different target price. Always publish a WACC / terminal growth sensitivity table alongside the base case.
    </td>
    <td>
      Identify 6–10 genuinely comparable peers — same growth profiles, capital structures, and geographic exposure.<br><br>
      Do not value a high-growth US SaaS company at the P/E multiple of a mature enterprise software vendor. The growth rate differential alone makes the comparison indefensible.<br><br>
      Pull NTM multiples, compute the median, apply to the subject company's NTM projected metric.
    </td>
  </tr>
</table>

<div class="callout" style="margin-top:20px;font-size:0.88em;">
<div class="callout-title">The Combined Target Price</div>
<strong>Target Price = (60% × DCF Value) + (40% × Peer Multiple Value)</strong><br>
For mature, cash-generative companies in stable sectors, DCF should carry more weight. For early-stage, high-growth companies where near-term cash flows are speculative and the terminal value drives almost everything, peer multiples anchor the valuation more reliably.
</div>

---

<!-- SLIDE 15: SECTOR VALUATION FRAMEWORKS -->

# Sector Valuation: One Framework Fails Everything

| Sector | Primary Multiple | Why This Multiple, Not P/E | Critical Non-GAAP Metrics |
|---|---|---|---|
| **Technology / SaaS** | EV / Forward NTM Revenue | Profitability lags growth by years; revenue is the leading indicator | NRR (>110%), LTV/CAC (>3x), Rule of 40 |
| **Banking / Financials** | Price-to-Book, P/E | Debt is operational raw material — EV is meaningless for banks | NIM, CET1 (>12%), NCO%, PCR (>70%) |
| **Energy / Oil & Gas** | EV/EBITDAX, EV/BOE | Normalizes for exploration accounting method differences | RRR (>100%), Lifting Cost/barrel, GRM |
| **Healthcare / Pharma** | Risk-Adjusted NPV, SOTP | Binary pipeline outcomes require probability weighting | Phase III count, Patent expiry calendar |
| **Retail / Consumer** | EV/EBITDA, P/E | Store economics are the operational driver | SSSG, GMV, Inventory Turnover |
| **Industrials / Capex** | EV/EBITDA, P/E | Capital cycle visibility drives the multiple | Order Book, Capacity Utilization, ROCE |
| **Real Estate (REITs)** | Price/FFO, Dividend Yield | Depreciation distorts net income; FFO is the cash proxy | Occupancy Rate, Cap Rate, NAV/unit |

<div class="footnote">* Using a single valuation multiple across all industries is one of the most consequential errors a junior analyst makes. A retail bank and a SaaS company share no meaningful financial architecture.</div>

---

<!-- SLIDE 16: SECTOR DEEP DIVES -->

# Sector Mechanics That Kill Analysts Who Ignore Them

<table class="layout-2col" style="font-size:22px;">
  <tr>
    <th>SaaS / Technology</th>
    <th>Banking / Financials</th>
  </tr>
  <tr>
    <td>
      Customer acquisition costs hit the income statement immediately. The resulting subscription revenue materialises over 3–5 year contract periods. Penalising on P/E is analytically incorrect — the earnings figure is distorted by design.<br><br>
      <strong>Net Revenue Retention:</strong> Above 110% = existing customers expand faster than some churn. Below 100% = the company is running in place — new customer acquisitions are merely replacing those leaving.<br><br>
      <strong>Rule of 40</strong> (<em>a16z.com</em>): Revenue growth % + EBITDA margin % > 40. A company growing 10% with 15% margins scores 25 — the growth engine or cost structure has a problem.
    </td>
    <td>
      Never apply Enterprise Value to a bank. Debt is the raw material. There is no separating "operational" from "financing" debt in a bank's capital structure.<br><br>
      <strong>Net Interest Margin:</strong> 50bps NIM compression on a bank with $500B of earning assets destroys $2.5B of annual income. Track NIM trajectory first, every rate cycle.<br><br>
      <strong>NCO% (Net Charge-Off Rate):</strong> Loans written off as uncollectible as a % of the loan book. Rising NCO over three consecutive quarters presages credit losses that hit the income statement ahead.<br><br>
      <strong>PCR above 70%</strong> means the bank has already absorbed >70% of its bad loans as provisions — income statement is cushioned when those loans default fully.
    </td>
  </tr>
</table>

---

<!-- SLIDE 17: STAGE 7 — WRITING THE THESIS -->

# Stage 7 — Writing the Investment Thesis
*Translate model outputs into a clear, unambiguous client recommendation — Page 1 must stand alone*

<table class="layout-3col" style="font-size:20px;">
  <tr>
    <th style="background:#f59e0b;color:white;padding:10px;">INPUTS</th>
    <th style="background:var(--brand-primary);color:white;padding:10px;">PAID TOOLS</th>
    <th style="background:#2e7d32;color:white;padding:10px;">OUTPUTS</th>
  </tr>
  <tr>
    <td style="border:1px solid #f59e0b;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>All outputs from Stages RS1–AV3</li>
        <li>Prior 10-K, 10-Q, earnings call transcripts (last 8 quarters)</li>
        <li>Internal research note templates</li>
        <li>Risk factor checklist: what specific events break the thesis</li>
      </ul>
    </td>
    <td style="border:1px solid var(--brand-primary);">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Bloomberg Research Terminal — institutional formatting and distribution prep</li>
        <li>Internal research management systems (Visible Alpha, proprietary platforms)</li>
        <li>Microsoft Word + Excel — note writing + model attachment</li>
      </ul>
    </td>
    <td style="border:1px solid #2e7d32;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Page 1: Investment thesis + Rating + 12-month target price (standalone)</li>
        <li>Financial summary table (3yr forecast, multiples at current + TP)</li>
        <li>Business model section (how the company actually makes money)</li>
        <li>Earnings review: actual vs. consensus, line by line</li>
        <li>Quantified risk factors — specific events + P&L impact, never "macro risk"</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td colspan="3" style="border:1px solid #1565c0;background:#e3f2fd;">
      <strong style="color:#1565c0;">FREE ALTERNATIVES:</strong>
      <span style="font-size:0.82em;">
        Google Docs for draft and collaborate &nbsp;|&nbsp;
        Google Sheets for financial summary tables &nbsp;|&nbsp;
        PDF export for final distribution format &nbsp;|&nbsp;
        Company IR documents to verify all factual claims before publishing
      </span>
    </td>
  </tr>
</table>

---

<!-- SLIDE 18: REPORT ANATOMY -->

# Anatomy of an Institutional Research Report

<table class="layout-boxed" style="font-size:22px;">
  <tr>
    <td>
      <strong style="color:var(--brand-primary);">Page 1 — Investment Thesis + Rating + Target Price</strong><br>
      <span style="font-size:0.85em;">Why is the market wrong? What closes the gap? Rating and 12-month TP. Institutional clients read this alone and make allocation decisions from it. Three questions, answered without hedging.</span>
    </td>
    <td>
      <strong style="color:var(--brand-primary);">Page 2 — Financial Summary Table</strong><br>
      <span style="font-size:0.85em;">Revenue, EBITDA, EPS, FCF across FY-1, FY0, FY+1, FY+2. Key multiples at current price AND at target price. This table is what the portfolio manager screenshots and pastes into their investment committee deck.</span>
    </td>
  </tr>
  <tr>
    <td>
      <strong style="color:#1565c0;">Pages 3–5 — Business Model & Competitive Position</strong><br>
      <span style="font-size:0.85em;">How the company makes money. Where pricing power sits. What prevents competitors from replicating it. Not a company history — an economic structure analysis.</span>
    </td>
    <td>
      <strong style="color:#1565c0;">Pages 6–8 — Earnings Review: Actual vs. Consensus</strong><br>
      <span style="font-size:0.85em;">Line-by-line: revenue, margins, FCF vs. Bloomberg / FactSet consensus. Structural beats separated from one-time items. Sandbag detection is the skill here.</span>
    </td>
  </tr>
  <tr>
    <td>
      <strong style="color:#2e7d32;">Pages 9–15 — Three-Scenario Financial Model</strong><br>
      <span style="font-size:0.85em;">Bear, Base, and Bull with numbered, explicit assumptions. WACC vs. terminal growth sensitivity matrix. Non-optional — a single base case communicates almost nothing about risk.</span>
    </td>
    <td>
      <strong style="color:var(--brand-secondary);">Pages 16+ — Risk Factors (Specific and Quantified)</strong><br>
      <span style="font-size:0.85em;">"A 75bps Fed hiking cycle compresses NIM 30bps, reducing FY26E EPS 18%, and contracts the P/B target from 2.2x to 1.7x — eliminating the upside at current prices." That is a risk factor. "Macroeconomic deterioration" is not.</span>
    </td>
  </tr>
</table>

---

<!-- SLIDE 19: STAGE 8 — COMPLIANCE -->

# Stage 8 — Internal Review & Compliance Clearance
*Every number verified. Every rating aligned with the model. Every conflict disclosed.*

<table class="layout-3col" style="font-size:20px;">
  <tr>
    <th style="background:#f59e0b;color:white;padding:10px;">INPUTS</th>
    <th style="background:var(--brand-primary);color:white;padding:10px;">REVIEW PROCESS</th>
    <th style="background:#2e7d32;color:white;padding:10px;">OUTPUTS</th>
  </tr>
  <tr>
    <td style="border:1px solid #f59e0b;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Draft research report (Stage 7)</li>
        <li>Supporting financial model</li>
        <li>Compliance pre-clearance checklist (MNPI declaration, conflict check)</li>
        <li>SEC Regulation AC (US) — Analyst Certification</li>
        <li>SEC Regulation FD (Fair Disclosure)</li>
        <li>FINRA Rule 2241 (Equity Research)</li>
      </ul>
    </td>
    <td style="border:1px solid var(--brand-primary);">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Internal compliance management systems (vary by institution)</li>
        <li>Senior analyst challenge session: every material assumption in the model gets questioned</li>
        <li>Legal counsel: activist positions, regulatory investigations</li>
        <li>Ratings aligned with model output — compliance reviews and returns any conflict for reconciliation</li>
      </ul>
    </td>
    <td style="border:1px solid #2e7d32;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Compliance-cleared final report with signed analyst disclosures</li>
        <li>Rating confirmed to match model output — no exceptions</li>
        <li>MNPI declarations signed: no non-public information in the note</li>
        <li>Conflict of interest disclosures appended and finalized</li>
        <li>Investment banking relationship disclosures (required under FINRA 2241)</li>
      </ul>
    </td>
  </tr>
</table>

<div class="info-box" style="margin-top:10px;font-size:0.78em;">
That review process returning a conflicting report is the system working correctly, not bureaucratic obstruction.
</div>

---

<!-- SLIDE 20: THE RATING SYSTEM -->

# The Rating: Making the Call Without Hedging

| Rating | Definition | Return Threshold |
|---|---|---|
| **BUY / OVERWEIGHT** | Expected total return (price appreciation + dividend yield) exceeds the sector hurdle rate or S&P 500 benchmark by more than 15% over 12 months | >15% above hurdle |
| **HOLD / NEUTRAL** | Expected return within ±5% of the benchmark. The stock is fairly priced; capital here generates an opportunity cost vs. better-rated alternatives in the coverage universe | ±5% of index |
| **SELL / UNDERWEIGHT** | Expected return is negative, or underperforms the hurdle rate by more than 15%. Structural deterioration or fundamental overvaluation is the driver | >15% below hurdle |

<div class="warning-box" style="margin-top:20px;font-size:0.85em;">
<strong>The crowding problem:</strong> When 85–90% of analysts carry a Buy rating on a stock (check Bloomberg ANR), that crowding is itself information — nearly all the optimism is already priced in. The most contrarian call an analyst can publish is sometimes a Hold. A well-reasoned Sell on a consensus Buy is how research reputations get made or destroyed.
</div>

---

<!-- SLIDE 21: STAGE 9 — PUBLISH & MONITOR -->

# Stage 9 — Publish, Distribute & Monitor Ongoing
*Publishing the note opens a coverage relationship — the quarterly cycle never stops*

<table class="layout-3col" style="font-size:20px;">
  <tr>
    <th style="background:#f59e0b;color:white;padding:10px;">INPUTS</th>
    <th style="background:var(--brand-primary);color:white;padding:10px;">PAID TOOLS</th>
    <th style="background:#2e7d32;color:white;padding:10px;">OUTPUTS</th>
  </tr>
  <tr>
    <td style="border:1px solid #f59e0b;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Final compliance-cleared report</li>
        <li>Institutional client distribution list (by tier and mandate)</li>
        <li>Quarterly earnings results (the continuous cycle input)</li>
        <li>Competitor analyst note alerts (consensus estimate revision tracking)</li>
        <li>SEC 8-K, 13F, and DEF 14A filings on covered tickers</li>
      </ul>
    </td>
    <td style="border:1px solid var(--brand-primary);">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Bloomberg Research Distribution (BRL) — publish directly to terminal subscribers</li>
        <li>Refinitiv Eikon Research — secondary distribution channel</li>
        <li>Internal CRM — client meeting tracking, coverage attribution, feedback logs</li>
      </ul>
    </td>
    <td style="border:1px solid #2e7d32;">
      <ul style="font-size:0.85em;margin:0;padding-left:18px;">
        <li>Published research note (distributed to institutional clients)</li>
        <li>Quarterly model updates (24–48 hr after each earnings release)</li>
        <li>Rating revision notes (when thesis materially changes)</li>
        <li>Annual model reset (after 10-K publication)</li>
        <li>Client meeting presentations (defending and updating the thesis)</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td colspan="3" style="border:1px solid #1565c0;background:#e3f2fd;">
      <strong style="color:#1565c0;">FREE ALTERNATIVES:</strong>
      <span style="font-size:0.82em;">
        Email distribution for independent and boutique analysts &nbsp;|&nbsp;
        Substack / Seeking Alpha for independent research publication &nbsp;|&nbsp;
        SEC EDGAR email alerts for 8-K and earnings filing notifications &nbsp;|&nbsp;
        LinkedIn for registered analysts posting research summaries publicly
      </span>
    </td>
  </tr>
</table>

---

<!-- SLIDE 22: THE INSTITUTIONAL PAID TOOLKIT -->

# The Institutional Paid Toolkit

<table class="layout-boxed" style="font-size:22px;">
  <tr>
    <td>
      <strong>Bloomberg Terminal</strong> <em style="font-size:0.8em;color:#666;">~$25,000–30,000/yr per seat</em><br>
      <ul style="font-size:0.82em;margin-top:8px;padding-left:18px;">
        <li><code>EE</code>: consensus earnings estimates from all covering analysts</li>
        <li><code>ANR</code>: all analyst ratings + target prices + recommendation distribution</li>
        <li><code>DDIS</code>: institutional ownership and fund position changes (13F-derived)</li>
        <li><code>WIRP</code>: market-implied Fed rate expectations via futures</li>
        <li>Real-time: yields, FX, equity prices, CDS spreads, derivatives</li>
      </ul>
    </td>
    <td>
      <strong>S&P Capital IQ</strong> <em style="font-size:0.8em;color:#666;">~$15,000–20,000/yr</em><br>
      <ul style="font-size:0.82em;margin-top:8px;padding-left:18px;">
        <li>10+ year normalized financial statement history</li>
        <li>Notes-to-accounts parsing (catches items aggregators miss)</li>
        <li>Multi-factor cross-company financial screeners</li>
        <li>Pre-built model templates with auto-populating data feeds</li>
        <li>M&A comparable transaction database</li>
      </ul>
    </td>
  </tr>
  <tr>
    <td>
      <strong>FactSet</strong> <em style="font-size:0.8em;color:#666;">~$12,000–20,000/yr</em><br>
      <ul style="font-size:0.82em;margin-top:8px;padding-left:18px;">
        <li>Consensus NTM estimate history (backtesting estimate accuracy)</li>
        <li>Peer group analysis and factor screening</li>
        <li>Portfolio attribution and performance analytics</li>
        <li>Alpha factor research and quantitative tools</li>
      </ul>
    </td>
    <td>
      <strong>Expert Networks (GLG, AlphaSights, Guidepoint)</strong> <em style="font-size:0.8em;color:#666;">$500–1,500/hr</em><br>
      <ul style="font-size:0.82em;margin-top:8px;padding-left:18px;">
        <li>Former executive interviews (verified ex-CFO, ex-COO of target company)</li>
        <li>Supplier and customer channel checks</li>
        <li>Industry specialist consultations</li>
        <li>Operational reality verification before publishing thesis</li>
      </ul>
    </td>
  </tr>
</table>

---

<!-- SLIDE 23: FREE ALTERNATIVES TABLE -->

# The Zero-Budget Research Stack

| Research Need | Paid Tool | Free Alternative | Quality Gap |
|---|---|---|---|
| **Macro Data** | Bloomberg Terminal | FRED + Fed H.8 + BLS.gov + Trading Economics | Minimal — free sources equally accurate, slower to navigate |
| **Company Screening** | Bloomberg EQS / Capital IQ | Finviz.com + Macrotrends + SEC EDGAR XBRL | Low — Finviz is genuinely excellent for US markets |
| **Primary Filings** | Capital IQ filing aggregation | SEC EDGAR (sec.gov/edgar) — 10-K, 10-Q, 8-K | Zero — filings are free by law. Aggregators only save time. |
| **Historical Financials** | Capital IQ / FactSet | Macrotrends + SEC EDGAR XBRL + Company 10-Ks | Low — requires manual entry; the numbers are identical |
| **Peer Valuations** | Bloomberg / Capital IQ comp sets | Damodaran datasets + Yahoo Finance | Low — Damodaran publishes sector multiples and betas annually, free |
| **Financial Modeling** | Capital IQ templates / FactSet feeds | Microsoft Excel or Google Sheets | Zero — the model is built by the analyst; the tool is just the container |
| **Expert Intelligence** | GLG / AlphaSights ($500–1,500/hr) | LinkedIn outreach + IR call access + industry events | **Significant — expert calls are genuinely differentiating. This gap is real.** |

---

<!-- SLIDE 24: ALTERNATIVE DATA -->

# Alternative Data: Where Research Differentiation Now Lives

Reading the same 10-K and modeling consensus numbers produces research indistinguishable from the 15 other analysts covering the same stock. Alternative data is where differentiation originates.

<table class="layout-2col" style="font-size:22px;">
  <tr>
    <th>Data Type & Source</th>
    <th>What It Tells You</th>
  </tr>
  <tr>
    <td>
      <strong>E-commerce pricing scrapers</strong><br>
      Python / Beautiful Soup / Scrapy tracking daily prices on Amazon US
    </td>
    <td>Real-time read on promotional intensity and pricing power weeks before the earnings call reveals it in the margin line</td>
  </tr>
  <tr>
    <td>
      <strong>App store trackers</strong><br>
      Sensor Tower, data.ai — daily download rankings and revenue estimates
    </td>
    <td>Engagement velocity for mobile-first businesses; detects inflection points months before quarterly filings</td>
  </tr>
  <tr>
    <td>
      <strong>Web traffic analytics</strong><br>
      SimilarWeb — monthly active users and traffic trends
    </td>
    <td>Leading demand indicator for e-commerce and fintech; tracks market share shifts between competitors in real time</td>
  </tr>
  <tr>
    <td>
      <strong>Satellite imagery</strong><br>
      Factory parking lot density, retail car park occupancy, shipping yard activity
    </td>
    <td>Capacity utilization and foot traffic proxy before official data appears — standard input at top US hedge funds</td>
  </tr>
</table>

---

<!-- SLIDE 25: ONGOING COVERAGE -->

# The Ongoing Coverage Loop

<div class="step">
  <div class="step-number">1</div>
  <div class="step-content">
    <strong>Quarterly Earnings Reviews</strong><br>
    Within 24–48 hours of results, release an updated note comparing actual vs. model estimates line-by-line. Revise forward estimates explicitly. If the story has changed materially, revise the rating to match — do not wait for the next scheduled review cycle.
  </div>
</div>

<div class="step">
  <div class="step-number">2</div>
  <div class="step-content">
    <strong>Catalyst Monitoring</strong><br>
    8-K announcing a material contract win, an FTC enforcement action, a supply chain disruption at a key input supplier — each requires immediate assessment. Material developments warrant a client note within hours, not the next morning.
  </div>
</div>

<div class="step">
  <div class="step-number">3</div>
  <div class="step-content">
    <strong>Annual Model Reset</strong><br>
    After each 10-K publishes, rebuild the three-year forward model from reported actuals. Do not roll forward stale assumptions. Reset from the current base. Every rolled-forward assumption that was wrong compounds its error into the next year's model.
  </div>
</div>

<div class="step">
  <div class="step-number">4</div>
  <div class="step-content">
    <strong>Institutional 13F Monitoring</strong><br>
    SEC 13F filings (quarterly, filed within 45 days of quarter-end) reveal which institutional funds are building or cutting positions in covered stocks. Conviction-level position building by long-only funds is a thesis confirmation signal. Mass exits precede price dislocations.
  </div>
</div>

---

<!-- SLIDE 26: CLOSING -->
<!-- _class: title-slide -->

# Thank You

## The market is a voting machine short-term and a weighing machine long-term. Research does the weighing.
### — Benjamin Graham & David Dodd, *Security Analysis* (1934)

<div style="margin-top:60px;font-size:0.85em;color:rgba(255,255,255,0.85);">

**Ankur Vatsa**

[Email](mailto:ankur.vatsa@gmail.com) &nbsp;|&nbsp; [LinkedIn](https://www.linkedin.com/in/ankurvatsa/) &nbsp;|&nbsp; [Medium](https://medium.com/@ankur.vatsa)

</div>
