"""Firecrawl fetcher reserved for M1.5+.

M1 uses the local httpx + BeautifulSoup fetcher only. This module keeps the
future switch point explicit without adding a Firecrawl dependency.
"""

from __future__ import annotations

from cs_mvp.tools.fetch import FetchResult


def fetch_via_firecrawl(url: str, timeout: float = 30.0) -> FetchResult:
    raise NotImplementedError("Firecrawl fetcher reserved for M1.5+; do not call in M1.")
