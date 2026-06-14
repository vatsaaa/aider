"""FastAPI health, observability, and dashboard endpoints for the pipeline.

Provides lightweight service checks plus a run-level observability snapshot
and HTML dashboard that surface pipeline status, DLQ pressure, and alerting
signals without requiring the full pipeline to be functional.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine, inspect, text
import redis
import os

from core.config import settings

app = FastAPI()


def _table_exists(engine, table_name: str) -> bool:
        try:
                return inspect(engine).has_table(table_name)
        except Exception:
                return False


def _parse_dt(value: Any) -> datetime | None:
        if value is None:
                return None
        if isinstance(value, datetime):
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
                return None


def _query_rows(engine, sql: str, params: dict[str, Any] | None = None) -> List[dict[str, Any]]:
        with engine.connect() as conn:
                rows = conn.execute(text(sql), params or {}).mappings().all()
        return [dict(row) for row in rows]


def _build_observability_snapshot(dsn: str) -> Dict[str, Any]:
        snapshot: Dict[str, Any] = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "stale_threshold_minutes": settings.RUN_ALERT_STALE_MINUTES,
                "pipeline": {"total": 0, "complete": 0, "failed": 0, "started": 0, "running": 0},
                "recent_runs": [],
                "stale_runs": [],
                "dlq": {"total": 0, "recent": []},
                "alerts": {"failed": 0, "recent": []},
        }

        engine = create_engine(dsn)

        if _table_exists(engine, "pipeline_runs"):
                counts = _query_rows(
                        engine,
                        "SELECT status, COUNT(*) AS count FROM pipeline_runs GROUP BY status",
                )
                snapshot["pipeline"]["total"] = sum(int(row.get("count") or 0) for row in counts)
                for row in counts:
                        status = str(row.get("status") or "").lower()
                        if status in snapshot["pipeline"]:
                                snapshot["pipeline"][status] = int(row.get("count") or 0)

                snapshot["recent_runs"] = _query_rows(
                        engine,
                        "SELECT run_id, ticker, trigger_type, status, started_at, completed_at, git_commit_hash "
                        "FROM pipeline_runs ORDER BY COALESCE(completed_at, started_at) DESC LIMIT 12",
                )

                stale_sql = (
                        "SELECT run_id, ticker, trigger_type, status, started_at, completed_at "
                        "FROM pipeline_runs WHERE status IN ('started', 'running')"
                )
                stale_candidates = _query_rows(engine, stale_sql)
                stale_runs: List[dict[str, Any]] = []
                cutoff_minutes = int(settings.RUN_ALERT_STALE_MINUTES)
                for row in stale_candidates:
                        started_at = _parse_dt(row.get("started_at"))
                        if started_at is None:
                                continue
                        age_minutes = (datetime.now(timezone.utc) - started_at).total_seconds() / 60.0
                        if age_minutes >= cutoff_minutes:
                                row["age_minutes"] = round(age_minutes, 1)
                                stale_runs.append(row)
                snapshot["stale_runs"] = stale_runs[:20]

        if _table_exists(engine, "dlq_entries"):
                snapshot["dlq"]["total"] = len(_query_rows(engine, "SELECT id FROM dlq_entries"))
                snapshot["dlq"]["recent"] = _query_rows(
                        engine,
                        "SELECT id, run_id, stream, message_id, reason, created_at FROM dlq_entries ORDER BY created_at DESC, id DESC LIMIT 12",
                )

        if _table_exists(engine, "alerts_failures"):
                snapshot["alerts"]["failed"] = len(_query_rows(engine, "SELECT id FROM alerts_failures"))
                snapshot["alerts"]["recent"] = _query_rows(
                        engine,
                        "SELECT id, channel, error_message, failed_at FROM alerts_failures ORDER BY failed_at DESC, id DESC LIMIT 12",
                )

        return snapshot


def _render_dashboard(snapshot: Dict[str, Any]) -> str:
        def esc(value: Any) -> str:
                import html

                return html.escape("" if value is None else str(value))

        cards = [
                ("Total Runs", snapshot["pipeline"]["total"], "All pipeline executions"),
                ("Completed", snapshot["pipeline"]["complete"], "Successful runs"),
                ("Failed", snapshot["pipeline"]["failed"], "Runs that hit DLQ or terminal failure"),
                ("Stale", len(snapshot["stale_runs"]), f"Runs older than {snapshot['stale_threshold_minutes']} min"),
                ("DLQ Entries", snapshot["dlq"]["total"], "Dead-letter pressure"),
                ("Alert Failures", snapshot["alerts"]["failed"], "Failed Slack/email attempts"),
        ]

        def table_row(cells: List[Any]) -> str:
                return "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in cells) + "</tr>"

        recent_rows = "".join(
                table_row([
                        row.get("run_id"),
                        row.get("ticker"),
                        row.get("trigger_type"),
                        row.get("status"),
                        row.get("started_at"),
                        row.get("completed_at"),
                ])
                for row in snapshot["recent_runs"]
        ) or "<tr><td colspan='6'>No runs yet</td></tr>"

        stale_rows = "".join(
                table_row([
                        row.get("run_id"),
                        row.get("ticker"),
                        row.get("trigger_type"),
                        row.get("status"),
                        row.get("age_minutes"),
                ])
                for row in snapshot["stale_runs"]
        ) or "<tr><td colspan='5'>No stale runs</td></tr>"

        dlq_rows = "".join(
                table_row([row.get("id"), row.get("run_id"), row.get("stream"), row.get("reason"), row.get("created_at")])
                for row in snapshot["dlq"]["recent"]
        ) or "<tr><td colspan='5'>No DLQ entries</td></tr>"

        alert_rows = "".join(
                table_row([row.get("id"), row.get("channel"), row.get("error_message"), row.get("failed_at")])
                for row in snapshot["alerts"]["recent"]
        ) or "<tr><td colspan='4'>No alert failures</td></tr>"

        card_html = "".join(
                f"<section class='card'><div class='kpi'>{esc(value)}</div><div class='label'>{esc(title)}</div><div class='hint'>{esc(hint)}</div></section>"
                for title, value, hint in cards
        )

        return f"""<!doctype html>
<html lang='en'>
<head>
    <meta charset='utf-8'>
    <meta name='viewport' content='width=device-width, initial-scale=1'>
    <title>Pipeline Observability</title>
    <style>
        :root {{
            --bg: #08111f;
            --panel: rgba(14, 24, 43, 0.92);
            --panel-2: rgba(17, 29, 51, 0.95);
            --text: #eef3ff;
            --muted: #a9b5cf;
            --accent: #7dd3fc;
            --accent-2: #a78bfa;
            --danger: #fb7185;
            --border: rgba(148, 163, 184, 0.18);
        }}
        body {{
            margin: 0;
            font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background:
                radial-gradient(circle at top left, rgba(125, 211, 252, 0.14), transparent 30%),
                radial-gradient(circle at 90% 10%, rgba(167, 139, 250, 0.16), transparent 28%),
                var(--bg);
            color: var(--text);
        }}
        .wrap {{ max-width: 1400px; margin: 0 auto; padding: 28px 22px 48px; }}
        .hero {{ display: flex; justify-content: space-between; gap: 24px; align-items: end; margin-bottom: 22px; }}
        .eyebrow {{ text-transform: uppercase; letter-spacing: .18em; color: var(--accent); font-size: 11px; }}
        h1 {{ margin: 6px 0 0; font-size: clamp(30px, 4vw, 54px); line-height: 1.02; }}
        .sub {{ color: var(--muted); max-width: 70ch; margin-top: 8px; }}
        .updated {{ color: var(--muted); font-size: 14px; text-align: right; }}
        .grid {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 14px; margin: 22px 0; }}
        .card {{ background: linear-gradient(180deg, rgba(21, 34, 61, 0.95), rgba(10, 17, 30, 0.96)); border: 1px solid var(--border); border-radius: 18px; padding: 18px; box-shadow: 0 20px 60px rgba(0,0,0,.18); }}
        .kpi {{ font-size: 32px; font-weight: 700; line-height: 1; }}
        .label {{ margin-top: 10px; font-size: 14px; font-weight: 600; }}
        .hint {{ margin-top: 6px; color: var(--muted); font-size: 12px; }}
        .panel {{ background: var(--panel); border: 1px solid var(--border); border-radius: 18px; padding: 18px; margin-top: 16px; overflow: hidden; }}
        .panel h2 {{ margin: 0 0 14px; font-size: 20px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
        th, td {{ padding: 12px 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.14); text-align: left; vertical-align: top; }}
        th {{ color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
        tbody tr:hover {{ background: rgba(125, 211, 252, 0.04); }}
        .danger {{ color: var(--danger); }}
        .tag {{ display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 999px; background: rgba(125, 211, 252, 0.1); color: var(--accent); font-size: 12px; font-weight: 700; }}
        .two-col {{ display: grid; grid-template-columns: 1.2fr .8fr; gap: 16px; }}
        @media (max-width: 1100px) {{ .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .two-col {{ grid-template-columns: 1fr; }} }}
        @media (max-width: 720px) {{ .grid {{ grid-template-columns: 1fr; }} .hero {{ flex-direction: column; align-items: start; }} .updated {{ text-align: left; }} }}
    </style>
</head>
<body>
    <main class='wrap'>
        <div class='hero'>
            <div>
                <div class='eyebrow'>Run-level observability</div>
                <h1>Pipeline dashboard</h1>
                <p class='sub'>Live view of pipeline execution status, dead-letter pressure, stale run candidates, and alert delivery failures. Use this to spot the runs that need attention now.</p>
            </div>
            <div class='updated'>
                <div class='tag'>Updated</div>
                <div style='margin-top:8px'>{esc(snapshot['generated_at'])}</div>
            </div>
        </div>

        <section class='grid'>
            {card_html}
        </section>

        <section class='panel'>
            <h2>Recent runs</h2>
            <table>
                <thead><tr><th>Run</th><th>Ticker</th><th>Trigger</th><th>Status</th><th>Started</th><th>Completed</th></tr></thead>
                <tbody>{recent_rows}</tbody>
            </table>
        </section>

        <div class='two-col'>
            <section class='panel'>
                <h2>Stale runs</h2>
                <table>
                    <thead><tr><th>Run</th><th>Ticker</th><th>Trigger</th><th>Status</th><th>Age (min)</th></tr></thead>
                    <tbody>{stale_rows}</tbody>
                </table>
            </section>

            <section class='panel'>
                <h2>Alert delivery failures</h2>
                <table>
                    <thead><tr><th>ID</th><th>Channel</th><th>Error</th><th>Failed at</th></tr></thead>
                    <tbody>{alert_rows}</tbody>
                </table>
            </section>
        </div>

        <section class='panel'>
            <h2>DLQ</h2>
            <table>
                <thead><tr><th>ID</th><th>Run</th><th>Stream</th><th>Reason</th><th>Created</th></tr></thead>
                <tbody>{dlq_rows}</tbody>
            </table>
        </section>
    </main>
</body>
</html>"""


def _db_status(dsn: str) -> str:
    """Return 'ok' if a DB connection can be established, otherwise 'error'."""

    try:
        engine = create_engine(dsn)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


def _redis_status(url: str) -> str:
    """Return 'ok' if Redis is reachable, otherwise 'error'."""

    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=2)
        client.ping()
        return "ok"
    except Exception:
        return "error"


@app.get("/health")
def health() -> Dict[str, str]:
    """Health endpoint reporting service, redis and db connectivity."""

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    db_url = os.getenv("AIDER_DATABASE_URL", "sqlite:///:memory:")

    return {"status": "ok", "redis": _redis_status(redis_url), "db": _db_status(db_url)}


@app.get("/ready")
def ready() -> Dict[str, str]:
    """Readiness endpoint alias for simple probes."""

    return health()


@app.get("/api/observability")
def observability() -> Dict[str, Any]:
    """Return a JSON snapshot of run-level observability data."""

    db_url = os.getenv("AIDER_DATABASE_URL", "sqlite:///:memory:")
    return _build_observability_snapshot(db_url)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    """Render a lightweight observability dashboard."""

    db_url = os.getenv("AIDER_DATABASE_URL", "sqlite:///:memory:")
    snapshot = _build_observability_snapshot(db_url)
    return HTMLResponse(_render_dashboard(snapshot))


@app.get("/")
def index() -> HTMLResponse:
    """Alias the dashboard at the root for convenience."""

    return dashboard()
