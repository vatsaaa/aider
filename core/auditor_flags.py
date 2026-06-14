"""Simple auditor-flag detection utilities.

Functions in this module scan filing text for known patterns that indicate
auditor concerns such as going-concern language, related-party transactions,
and restatements.
"""

from __future__ import annotations

import re
from typing import Iterable, List


def scan_texts_for_flags(texts: Iterable[str]) -> List[str]:
    """Scan an iterable of text blobs and return a list of detected flags.

    Supported flags:
    - "going_concern": detects "substantial doubt"
    - "related_party_txn": detects related-party wording plus dollar amounts > 1,000,000
    - "revenue_recognition_change": detects accounting policy changes related to revenue
    - "restatement": detects mention of restatements
    """

    flags: set[str] = set()
    rp_amount_re = re.compile(r"\$?([0-9,.]+)\s*(?:million|bn|billion)?", re.IGNORECASE)

    for text in texts:
        if not text:
            continue
        lower = text.lower()
        if "substantial doubt" in lower:
            flags.add("going_concern")

        if "restat" in lower or "correct" in lower and "prior" in lower:
            flags.add("restatement")

        if "related party" in lower or "related-party" in lower or "related person" in lower:
            # Look for dollar amounts nearby
            for match in rp_amount_re.finditer(text):
                try:
                    val = float(match.group(1).replace(',', ''))
                except Exception:
                    continue
                # If value is large (>= 1,000,000) flag it
                if val >= 1_000_000:
                    flags.add("related_party_txn")
                    break

        if "change in accounting" in lower or "policy" in lower and "revenue" in lower:
            flags.add("revenue_recognition_change")

    return sorted(flags)
