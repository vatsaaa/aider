"""SEC EDGAR watcher that promotes new filings into the trigger stream.

The watcher polls the SEC current-filings Atom feeds for 8-K, 10-Q, and 10-K
entries, filters them to the current coverage universe, deduplicates them
against the `edgar_triggers` table, and publishes M1 trigger envelopes onto
`trigger:events`.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

import requests

from core.bus import Bus
from core.config import Settings
from core.schemas import M1TriggerEvent, MessageEnvelope
from db.edgar_triggers import already_triggered, already_triggered_for_period, list_coverage_tickers, record_trigger
from db.pipeline_runs import ensure_pipeline_run


ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
SEC_FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form_type}&dateb=&owner=include&count=40&search_text=&output=atom"


@dataclass(frozen=True)
class EdgarEntry:
    """Parsed SEC feed entry."""

    accession_number: str
    ticker: str | None
    form_type: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    filed_at: datetime | None
    title: str


class EdgarWatcher:
    """Poll SEC EDGAR feeds and emit M1 trigger events for covered filings."""

    def __init__(self, bus: Bus, db: Any, settings: Settings) -> None:
        """Store runtime dependencies used during feed polling."""

        self.bus = bus
        self.db = db
        self.settings = settings
        self.stream_name = "trigger:events"

    def poll(self) -> list[M1TriggerEvent]:
        """Fetch SEC Atom feeds, filter covered filings, deduplicate, and publish.

        Returns the list of newly created M1 events. Each accepted event is also
        published to the trigger stream with a full message envelope.
        """

        events: list[M1TriggerEvent] = []
        covered_tickers = list_coverage_tickers(self.db)
        seen_accessions: set[str] = set()

        for index, form_type in enumerate(("8-K", "10-Q", "10-K")):
            if index:
                time.sleep(0.1)
            feed_url = SEC_FEED_URL.format(form_type=form_type)
            response = requests.get(
                feed_url,
                headers={"User-Agent": self.settings.SEC_USER_AGENT, "Accept": "application/atom+xml"},
                timeout=30,
            )
            response.raise_for_status()

            for entry in self._parse_feed(response.text, form_type):
                if entry.accession_number in seen_accessions:
                    continue
                seen_accessions.add(entry.accession_number)

                ticker = (entry.ticker or "").upper()
                if not ticker or not self._is_covered(ticker):
                    continue
                if self._already_triggered(entry.accession_number):
                    continue
                if self._already_triggered_for_period(ticker, form_type, entry.fiscal_year, entry.fiscal_period):
                    continue

                event = M1TriggerEvent(
                    ticker=ticker,
                    trigger_type=form_type,
                    pipeline_run_id=str(uuid4()),
                )
                inserted = record_trigger(
                    self.db,
                    accession_number=entry.accession_number,
                    run_id=None,
                    ticker=ticker,
                    form_type=form_type,
                    fiscal_year=entry.fiscal_year,
                    fiscal_period=entry.fiscal_period,
                    filed_at=entry.filed_at,
                )
                if not inserted:
                    continue
                ensure_pipeline_run(
                    self.db,
                    run_id=event.pipeline_run_id,
                    ticker=ticker,
                    trigger_type=form_type,
                    status="started",
                )
                self._publish_event(event, entry)
                events.append(event)

        return events

    def _publish_event(self, event: M1TriggerEvent, entry: EdgarEntry) -> None:
        """Publish an M1 trigger envelope to the bus."""

        envelope = MessageEnvelope(
            message_id=str(uuid4()),
            pipeline_run_id=event.pipeline_run_id,
            trigger_type=event.trigger_type,
            ticker=event.ticker,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=event.model_dump(),
            metadata={
                "source": "edgar_watcher",
                "accession_number": entry.accession_number,
                "form_type": entry.form_type or event.trigger_type,
            },
        )
        self.bus.publish(self.stream_name, envelope.model_dump())

    def _parse_feed(self, xml_text: str, form_type: str) -> list[EdgarEntry]:
        """Parse Atom feed XML into normalized `EdgarEntry` records."""

        root = ET.fromstring(xml_text)
        entries: list[EdgarEntry] = []
        for entry in root.findall("atom:entry", ATOM_NS):
            accession_number = self._extract_accession_number(entry)
            ticker = self._extract_ticker(entry)
            filed_at = self._extract_datetime(entry)
            title = self._text(entry.find("atom:title", ATOM_NS)) or ""
            summary = self._text(entry.find("atom:summary", ATOM_NS)) or ""
            fiscal_year, fiscal_period = self._extract_fiscal_period(form_type, filed_at, title, summary)
            entries.append(
                EdgarEntry(
                    accession_number=accession_number,
                    ticker=ticker,
                    form_type=form_type,
                    fiscal_year=fiscal_year,
                    fiscal_period=fiscal_period,
                    filed_at=filed_at,
                    title=title,
                )
            )
        return entries

    def _extract_fiscal_period(
        self,
        form_type: str,
        filed_at: datetime | None,
        title: str,
        summary: str,
    ) -> tuple[int | None, str | None]:
        """Infer the fiscal year/period from the filing text or filing date.

        The SEC feed does not always expose the period directly, so we look
        for a period-of-report style date in the title or summary and fall back
        to a filing-date-based quarterly bucket when necessary.
        """

        if form_type not in {"10-Q", "10-K"}:
            return None, None

        haystack = f"{title}\n{summary}".lower()
        extracted_date = self._extract_period_date(haystack)
        if extracted_date is not None:
            year = extracted_date.year
            if form_type == "10-K":
                return year, f"FY{year}"
            quarter = ((extracted_date.month - 1) // 3) + 1
            return year, f"FY{year}Q{quarter}"

        if filed_at is None:
            return None, None

        filing_year = filed_at.year
        if form_type == "10-K":
            return filing_year, f"FY{filing_year}"
        if form_type == "10-Q":
            quarter = ((filed_at.month - 1) // 3) + 1
            return filing_year, f"FY{filing_year}Q{quarter}"
        return filing_year, f"FY{filing_year}"

    def _extract_period_date(self, text: str) -> datetime | None:
        """Extract a report-period date from filing text when present."""

        patterns = [
            r"period of report[:\s]+([a-z]+\s+\d{1,2},\s+\d{4})",
            r"quarter ended\s+([a-z]+\s+\d{1,2},\s+\d{4})",
            r"year ended\s+([a-z]+\s+\d{1,2},\s+\d{4})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            try:
                return datetime.strptime(match.group(1), "%B %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                try:
                    return datetime.strptime(match.group(1), "%b %d, %Y").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        return None

    def _extract_accession_number(self, entry: ET.Element) -> str:
        """Extract the accession number from a feed entry."""

        entry_id = self._text(entry.find("atom:id", ATOM_NS)) or ""
        href = ""
        link = entry.find("atom:link", ATOM_NS)
        if link is not None:
            href = link.attrib.get("href", "")
        candidates = [entry_id, href, self._text(entry.find("atom:summary", ATOM_NS)) or ""]
        for candidate in candidates:
            match = re.search(r"accession(?:-number)?=([0-9\-]+)", candidate)
            if match:
                return match.group(1)
            match = re.search(r"([0-9]{10}-[0-9]{2}-[0-9]{6})", candidate)
            if match:
                return match.group(1)
        raise ValueError("Unable to determine accession number from EDGAR entry")

    def _extract_ticker(self, entry: ET.Element) -> str | None:
        """Extract a ticker symbol from an Atom entry when present."""

        category = entry.find("atom:category", ATOM_NS)
        if category is not None:
            term = category.attrib.get("term")
            if term:
                return term.strip().upper()

        title = (self._text(entry.find("atom:title", ATOM_NS)) or "").upper()
        match = re.search(r"\(([A-Z]{1,6})\)", title)
        if match:
            return match.group(1)

        summary = (self._text(entry.find("atom:summary", ATOM_NS)) or "").upper()
        match = re.search(r"TICKER[:\s]+([A-Z]{1,6})", summary)
        if match:
            return match.group(1)
        return None

    def _extract_datetime(self, entry: ET.Element) -> datetime | None:
        """Extract the filing timestamp from the entry."""

        updated = self._text(entry.find("atom:updated", ATOM_NS))
        if not updated:
            return None
        try:
            normalized = updated.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None

    def _text(self, element: ET.Element | None) -> str | None:
        """Return stripped text content for an XML element."""

        if element is None or element.text is None:
            return None
        value = element.text.strip()
        return value or None

    def _is_covered(self, cik: str) -> bool:
        """Check whether a ticker/CIK-like identifier is covered."""

        return cik.upper() in list_coverage_tickers(self.db)

    def _already_triggered(self, accession_number: str) -> bool:
        """Check the EDGAR dedupe table for a previously processed filing."""

        return already_triggered(self.db, accession_number)

    def _already_triggered_for_period(
        self,
        ticker: str,
        form_type: str,
        fiscal_year: int | None,
        fiscal_period: str | None,
    ) -> bool:
        """Check whether the same fiscal period has already triggered a run."""

        return already_triggered_for_period(
            self.db,
            ticker=ticker,
            form_type=form_type,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
        )


__all__ = ["EdgarWatcher"]