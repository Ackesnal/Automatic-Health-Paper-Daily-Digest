import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Optional

import requests

from config import Config
from models import Paper

logger = logging.getLogger(__name__)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


class PubMedFetcher:
    def __init__(self):
        self.query = Config.PUBMED_SEARCH_QUERY
        self.max_results = Config.MAX_PAPERS_PUBMED
        self.days_back = Config.DAYS_BACK
        self._base = {
            "tool": "MedicalPaperDigest",
            "email": Config.PUBMED_EMAIL,
        }

    def fetch_recent_papers(self) -> List[Paper]:
        """Fetch recent papers from PubMed via NCBI E-utilities."""
        end = datetime.now()
        start = end - timedelta(days=self.days_back)
        date_filter = (
            f"{start.strftime('%Y/%m/%d')}:{end.strftime('%Y/%m/%d')}[pdat]"
        )
        full_query = f"({self.query}) AND {date_filter}"
        logger.info("Querying PubMed: %s", full_query[:80])

        pmids = self._search(full_query)
        if not pmids:
            logger.info("No PubMed IDs found")
            return []

        papers = self._fetch_details(pmids[: self.max_results])
        logger.info("Fetched %d papers from PubMed", len(papers))
        return papers

    # ── private helpers ──────────────────────────────────────────────────────

    def _search(self, query: str) -> List[str]:
        params = {
            **self._base,
            "db": "pubmed",
            "term": query,
            "retmax": self.max_results,
            "retmode": "json",
            "sort": "pub_date",
        }
        try:
            r = requests.get(ESEARCH_URL, params=params, timeout=30)
            r.raise_for_status()
            return r.json().get("esearchresult", {}).get("idlist", [])
        except Exception as exc:
            logger.error("PubMed search error: %s", exc)
            return []

    def _fetch_details(self, pmids: List[str]) -> List[Paper]:
        if not pmids:
            return []
        time.sleep(0.4)  # respect NCBI rate limit (3 req/s without API key)
        params = {
            **self._base,
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }
        try:
            r = requests.get(EFETCH_URL, params=params, timeout=60)
            r.raise_for_status()
            return self._parse_xml(r.text)
        except Exception as exc:
            logger.error("PubMed fetch error: %s", exc)
            return []

    def _parse_xml(self, xml_text: str) -> List[Paper]:
        papers: List[Paper] = []
        try:
            root = ET.fromstring(xml_text)
            for article in root.findall(".//PubmedArticle"):
                p = self._parse_article(article)
                if p:
                    papers.append(p)
        except ET.ParseError as exc:
            logger.error("XML parse error: %s", exc)
        return papers

    def _parse_article(self, article) -> Optional[Paper]:
        try:
            medline = article.find("MedlineCitation")
            if medline is None:
                return None
            art = medline.find("Article")
            if art is None:
                return None

            # Title
            title_el = art.find("ArticleTitle")
            title = ("".join(title_el.itertext()) if title_el is not None else "").strip().rstrip(".")

            # Abstract (may have multiple AbstractText sections)
            abstract = " ".join(
                "".join(el.itertext()) for el in art.findall(".//AbstractText")
            ).strip()
            if not abstract:
                return None  # skip papers without abstracts

            # Authors
            authors = []
            for a in art.findall(".//Author"):
                ln = a.findtext("LastName", "")
                fn = a.findtext("ForeName", "")
                if ln:
                    authors.append(f"{fn} {ln}".strip())

            # PMID
            pmid_el = medline.find("PMID")
            pmid = pmid_el.text if pmid_el is not None else "0"

            # PMCID — only present for open-access articles in PMC
            pmcid = None
            for aid in article.findall(".//PubmedData/ArticleIdList/ArticleId"):
                if aid.get("IdType") == "pmc":
                    pmcid = aid.text  # e.g. "PMC1234567"
                    break

            pdf_url = (
                f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
                if pmcid else ""
            )

            pub_date = self._parse_date(art)

            return Paper(
                title=title,
                authors=authors[:5],
                abstract=abstract,
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                pdf_url=pdf_url,
                source="PubMed",
                published=pub_date,
                paper_id=f"pmid_{pmid}",
            )
        except Exception as exc:
            logger.error("Error parsing PubMed article: %s", exc)
            return None

    def _parse_date(self, art_elem) -> datetime:
        for path in [".//PubDate", ".//ArticleDate"]:
            el = art_elem.find(path)
            if el is None:
                continue
            year_str = el.findtext("Year")
            if not year_str:
                continue
            month_raw = el.findtext("Month", "1")
            day_raw = el.findtext("Day", "1")
            try:
                month = (
                    _MONTH_ABBR.get(month_raw.lower()[:3], 1)
                    if not month_raw.isdigit()
                    else int(month_raw)
                )
                return datetime(int(year_str), month, int(day_raw))
            except (ValueError, AttributeError):
                continue
        return datetime.now()
