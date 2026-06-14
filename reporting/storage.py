"""Binary artifact storage helpers for report outputs.

Supports optional S3/MinIO uploads for rendered PDFs while keeping the
existing git-tracked local copy path intact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional


class ReportObjectStore:
    """Upload rendered report binaries to S3-compatible object storage."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.bucket = getattr(settings, "REPORT_S3_BUCKET", None)
        self.prefix = (getattr(settings, "REPORT_S3_PREFIX", "reports") or "reports").strip("/")
        self.endpoint_url = getattr(settings, "REPORT_S3_ENDPOINT_URL", None)
        self.region = getattr(settings, "REPORT_S3_REGION", None)
        self.access_key_id = getattr(settings, "REPORT_S3_ACCESS_KEY_ID", None)
        self.secret_access_key = getattr(settings, "REPORT_S3_SECRET_ACCESS_KEY", None)
        self.use_ssl = bool(getattr(settings, "REPORT_S3_USE_SSL", True))
        self._client = None

    def enabled(self) -> bool:
        return bool(self.bucket)

    def _client_factory(self):
        if self._client is not None:
            return self._client

        if not self.enabled():
            return None

        try:
            import boto3
        except Exception as exc:  # pragma: no cover - import guard
            raise RuntimeError("boto3 is required for S3 report uploads") from exc

        self._client = boto3.client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            use_ssl=self.use_ssl,
        )
        return self._client

    def _object_key(self, run_id: str, filename: str) -> str:
        base = self.prefix.rstrip("/")
        if base:
            return f"{base}/{run_id}/{filename}"
        return f"{run_id}/{filename}"

    def ensure_bucket(self) -> None:
        client = self._client_factory()
        if client is None:
            return

        from botocore.exceptions import ClientError

        try:
            client.head_bucket(Bucket=self.bucket)
        except ClientError:
            create_kwargs = {"Bucket": self.bucket}
            if self.region and self.region != "us-east-1":
                create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self.region}
            client.create_bucket(**create_kwargs)

    def upload_pdf(self, pdf_path: str | Path, *, run_id: str, ticker: str | None = None) -> Optional[str]:
        """Upload a PDF and return its S3 URI when enabled."""

        if not self.enabled():
            return None

        path = Path(pdf_path)
        client = self._client_factory()
        if client is None:
            return None

        self.ensure_bucket()
        key = self._object_key(run_id, path.name)
        client.upload_file(
            str(path),
            self.bucket,
            key,
            ExtraArgs={"ContentType": "application/pdf"},
        )
        return f"s3://{self.bucket}/{key}"
