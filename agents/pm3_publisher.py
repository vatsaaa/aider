"""PM3 Publisher Agent

This agent finalizes and publishes approved reports. It renders the final
markdown to PDF, commits the PDF into a git repository, emails the first
page to recipients, updates the `pipeline_runs` table, and emits an
`M11PublishReceipt` on success.
"""

from __future__ import annotations

import os
import smtplib
import subprocess
from datetime import datetime, timezone
from email import encoders
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel
from sqlalchemy import create_engine

from core.agent_base import BaseAgent
from core.bus import Bus, Message
from core.schemas import M11PublishReceipt, MessageEnvelope
from core.exceptions import FatalError

from reporting.renderer import render, RendererError
from reporting.storage import ReportObjectStore


class PM3PublisherAgent(BaseAgent):
    """Publisher agent that renders PDFs, commits to git, emails, and marks runs complete."""

    stream_in = "stage:pm2:output"
    stream_out = "stage:pm3:output"
    group_name = "pm3-group"
    agent_name = "pm3_publisher"

    def __init__(self, bus: Bus, db: Any, settings: Any) -> None:
        super().__init__(bus=bus, db=db, settings=settings)
        self.object_store = ReportObjectStore(settings)

    def _extract_page1(self, markdown: str) -> str:
        """Return the first page section of `markdown` up to the first '## ' header."""

        lines = markdown.splitlines()
        out_lines = []
        for idx, line in enumerate(lines):
            out_lines.append(line)
            if line.startswith("## ") and idx != 0:
                break
        return "\n".join(out_lines).strip()

    def process(self, message: Message) -> Optional[BaseModel]:
        """Process `M10FinalReport` and publish the final report.

        The method follows these steps: load final_md from `reports`, render
        to PDF, commit the PDF into the git repo, send email with PDF
        attached, update `pipeline_runs`, and publish an `M11PublishReceipt`.
        """

        payload = message.payload or message.data.get("payload", {})
        run_id = message.pipeline_run_id or payload.get("run_id")

        if not run_id:
            self.bus.publish_dlq("pm3_missing_run_id", message.stream, message.data, None)
            raise FatalError("missing_run_id", None)

        if self.db is None:
            self.bus.publish_dlq("pm3_no_db", message.stream, message.data, run_id)
            raise FatalError("no_db", run_id)

        # fetch final_md and metadata from reports
        report = self.repository.load_report_by_run_id(run_id)
        if not report:
            self.bus.publish_dlq("pm3_missing_report", message.stream, message.data, run_id)
            raise FatalError("missing_report", run_id)

        final_md = report.get("final_md")
        ticker = report.get("ticker")
        rating = report.get("rating")

        # Render PDF
        try:
            pdf_path = render(final_md or "", run_id)
        except RendererError as err:
            self.bus.publish_dlq("pm3_render_failed", message.stream, message.data, run_id)
            raise FatalError("render_failed", run_id)

        # Copy PDF into git repo path
        repo_base = Path(self.settings.GIT_REPO_PATH)
        dest_dir = repo_base / (ticker or "unknown")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_pdf = dest_dir / f"{run_id}.pdf"
        # atomic copy
        Path(pdf_path).replace(dest_pdf)

        artifact_uri = None
        if self.object_store.enabled():
            try:
                artifact_uri = self.object_store.upload_pdf(dest_pdf, run_id=run_id, ticker=ticker)
            except Exception:
                self.bus.publish_dlq("pm3_object_storage_failed", message.stream, message.data, run_id)
                raise FatalError("object_storage_failed", run_id)

        # Persist the local file path and optional object-store URI on the report row
        self.repository.update_report_artifacts(
            run_id=run_id,
            pdf_path=str(dest_pdf),
            artifact_uri=artifact_uri,
        )

        # Git commit
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = self.settings.GIT_AUTHOR_NAME
        env["GIT_AUTHOR_EMAIL"] = self.settings.GIT_AUTHOR_EMAIL

        try:
            subprocess.run(["git", "add", str(dest_pdf)], check=True, cwd=str(repo_base), env=env, capture_output=True)
            commit_msg = f"{ticker} — {rating or 'UNRATED'} | {datetime.now(timezone.utc).date().isoformat()} | run:{run_id}"
            subprocess.run(["git", "commit", "-m", commit_msg], check=True, cwd=str(repo_base), env=env, capture_output=True)
            rev = subprocess.run(["git", "rev-parse", "HEAD"], check=True, cwd=str(repo_base), env=env, capture_output=True, text=True)
            commit_hash = rev.stdout.strip()
        except subprocess.CalledProcessError as err:
            self.bus.publish_dlq("pm3_git_failed", message.stream, message.data, run_id)
            raise FatalError("git_failed", run_id)

        # Send email with Page 1 and attachment
        page1 = self._extract_page1(final_md or "")
        try:
            msg = MIMEMultipart()
            msg["From"] = self.settings.SMTP_FROM
            msg["To"] = ", ".join(self.settings.SMTP_TO or [])
            msg["Subject"] = f"Research Note: {ticker} — {rating or 'UNRATED'}"

            # plain text part
            msg.attach(MIMEText(page1, "plain"))

            # attachment
            with open(dest_pdf, "rb") as fh:
                part = MIMEApplication(fh.read(), _subtype="pdf")
                part.add_header("Content-Disposition", "attachment", filename=dest_pdf.name)
                msg.attach(part)

            smtp_host = self.settings.SMTP_HOST
            smtp_port = int(self.settings.SMTP_PORT)
            with smtplib.SMTP(smtp_host, smtp_port) as smtp:
                if self.settings.SMTP_USER and self.settings.SMTP_PASSWORD:
                    smtp.login(self.settings.SMTP_USER, self.settings.SMTP_PASSWORD)
                smtp.send_message(msg)
        except Exception:
            self.bus.publish_dlq("pm3_email_failed", message.stream, message.data, run_id)
            raise FatalError("email_failed", run_id)

        # Update pipeline_runs
        self.repository.update_pipeline_run_status(
            run_id=run_id,
            status="complete",
            git_commit_hash=commit_hash,
            completed_at=datetime.now(timezone.utc),
        )

        # Publish M11
        receipt_payload = {
            "git_commit_hash": commit_hash,
            "email_sent_at": datetime.now(timezone.utc).isoformat(),
            "pdf_path": str(dest_pdf),
            "artifact_uri": artifact_uri,
            "run_id": run_id,
        }

        return M11PublishReceipt.model_validate(receipt_payload)


__all__ = ["PM3PublisherAgent"]
