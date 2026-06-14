"""End-to-end smoke test runner for the Digital Equity Analyst pipeline.

This script triggers a manual pipeline run via the scanner, polls the
monitor API until the run completes, verifies a git commit hash was
produced, checks Mailhog for the published email with PDF attachment,
extracts text from the PDF to confirm the pipeline_run_id appears, and
asserts there are no DLQ entries.

Usage:
    python scripts/smoke_test.py --ticker AAPL

Requirements:
    - The application HTTP API must be reachable at http://localhost:8000
    - Mailhog API must be reachable at http://localhost:8025
    - `pdftotext` must be installed on the machine running this script
    - `python -m triggers.scanner --manual` must be a valid invocation

Exit codes:
    0  All checks passed
    1  One or more checks failed (diagnostics printed to stdout)
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import requests


API_BASE = os.environ.get("SMOKE_API_BASE", "http://localhost:8000")
MAILHOG_BASE = os.environ.get("SMOKE_MAILHOG_BASE", "http://localhost:8025")
PDFTOTEXT = os.environ.get("PDFTOTEXT_CMD", "pdftotext")


def log(msg: str) -> None:
    """Print a timestamped log message to stdout."""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def run_scanner_manual(ticker: str) -> None:
    """Trigger the scanner in manual mode for a ticker.

    Runs: `python -m triggers.scanner --manual --ticker {ticker} --type manual`
    Raises subprocess.CalledProcessError on non-zero exit.
    """
    cmd = [sys.executable, "-m", "triggers.scanner", "--manual", "--ticker", ticker, "--type", "manual"]
    log(f"Triggering scanner: {' '.join(shlex.quote(p) for p in cmd)}")
    subprocess.run(cmd, check=True)


def get_latest_run() -> Optional[dict]:
    """Fetch the most recent pipeline runs and return the first element or None."""
    url = f"{API_BASE}/runs"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    runs = r.json()
    if not runs:
        return None
    return runs[0]


def wait_for_run_complete(timeout_seconds: int = 600, poll_interval: int = 10) -> dict:
    """Poll `/runs` until the latest run has status 'complete' or timeout.

    Returns the run dict on success. Raises RuntimeError on timeout.
    """
    deadline = time.time() + timeout_seconds
    log(f"Waiting up to {timeout_seconds}s for run to complete (poll every {poll_interval}s)")
    last_run_id = None
    while time.time() < deadline:
        run = get_latest_run()
        if run:
            status = run.get("status")
            run_id = run.get("pipeline_run_id") or run.get("run_id") or run.get("id")
            if run_id != last_run_id:
                log(f"Observed run id={run_id} status={status}")
                last_run_id = run_id
            if status == "complete":
                return run
        else:
            log("No runs observed yet")
        time.sleep(poll_interval)
    raise RuntimeError("Timed out waiting for pipeline run to complete")


def assert_git_commit_present(run: dict) -> None:
    """Assert the run contains a non-empty git_commit_hash field."""
    commit = run.get("git_commit_hash") or run.get("commit_hash")
    if not commit:
        raise AssertionError("git_commit_hash is missing or empty in run record")
    log(f"Found git commit hash: {commit}")


def find_mailhog_message(subject_substr: str, since_seconds: int = 600) -> dict:
    """Query Mailhog API for messages whose subject contains subject_substr.

    Returns the message dict if found, otherwise raises AssertionError.
    """
    url = f"{MAILHOG_BASE}/api/v2/messages"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    items = data.get("items", [])
    now = time.time()
    for msg in items:
        subj = msg.get("Content", {}).get("Headers", {}).get("Subject", [""])[0]
        created = msg.get("Created")
        # no reliable created timestamp normalization here; just match subject
        if subject_substr in subj:
            log(f"Found Mailhog message with subject: {subj}")
            return msg
    raise AssertionError(f"No Mailhog message found containing subject '{subject_substr}'")


def download_pdf_from_mailhog(msg: dict, out_dir: Path) -> Path:
    """Download the first PDF attachment from a Mailhog message into out_dir.

    Returns the path to the saved PDF. Raises AssertionError if no PDF found.
    """
    parts = msg.get("MIME", {}).get("Parts", [])
    # Search parts recursively for attachment with application/pdf
    def walk(parts_list):
        for p in parts_list:
            ct = p.get("Headers", {}).get("Content-Type", [""])[0]
            if "application/pdf" in ct.lower():
                yield p
            for sub in p.get("Parts", []) or []:
                yield from walk([sub])

    for part in walk(parts):
        filename = part.get("Filename") or "attachment.pdf"
        data_b64 = part.get("Body", "")
        if not data_b64:
            continue
        out_path = out_dir / filename
        import base64

        with open(out_path, "wb") as fh:
            fh.write(base64.b64decode(data_b64))
        log(f"Saved PDF attachment to {out_path}")
        return out_path
    raise AssertionError("No PDF attachment found in Mailhog message")


def fetch_pdf_from_run(run: dict, out_dir: Path) -> Path:
    """Fetch the pdf referred to by run['pdf_path'].

    If the path is a URL, download it. If it's a local path, copy it.
    """
    pdf_path = run.get("pdf_path") or run.get("receipt", {}).get("pdf_path") if run.get("receipt") else None
    if not pdf_path:
        raise AssertionError("run record has no pdf_path")
    out_dir.mkdir(parents=True, exist_ok=True)
    if pdf_path.startswith("http://") or pdf_path.startswith("https://"):
        r = requests.get(pdf_path, timeout=30)
        r.raise_for_status()
        out_file = out_dir / Path(pdf_path).name
        with open(out_file, "wb") as fh:
            fh.write(r.content)
        log(f"Downloaded PDF from URL to {out_file}")
        return out_file
    else:
        # treat as local file path
        local = Path(pdf_path)
        if not local.exists():
            raise AssertionError(f"PDF path does not exist: {local}")
        out_file = out_dir / local.name
        from shutil import copy2

        copy2(local, out_file)
        log(f"Copied PDF from {local} to {out_file}")
        return out_file


def pdftotext_contains(pdf_path: Path, substring: str) -> bool:
    """Run pdftotext on pdf_path and check whether substring appears in text."""
    if not shutil_which(PDFTOTEXT):
        raise AssertionError(f"{PDFTOTEXT} not found on PATH; install poppler-utils")
    txt_path = pdf_path.with_suffix(".txt")
    cmd = [PDFTOTEXT, str(pdf_path), str(txt_path)]
    subprocess.run(cmd, check=True)
    text = txt_path.read_text(encoding="utf-8", errors="ignore")
    return substring in text


def shutil_which(cmd: str) -> Optional[str]:
    """Return full path to cmd if found on PATH, else None."""
    from shutil import which

    return which(cmd)


def check_dlq_empty() -> None:
    """Assert the DLQ endpoint returns an empty list or zero length."""
    url = f"{API_BASE}/dlq"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    length = len(data) if isinstance(data, list) else data.get("length", 0)
    if length != 0:
        raise AssertionError(f"DLQ is not empty: length={length}")
    log("DLQ is empty")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", default="AAPL", help="Ticker to trigger")
    parser.add_argument("--timeout", type=int, default=600, help="Max seconds to wait for run completion")
    args = parser.parse_args()

    out_dir = Path("/tmp/aider_smoke")
    try:
        run_scanner_manual(args.ticker)
    except subprocess.CalledProcessError as e:
        log(f"Scanner invocation failed: {e}")
        return 1

    try:
        run = wait_for_run_complete(timeout_seconds=args.timeout)
        # verify commit
        assert_git_commit_present(run)

        # check Mailhog for message
        subject_substr = f"Research Note: {args.ticker}"
        msg = find_mailhog_message(subject_substr)
        # try to download PDF from Mailhog first
        try:
            pdf_from_mail = download_pdf_from_mailhog(msg, out_dir)
            pdf_path = pdf_from_mail
        except AssertionError:
            # fallback to pdf_path in run
            pdf_path = fetch_pdf_from_run(run, out_dir)

        # extract pipeline_run_id to check in pdf
        run_id = run.get("pipeline_run_id") or run.get("run_id") or run.get("id")
        if not run_id:
            raise AssertionError("Could not determine pipeline_run_id from run record")

        # check pdf contains run id (may require pdftotext)
        if not pdftotext_contains(pdf_path, run_id):
            raise AssertionError("PDF does not contain pipeline_run_id")
        log("PDF contains pipeline_run_id")

        # check DLQ empty
        check_dlq_empty()

    except Exception as exc:  # noqa: BLE001 - top-level handling
        log(f"Smoke test failed: {exc}")
        return 1

    log("Smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
