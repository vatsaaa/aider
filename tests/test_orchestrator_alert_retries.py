import sys

from sqlalchemy import create_engine, text

import pytest


from orchestrator.monitor import OrchestratorMonitor


ALERT_SETTINGS = {
    "SMTP_HOST": "localhost",
    "SMTP_PORT": 1025,
    "SMTP_FROM": "test@localhost",
    "SMTP_TO": "ops@localhost",
    "SLACK_WEBHOOK_URL": "http://localhost:9999/webhook",
    "ALERT_MAX_RETRIES": 3,
    "ALERT_RETRY_BASE_SECONDS": 0,
}


@pytest.fixture(autouse=True)
def alert_settings(monkeypatch):
    """Overlay alert settings on the monitor module's settings without touching process env or other tests."""

    monitor_module = sys.modules[OrchestratorMonitor.__module__]
    real_settings = monitor_module.settings

    class _AlertSettings:
        """Settings proxy returning `ALERT_SETTINGS` overrides, else the real value."""

        def __getattr__(self, name):
            if name in ALERT_SETTINGS:
                return ALERT_SETTINGS[name]
            return getattr(real_settings, name)

    monkeypatch.setattr(monitor_module, "settings", _AlertSettings())


@pytest.fixture()
def sqlite_engine():
    engine = create_engine("sqlite:///:memory:")
    # create alerts_failures table
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE alerts_failures (id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT NOT NULL, payload JSON, error_message TEXT, failed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            )
        )
    yield engine


def test_slack_retries_and_record(sqlite_engine, monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(1)
        if len(calls) < 3:
            raise Exception("network")

        class Resp:
            def raise_for_status(self):
                return None

        return Resp()

    monkeypatch.setattr("requests.post", fake_post, raising=False)
    monkeypatch.setattr("time.sleep", lambda s: None)

    monitor = OrchestratorMonitor(redis_client=object(), db_engine=sqlite_engine)

    # should succeed on 3rd attempt
    monitor._send_slack({"run_id": "r1", "failures": 2, "reason": "x"})
    assert len(calls) == 3

    # now force permanent failure and assert DB record
    def always_fail(url, json=None, timeout=None):
        raise Exception("down")

    monkeypatch.setattr("requests.post", always_fail, raising=False)
    monitor._send_slack({"run_id": "r2", "failures": 5, "reason": "y"})

    with sqlite_engine.connect() as conn:
        res = conn.execute(text("SELECT count(*) FROM alerts_failures")).scalar()
    assert res >= 1


def test_email_retries_and_record(sqlite_engine, monkeypatch):
    attempts = {"count": 0}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise Exception("smtp down")
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, u, p):
            pass

        def sendmail(self, f, to, msg):
            return None

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP, raising=False)
    monkeypatch.setattr("time.sleep", lambda s: None)

    monitor = OrchestratorMonitor(redis_client=object(), db_engine=sqlite_engine)
    monitor._send_email({"run_id": "r3", "failures": 1, "reason": "z", "failed_at": "now"})
    assert attempts["count"] == 3

    # now simulate permanent failure
    class AlwaysFailSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            raise Exception("down")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("smtplib.SMTP", AlwaysFailSMTP, raising=False)
    monitor._send_email({"run_id": "r4", "failures": 9, "reason": "y", "failed_at": "now"})

    with sqlite_engine.connect() as conn:
        res = conn.execute(text("SELECT count(*) FROM alerts_failures")).scalar()
    assert res >= 1