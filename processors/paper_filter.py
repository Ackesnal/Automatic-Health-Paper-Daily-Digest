"""
Filter papers to keep only those relevant to critical care / emergency medicine.

Priority 1 – Journal match:
    Paper is published in one of the target journals → kept unconditionally.

Priority 2 – Keyword match + LLM verification:
    Abstract contains a keyword → candidate for LLM second-pass.
    LLM confirms whether the paper is genuinely about one of the four focus areas:
      • Paediatric critical care
      • Paediatric intensive care / PICU
      • Adult intensive care / ICU
      • Emergency medicine
    Papers the LLM rejects are discarded.

All other papers (no journal match, no keyword hit) are discarded immediately.
"""

import json
import logging
import re
import time
from typing import List, Tuple

from openai import OpenAI

from config import Config
from models import Paper

logger = logging.getLogger(__name__)

_LLM_BATCH = 10      # abstracts per LLM call
_RETRY_SLEEP = 5

# ── Target journals (exact match, case-insensitive) ──────────────────────────

_TARGET_JOURNALS: List[str] = [
    "critical care and resuscitation",
    "intensive care medicine",
    "pediatric critical care medicine",
    "paediatric critical care medicine",
    "the new england journal of medicine",
    "new england journal of medicine",
    "n engl j med",
    "critical care",
    "crit care",
    "the journal of the american medical association",
    "journal of the american medical association",
    "jama",
    "lancet",
    "the lancet",
]

# ── Abstract keyword patterns ─────────────────────────────────────────────────

_AREA_PATTERNS: List[re.Pattern] = [
    re.compile(r"pa?ediatric\s+critical\s+care",  re.IGNORECASE),
    re.compile(r"pa?ediatric\s+intensive\s+care", re.IGNORECASE),
    re.compile(r"\bPICU\b"),
    re.compile(r"\bICU\b"),
    re.compile(r"adult\s+intensive\s+care",       re.IGNORECASE),
    re.compile(r"adult\s+critical\s+care",        re.IGNORECASE),
    re.compile(r"intensive\s+care\s+unit",        re.IGNORECASE),
    re.compile(r"emergency\s+medicine",           re.IGNORECASE),
    re.compile(r"emergency\s+department",         re.IGNORECASE),
]

_FOCUS_AREAS = (
    "paediatric critical care, "
    "paediatric intensive care (PICU), "
    "adult intensive care (ICU), "
    "emergency medicine"
)


def _journal_relevant(journal: str) -> bool:
    return journal.strip().lower() in _TARGET_JOURNALS


def _keyword_match(abstract: str) -> bool:
    return any(pat.search(abstract) for pat in _AREA_PATTERNS)


def _llm_verify(papers: List[Paper]) -> List[bool]:
    """
    Ask the LLM whether each paper is genuinely about one of the focus areas.
    Returns a list of booleans (True = keep) in the same order as input.
    Defaults to True on any API failure to avoid discarding papers incorrectly.
    """
    if not papers:
        return []

    client = OpenAI(api_key=Config.OPENAI_API_KEY)
    results: List[bool] = [True] * len(papers)

    for batch_start in range(0, len(papers), _LLM_BATCH):
        batch = papers[batch_start: batch_start + _LLM_BATCH]
        items_text = ""
        for i, p in enumerate(batch, start=1):
            items_text += (
                f"\n--- Paper {i} ---\n"
                f"Title: {p.title}\n"
                f"Abstract: {p.abstract[:600]}\n"
            )

        prompt = f"""You are a medical research screener for a critical care and emergency medicine digest.

For each paper below, decide whether it is genuinely focused on one of these areas:
  - Paediatric critical care
  - Paediatric intensive care (PICU)
  - Adult intensive care (ICU)
  - Emergency medicine

A paper that merely mentions "ICU" or "emergency department" as a minor detail (e.g. a basic-science paper where patients happened to be recruited from ICU) should be marked false.
A paper whose main subject is diagnosis, treatment, management, outcomes, or policy within these areas should be marked true.

{items_text}

Return ONLY a JSON object with exactly this structure (no extra text):
{{
  "decisions": [
    {{"index": 1, "keep": true}},
    {{"index": 2, "keep": false}}
  ]
}}"""

        for attempt in range(2):
            try:
                resp = client.chat.completions.create(
                    model=Config.LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.0,
                    max_completion_tokens=300,
                )
                data = json.loads(resp.choices[0].message.content)
                for item in data.get("decisions", []):
                    idx = int(item.get("index", 1)) - 1
                    global_idx = batch_start + idx
                    if 0 <= global_idx < len(results):
                        results[global_idx] = bool(item.get("keep", True))
                break
            except Exception as exc:
                logger.warning(
                    "LLM relevance check failed (attempt %d): %s", attempt + 1, exc
                )
                time.sleep(_RETRY_SLEEP)
        else:
            # Both attempts failed — keep the batch (safe default)
            logger.warning(
                "LLM relevance check gave up for batch starting at %d; keeping by default",
                batch_start,
            )

        if batch_start + _LLM_BATCH < len(papers):
            time.sleep(0.5)

    return results


def filter_papers(papers: List[Paper]) -> List[Paper]:
    """
    Three-stage filter:
      1. Journal match → keep immediately.
      2. Keyword match → LLM second-pass verification.
      3. Everything else → discard immediately.
    """
    journal_kept: List[Paper] = []
    keyword_candidates: List[Paper] = []

    for p in papers:
        if p.journal and _journal_relevant(p.journal):
            journal_kept.append(p)
            logger.debug("Kept (journal: %s): %s", p.journal, p.title[:60])
        elif _keyword_match(p.abstract):
            keyword_candidates.append(p)
            logger.debug("Keyword candidate: %s", p.title[:60])
        else:
            logger.debug("Discarded (no match): %s", p.title[:60])

    # LLM second-pass on keyword candidates
    llm_kept: List[Paper] = []
    if keyword_candidates:
        logger.info(
            "LLM relevance check: verifying %d keyword-matched papers …",
            len(keyword_candidates),
        )
        decisions = _llm_verify(keyword_candidates)
        for paper, keep in zip(keyword_candidates, decisions):
            if keep:
                llm_kept.append(paper)
                logger.debug("Kept (LLM confirmed): %s", paper.title[:60])
            else:
                logger.debug("Discarded (LLM rejected): %s", paper.title[:60])

    kept = journal_kept + llm_kept
    logger.info(
        "Paper filter: %d total → %d journal, %d LLM-confirmed, %d discarded",
        len(papers),
        len(journal_kept),
        len(llm_kept),
        len(papers) - len(kept),
    )
    return kept
