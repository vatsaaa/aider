"""Tests for PM3 publisher and renderer."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from unittest.mock import MagicMock

import pytest

from reporting import renderer


def test_pm3_renders_pdf(monkeypatch, tmp_path):
    called = {}

    def fake_run(cmd, capture_output=False):
        called['cmd'] = cmd
        class R:
            returncode = 0
            stderr = b""
        return R()

    monkeypatch.setattr(renderer, "subprocess", MagicMock(run=fake_run))

    out = renderer.render("# Title\n\nContent", "run-123")
    assert "run-123" in out
    assert called['cmd'][0] == "pandoc"
    assert "--pdf-engine=xelatex" in called['cmd']


def test_pm3_pdf_path_contains_run_id(monkeypatch):
    from reporting import renderer
    # ensure subprocess.run succeeds
    monkeypatch.setattr(renderer, "subprocess", MagicMock(run=lambda *a, **k: type("R", (), {"returncode": 0, "stderr": b""})()))
    path = renderer.render("# T", "rid-456")
    assert "rid-456" in path


def _create_temp_db(path):
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pipeline_runs (
            run_id TEXT PRIMARY KEY,
            ticker TEXT,
            trigger_type TEXT,
            status TEXT,
            started_at DATETIME,
            completed_at DATETIME,
            git_commit_hash TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            report_id TEXT PRIMARY KEY,
            run_id TEXT,
            model_id TEXT,
            ticker TEXT,
            iteration INTEGER,
            status TEXT,
            draft_md TEXT,
            final_md TEXT,
            pdf_path TEXT,
            artifact_uri TEXT,
            rating TEXT
        )
        """
    )
    conn.commit()
    return conn


def test_pm3_git_commit_and_email_and_db_update(monkeypatch, tmp_path):
    from agents.pm3_publisher import PM3PublisherAgent
    from core.bus import InMemoryBus, Message
    import sqlalchemy
    from sqlalchemy import text
    from core import config

    # create a temporary sqlite file-based DB
    db_file = tmp_path / "pm3_test.db"
    conn = _create_temp_db(str(db_file))
    cur = conn.cursor()
    run_id = "run-xyz"
    ticker = "TICK"
    rating = "BUY"
    # insert pipeline_runs and reports
    cur.execute("INSERT INTO pipeline_runs (run_id, ticker, trigger_type, status) VALUES (?, ?, ?, ?)", (run_id, ticker, "manual", "started"))
    final_md = "# Title\nFirst page text.\n\n## Section 2\nMore"
    cur.execute("INSERT INTO reports (report_id, run_id, ticker, iteration, status, final_md, rating) VALUES (?, ?, ?, ?, ?, ?, ?)", ("rid1", run_id, ticker, 1, "approved", final_md, rating))
    conn.commit()
    conn.close()

    # create SQLAlchemy engine for that file
    engine = sqlalchemy.create_engine(f"sqlite:///{db_file}")

    # Monkeypatch create_engine used inside the agent to return our engine
    import agents.pm3_publisher as pm3_mod
    monkeypatch.setattr(pm3_mod, "create_engine", lambda url: engine)

    # Monkeypatch renderer.render to produce a fake pdf file path
    fake_pdf = tmp_path / f"{run_id}.pdf"
    fake_pdf.write_bytes(b"PDFDATA")
    monkeypatch.setattr(pm3_mod, "render", lambda md, rid: str(fake_pdf))

    # Capture subprocess.run calls for git
    calls = []

    def fake_subprocess_run(cmd, check=False, cwd=None, env=None, capture_output=False, text=False):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = "deadbeef\n"
        return R()

    monkeypatch.setattr(pm3_mod, "subprocess", MagicMock(run=fake_subprocess_run))

    # Monkeypatch SMTP to capture message
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port):
            sent['host'] = host
            sent['port'] = port

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, user, password):
            sent['login'] = (user, password)

        def send_message(self, msg):
            sent['msg'] = msg

    monkeypatch.setattr(pm3_mod, "smtplib", MagicMock(SMTP=FakeSMTP))

    # Prepare bus and message
    bus = InMemoryBus()
    message = Message(id="1", stream="stage:pm2:output", data={"payload": {}}, pipeline_run_id=run_id, ticker=ticker, trigger_type="manual", timestamp=None, payload={}, metadata={})

    agent = PM3PublisherAgent(bus=bus, db=engine, settings=config.settings)
    receipt = agent.process(message)
    agent.publish_result(receipt, message)

    # assert git commands called (git add, commit, rev-parse)
    assert any(cmd[0] == 'git' and cmd[1] == 'add' for cmd in calls)
    assert any(cmd[0] == 'git' and cmd[1] == 'commit' for cmd in calls)

    # assert email sent and has pdf attachment
    assert 'msg' in sent
    msg = sent['msg']
    # count attachments by checking for parts with filename
    attachments = [p for p in msg.walk() if p.get_filename()]
    assert len(attachments) == 1
    assert attachments[0].get_content_type() == 'application/pdf'

    # check DB updated
    conn2 = sqlite3.connect(str(db_file))
    cur2 = conn2.cursor()
    cur2.execute("SELECT status, git_commit_hash FROM pipeline_runs WHERE run_id = ?", (run_id,))
    row = cur2.fetchone()
    assert row is not None
    assert row[0] == 'complete'
    assert row[1] is not None

    # check m11 published
    assert receipt is not None
    assert receipt.git_commit_hash
    assert receipt.pdf_path.endswith(f"{run_id}.pdf")
    assert receipt.artifact_uri is None
    assert bus.get_stream_length("stage:pm3:output") == 1
    out = bus.read("stage:pm3:output", count=1)
    assert out and out[0]['message']


def test_pm3_uploads_pdf_to_s3_and_persists_artifact_uri(monkeypatch, tmp_path):
    from agents.pm3_publisher import PM3PublisherAgent
    from core.bus import InMemoryBus, Message
    import sqlalchemy
    from core import config

    db_file = tmp_path / "pm3_s3_test.db"
    conn = _create_temp_db(str(db_file))
    cur = conn.cursor()
    run_id = "run-s3"
    ticker = "TICK"
    rating = "BUY"
    cur.execute("INSERT INTO pipeline_runs (run_id, ticker, trigger_type, status) VALUES (?, ?, ?, ?)", (run_id, ticker, "manual", "started"))
    final_md = "# Title\nFirst page text.\n\n## Section 2\nMore"
    cur.execute("INSERT INTO reports (report_id, run_id, ticker, iteration, status, final_md, rating) VALUES (?, ?, ?, ?, ?, ?, ?)", ("rid-s3", run_id, ticker, 1, "approved", final_md, rating))
    conn.commit()
    conn.close()

    engine = sqlalchemy.create_engine(f"sqlite:///{db_file}")

    import agents.pm3_publisher as pm3_mod
    monkeypatch.setattr(pm3_mod, "create_engine", lambda url: engine)

    fake_pdf = tmp_path / f"{run_id}.pdf"
    fake_pdf.write_bytes(b"PDFDATA")
    monkeypatch.setattr(pm3_mod, "render", lambda md, rid: str(fake_pdf))

    calls = []

    def fake_subprocess_run(cmd, check=False, cwd=None, env=None, capture_output=False, text=False):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = "deadbeef\n"
        return R()

    monkeypatch.setattr(pm3_mod, "subprocess", MagicMock(run=fake_subprocess_run))

    sent = {}

    class FakeSMTP:
        def __init__(self, host, port):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send_message(self, msg):
            sent['msg'] = msg

    monkeypatch.setattr(pm3_mod, "smtplib", MagicMock(SMTP=FakeSMTP))

    uploaded = {}

    class FakeStore:
        def __init__(self, settings):
            self.settings = settings

        def enabled(self):
            return True

        def upload_pdf(self, pdf_path, *, run_id, ticker=None):
            uploaded['pdf_path'] = str(pdf_path)
            uploaded['run_id'] = run_id
            uploaded['ticker'] = ticker
            return f"s3://reports/{run_id}/{fake_pdf.name}"

    monkeypatch.setattr(pm3_mod, "ReportObjectStore", FakeStore)

    bus = InMemoryBus()
    message = Message(id="2", stream="stage:pm2:output", data={"payload": {}}, pipeline_run_id=run_id, ticker=ticker, trigger_type="manual", timestamp=None, payload={}, metadata={})

    agent = PM3PublisherAgent(bus=bus, db=engine, settings=config.settings)
    receipt = agent.process(message)
    agent.publish_result(receipt, message)

    assert uploaded['run_id'] == run_id
    assert receipt.artifact_uri == f"s3://reports/{run_id}/{fake_pdf.name}"

    conn2 = sqlite3.connect(str(db_file))
    cur2 = conn2.cursor()
    cur2.execute("SELECT pdf_path, artifact_uri FROM reports WHERE run_id = ?", (run_id,))
    row = cur2.fetchone()
    assert row is not None
    assert row[0].endswith(f"{run_id}.pdf")
    assert row[1] == receipt.artifact_uri
