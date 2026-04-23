import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import schedule
import time

# ── Logging setup ────────────────────────────────────────────────────────────

log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            log_dir / f"digest_{datetime.now().strftime('%Y%m')}.log",
            mode="a",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)


# ── Core digest function ─────────────────────────────────────────────────────

def run_digest():
    """Fetch → process → email one daily digest cycle."""
    # Deferred imports so logging is configured first
    from config import Config
    from fetchers.medrxiv_fetcher import MedRxivFetcher
    from fetchers.pubmed_fetcher import PubMedFetcher
    from processors.llm_processor import LLMProcessor
    from processors.pdf_parser import extract_text_from_pdf_url
    from notifier.email_sender import send_email, save_html_report

    date_str = datetime.now().strftime("%B %d, %Y")
    logger.info("=== Medical Research Digest – %s ===", date_str)

    all_papers = []

    # 1. Fetch ─────────────────────────────────────────────────────────────
    try:
        medrxiv_papers = MedRxivFetcher().fetch_recent_papers()
        all_papers.extend(medrxiv_papers)
        logger.info("medRxiv: %d papers", len(medrxiv_papers))
    except Exception as exc:
        logger.error("medRxiv fetch failed: %s", exc)

    try:
        pubmed_papers = PubMedFetcher().fetch_recent_papers()
        all_papers.extend(pubmed_papers)
        logger.info("PubMed: %d papers", len(pubmed_papers))
    except Exception as exc:
        logger.error("PubMed fetch failed: %s", exc)

    if not all_papers:
        logger.warning("No papers fetched – skipping digest for today.")
        return

    # Deduplicate by lowercased title
    seen: set = set()
    unique = []
    for p in all_papers:
        key = p.title.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    logger.info(
        "%d unique papers after dedup (removed %d)",
        len(unique), len(all_papers) - len(unique),
    )
    all_papers = unique

    # 2. Optional PDF download ─────────────────────────────────────────────
    if Config.DOWNLOAD_PDFS:
        sorted_by_date = sorted(
            all_papers,
            key=lambda p: p.published or datetime.min,
            reverse=True,
        )
        downloaded = 0
        for p in sorted_by_date:
            if downloaded >= Config.MAX_PDF_PAPERS:
                break
            if p.pdf_url:
                text = extract_text_from_pdf_url(p.pdf_url)
                if text:
                    p.full_text = text
                    downloaded += 1
                    logger.info("PDF downloaded: %s…", p.title[:60])
        logger.info("PDFs downloaded: %d", downloaded)

    # 3. LLM processing ────────────────────────────────────────────────────
    intro = f"Today's digest covers {len(all_papers)} recent healthcare and medical research papers."
    daily_summary = ""
    try:
        processor = LLMProcessor()
        all_papers = processor.process_papers(all_papers)
        intro = processor.generate_digest_intro(all_papers, date_str)
        daily_summary = processor.generate_daily_summary(all_papers, date_str)
        logger.info("LLM processing complete")
    except ValueError as exc:
        logger.error("LLM config error: %s", exc)
        for p in all_papers:
            p.topic = "Other Healthcare Topics"
            p.study_type = "Other / Unclear"
            p.relevance_score = 3
            p.summary = p.abstract[:400]
    except Exception as exc:
        logger.error("LLM processing error: %s", exc)

    # 4. Send email ────────────────────────────────────────────────────────
    success = send_email(all_papers, intro, daily_summary, date_str)
    if not success:
        fallback = log_dir / f"digest_{datetime.now().strftime('%Y%m%d')}.html"
        save_html_report(all_papers, intro, daily_summary, date_str, str(fallback))
        logger.warning("Email failed – HTML saved to %s", fallback)

    logger.info("=== Digest complete: %d papers ===", len(all_papers))


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Medical Paper Daily Digest")
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run the digest immediately and exit (useful for testing).",
    )
    parser.add_argument(
        "--schedule-only",
        action="store_true",
        help="Start the scheduler without running an immediate digest.",
    )
    args = parser.parse_args()

    if args.run_now:
        run_digest()
        return

    # Run once on startup unless --schedule-only
    if not args.schedule_only:
        logger.info("Running startup digest …")
        run_digest()

    from config import Config
    logger.info("Scheduling daily digest at %s (24h clock)", Config.SCHEDULE_TIME)
    schedule.every().day.at(Config.SCHEDULE_TIME).do(run_digest)
    logger.info("Scheduler running. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
