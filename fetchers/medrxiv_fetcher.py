import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from config import Config
from models import Paper

logger = logging.getLogger(__name__)

# medRxiv official API (faster indexing than api.biorxiv.org)
_API_BASE = "https://api.medrxiv.org/details/medrxiv"
_CURSOR_STEP = 100
_MAX_CURSOR = 500  # safety cap (5 pages × 100)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; MedicalPaperDigest/1.0; Academic Research)"
    )
}


class MedRxivFetcher:
    """
    Fetch recent preprints from medRxiv via api.medrxiv.org.
    API docs: https://api.biorxiv.org/
    """

    def __init__(self):
        self.max_results = Config.MAX_PAPERS_MEDRXIV
        self.days_back = Config.DAYS_BACK

    def fetch_recent_papers(self) -> List[Paper]:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.days_back)
        interval = (
            f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
        )
        logger.info(
            "Fetching medRxiv papers for interval %s (max=%d)",
            interval, self.max_results,
        )

        papers: List[Paper] = []
        cursor = 0
        while cursor <= _MAX_CURSOR and len(papers) < self.max_results:
            url = f"{_API_BASE}/{interval}/{cursor}/json"
            batch = self._fetch_page(url)
            if not batch:
                break
            for item in batch:
                p = self._to_paper(item)
                if p:
                    papers.append(p)
                if len(papers) >= self.max_results:
                    break
            if len(batch) < _CURSOR_STEP:
                break
            cursor += _CURSOR_STEP
            time.sleep(0.5)

        logger.info("Fetched %d papers from medRxiv", len(papers))
        return papers

    # ── private helpers ──────────────────────────────────────────────────────

    def _fetch_page(self, url: str) -> List[Dict[str, Any]]:
        try:
            r = requests.get(url, headers=_HEADERS, timeout=30)
            r.raise_for_status()
            data = r.json()
            collection = data.get("collection", [])
            total = data.get("messages", [{}])[0].get("total", "?")
            logger.debug("medRxiv page %s → %d items (total=%s)", url, len(collection), total)
            return collection
        except requests.RequestException as exc:
            logger.error("medRxiv request error: %s", exc)
            return []
        except (ValueError, KeyError) as exc:
            logger.error("medRxiv JSON parse error: %s", exc)
            return []

    def _to_paper(self, item: Dict[str, Any]) -> Optional[Paper]:
        try:
            title = item.get("title", "").strip()
            abstract = item.get("abstract", "").strip()
            if not title or not abstract:
                return None

            doi = item.get("doi", "")
            date_str = item.get("date", "")
            try:
                pub_date = datetime.strptime(date_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                pub_date = datetime.now()

            # Authors: "Lastname, Firstname; ..." format
            raw_authors = item.get("authors", "")
            authors = [a.strip() for a in raw_authors.split(";") if a.strip()][:5]

            url = f"https://www.medrxiv.org/content/{doi}v{item.get('version', 1)}"
            pdf_url = f"https://www.medrxiv.org/content/{doi}v{item.get('version', 1)}.full.pdf"

            return Paper(
                title=title,
                authors=authors,
                abstract=abstract,
                url=url,
                pdf_url=pdf_url,
                source="medRxiv",
                published=pub_date,
                paper_id=doi.replace("/", "_"),
                journal=item.get("journal_name", "").strip(),
            )
        except Exception as exc:
            logger.error("Error converting medRxiv item to Paper: %s", exc)
            return None
