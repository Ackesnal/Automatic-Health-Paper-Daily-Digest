import logging
from datetime import datetime, timedelta, timezone
from typing import List

import arxiv

from config import Config
from models import Paper

logger = logging.getLogger(__name__)


class ArxivFetcher:
    def __init__(self):
        self.query = Config.ARXIV_SEARCH_QUERY
        self.max_results = Config.MAX_PAPERS_ARXIV
        self.days_back = Config.DAYS_BACK
        self.client = arxiv.Client(
            page_size=100,
            delay_seconds=3,
            num_retries=3,
        )

    def fetch_recent_papers(self) -> List[Paper]:
        """Fetch recent medical / healthcare papers from arXiv."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.days_back)
        logger.info(
            "Fetching arXiv papers since %s", cutoff.strftime("%Y-%m-%d %H:%M UTC")
        )

        search = arxiv.Search(
            query=self.query,
            max_results=self.max_results * 2,  # over-fetch; we filter by date below
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        papers: List[Paper] = []
        try:
            for result in self.client.results(search):
                pub = result.published
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)

                if pub < cutoff:
                    # Results are date-sorted; stop once we go past cutoff
                    if papers:
                        break
                    continue

                papers.append(
                    Paper(
                        title=result.title.replace("\n", " ").strip(),
                        authors=[str(a) for a in result.authors[:5]],
                        abstract=result.summary.replace("\n", " ").strip(),
                        url=result.entry_id,
                        pdf_url=result.pdf_url,
                        source="arXiv",
                        published=pub,
                        paper_id=result.entry_id.split("/")[-1],
                    )
                )

                if len(papers) >= self.max_results:
                    break

        except Exception as exc:
            logger.error("Error fetching arXiv papers: %s", exc)

        logger.info("Fetched %d papers from arXiv", len(papers))
        return papers
