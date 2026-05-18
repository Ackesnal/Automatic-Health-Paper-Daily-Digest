import logging
import time
from collections import Counter
from typing import Any, Dict, List, cast

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from config import Config
from models import Paper

logger = logging.getLogger(__name__)

# ── Classification taxonomy ──────────────────────────────────────────────────

TOPICS = [
    "Clinical Research & Trials",
    "Medical AI & Machine Learning",
    "Drug Discovery & Pharmacology",
    "Genomics & Precision Medicine",
    "Medical Imaging & Diagnostics",
    "Public Health & Epidemiology",
    "Cardiology & Cardiovascular Disease",
    "Oncology & Cancer Research",
    "Infectious Diseases",
    "Neurology & Brain Disorders",
    "Surgery & Procedures",
    "Mental Health & Psychiatry",
    "Other Healthcare Topics",
]

STUDY_TYPES = [
    "Randomized Controlled Trial (RCT)",
    "Systematic Review / Meta-Analysis",
    "Observational Study",
    "Cohort Study",
    "Cross-Sectional Study",
    "Case Report / Case Series",
    "Computational / Modeling Study",
    "Laboratory / In Vitro Study",
    "Clinical Guidelines / Review Article",
    "Other / Unclear",
]

PATIENT_GROUPS = [
    "Paediatric",         # children / adolescents (< 18 years)
    "Adult",              # adults (≥ 18 years)
    "Mixed / All Ages",   # involves or does not restrict to a single age group
    "No human subjects",     # animal, in vitro, computational – no human subjects
]

_BATCH = 1          # papers per LLM call
_RETRY_SLEEP = 5    # seconds between retries

_DIGEST_INTRO_INSTRUCTIONS = """You write the opening lines for a daily critical care and emergency medicine research digest.

# Goal
Write a concise intro that highlights the main themes and most important findings.

# Success criteria
- Write 2 or 3 sentences.
- Be professional, concise, and readable.
- Lead with the dominant themes from the provided digest data.
- Use only the provided digest metadata.
- Do not use bullets or headings.
"""

_WEEKLY_SUMMARY_INSTRUCTIONS = """You write the weekly overview for a critical care and emergency medicine research digest.

# Goal
Write a three-paragraph summary for clinicians.

# Success criteria
- Return exactly 3 paragraphs separated by a blank line.
- Paragraph 1 summarises the overall landscape and study-type mix.
- Paragraph 2 covers paediatric research, or states exactly: "No paediatric-focused papers are featured in this week's digest."
- Paragraph 3 highlights the 2 to 3 most important contributions and why they matter clinically.
- Use only the provided digest data.
- Do not use bullets or headings.
"""

_ANALYSIS_INSTRUCTIONS = """You are a medical research analyst for a critical care and emergency medicine digest.

# Goal
Classify each paper and produce a concise downstream-ready summary.

# Success criteria
- Return one analysis per paper in input order.
- Choose topic, study_type, and patient_group only from the allowed lists.
- research_area must be a specific 3-6 word sub-area and not a restatement of topic.
- relevance_score must be an integer from 1 to 5 based on likely clinical impact.
- summary must be 2 to 3 plain-language sentences.
- key_findings must contain 1 to 3 specific factual findings.
- Use only the provided paper content. If evidence is limited, choose the safest conservative classification instead of inventing details.

# Output
Return structured output only.
"""

_CLASSIFICATION_GUIDANCE = (
    "Allowed topic values:\n"
    + "\n".join(f"- {topic}" for topic in TOPICS)
    + "\n\nAllowed study_type values:\n"
    + "\n".join(f"- {study_type}" for study_type in STUDY_TYPES)
    + "\n\nAllowed patient_group values:\n"
    + "\n".join(f"- {patient_group}" for patient_group in PATIENT_GROUPS)
    + "\n\nRelevance score guide:\n"
    + "- 5 = major clinical breakthrough with clear patient impact\n"
    + "- 4 = important finding with near-term medical application\n"
    + "- 3 = solid research, potential healthcare relevance\n"
    + "- 2 = preliminary or methodological work\n"
    + "- 1 = marginal medical relevance"
)


class PaperAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(description="1-based paper index in the current batch.")
    topic: str
    study_type: str
    research_area: str
    patient_group: str
    relevance_score: int = Field(ge=1, le=5)
    summary: str
    key_findings: List[str]


class PaperAnalysisBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    papers: List[PaperAnalysis]


def _response_text(response) -> str:
    return (getattr(response, "output_text", "") or "").strip()


def _reasoning_config() -> Any:
    return cast(Any, {"effort": Config.LLM_REASONING_EFFORT})


def _text_config() -> Any:
    return cast(Any, {"verbosity": Config.LLM_TEXT_VERBOSITY})


def _analysis_input(papers: List[Paper]) -> str:
    papers_text = ""
    for idx, paper in enumerate(papers, start=1):
        content = paper.full_text[:5000] if paper.full_text else paper.abstract
        papers_text += (
            f"\nPaper {idx}\n"
            f"Title: {paper.title}\n"
            f"Authors: {', '.join(paper.authors[:3]) or 'Unknown'}\n"
            f"Source: {paper.source}\n"
            f"Content: {content}\n"
        )

    return f"{_CLASSIFICATION_GUIDANCE}\n\nPaper batch:{papers_text}"


class LLMProcessor:
    def __init__(self):
        if not Config.OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY is not set. Add it to your .env file."
            )
        self.client = OpenAI(api_key=Config.OPENAI_API_KEY)

    # ── public ───────────────────────────────────────────────────────────────

    def process_papers(self, papers: List[Paper]) -> List[Paper]:
        """Classify and summarise all papers using the LLM."""
        total = len(papers)
        logger.info(
            "LLM-processing %d papers with %s (batch=%d)",
            total, Config.LLM_MODEL, _BATCH,
        )
        for i in range(0, total, _BATCH):
            batch = papers[i: i + _BATCH]
            n = i // _BATCH + 1
            logger.info(
                "Batch %d/%d (%d papers)",
                n, (total + _BATCH - 1) // _BATCH, len(batch),
            )
            self._analyze_batch(batch)
            if i + _BATCH < total:
                time.sleep(1)
        return papers

    def generate_digest_intro(self, papers: List[Paper], date_str: str) -> str:
        """Short header introduction (2-3 sentences) for the email."""
        topic_counts: Dict[str, int] = {}
        high_impact: List[str] = []
        score_sum = 0

        for p in papers:
            topic_counts[p.topic] = topic_counts.get(p.topic, 0) + 1
            score_sum += p.relevance_score
            if p.relevance_score >= 4:
                high_impact.append(p.title)

        avg = score_sum / len(papers) if papers else 0
        top3 = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:3]

        prompt = (
            f"Date: {date_str}\n"
            f"Total papers: {len(papers)}\n"
            f"Average relevance score: {avg:.1f}/5\n"
            f"Top topics: {', '.join(f'{t} ({c})' for t, c in top3)}\n"
            f"Highest-impact titles: {'; '.join(high_impact[:3]) or 'none'}"
        )
        try:
            resp = self.client.responses.create(
                model=Config.LLM_MODEL,
                instructions=_DIGEST_INTRO_INSTRUCTIONS,
                input=[{"role": "user", "content": prompt}],
                reasoning=_reasoning_config(),
                text=_text_config(),
                max_output_tokens=220,
                store=False,
            )
            intro = _response_text(resp)
            if intro:
                return intro
            raise ValueError("Empty digest intro response")
        except Exception as exc:
            logger.error("Error generating digest intro: %s", exc)
            return (
                f"Today's digest covers {len(papers)} recent papers across "
                f"{len(topic_counts)} healthcare research areas."
            )

    def generate_weekly_summary(self, papers: List[Paper], date_str: str) -> str:
        """
        Generate a comprehensive weekly overview consisting of three paragraphs:
          1. General research landscape and study type distribution
          2. Paediatric-focused papers (or note if none)
          3. Key contributions / most important findings
        """
        if not papers:
            return "No new papers this week."

        topic_counter = Counter(p.topic for p in papers)
        type_counter  = Counter(p.study_type for p in papers if p.study_type)
        area_counter  = Counter(p.research_area for p in papers if p.research_area)

        top_topics = topic_counter.most_common(5)
        top_types  = type_counter.most_common(5)
        top_areas  = area_counter.most_common(5)

        paeds_papers = sorted(
            [p for p in papers if p.patient_group == "Paediatric"],
            key=lambda x: x.relevance_score, reverse=True,
        )
        paeds_block = "\n".join(
            f"  - [{p.relevance_score}/5] {p.title}\n"
            f"    Findings: {'; '.join(p.key_findings[:2])}"
            for p in paeds_papers[:5]
        ) or "  (none this week)"

        high_papers = sorted(
            [p for p in papers if p.relevance_score >= 4],
            key=lambda x: x.relevance_score,
            reverse=True,
        )[:5]
        high_block = "\n".join(
            f"  - [{p.relevance_score}/5] {p.title} ({p.source})\n"
            f"    Findings: {'; '.join(p.key_findings[:2])}"
            for p in high_papers
        ) or "  (none)"

        prompt = f"""Week: {date_str}
Total papers: {len(papers)} ({len(paeds_papers)} paediatric)
Sources: PubMed + medRxiv
Focus areas: paediatric critical care, adult intensive care, emergency medicine

Top topics:
{chr(10).join(f"- {t}: {c} paper(s)" for t, c in top_topics)}

Study type distribution:
{chr(10).join(f"- {t}: {c} paper(s)" for t, c in top_types) or "- no data"}

Specific research areas:
{chr(10).join(f"- {a}: {c} paper(s)" for a, c in top_areas) or "- no data"}

Paediatric papers:
{paeds_block}

High-impact papers (score >= 4):
{high_block}"""

        for attempt in range(2):
            try:
                resp = self.client.responses.create(
                    model=Config.LLM_MODEL,
                    instructions=_WEEKLY_SUMMARY_INSTRUCTIONS,
                    input=[{"role": "user", "content": prompt}],
                    reasoning=_reasoning_config(),
                    text=_text_config(),
                    max_output_tokens=700,
                    store=False,
                )
                summary = _response_text(resp)
                if summary:
                    return summary
                raise ValueError("Empty weekly summary response")
            except Exception as exc:
                logger.error("Error generating weekly summary (attempt %d): %s", attempt + 1, exc)
                time.sleep(_RETRY_SLEEP)

        # Fallback
        return (
            f"This week's digest covers {len(papers)} critical care and emergency medicine "
            f"papers across {len(topic_counter)} topic areas. "
            f"Leading themes include: {', '.join(t for t, _ in top_topics[:3])}."
        )

    # ── private ──────────────────────────────────────────────────────────────

    def _analyze_batch(self, papers: List[Paper]):
        """Call the LLM for one batch and update paper objects in-place."""
        user = _analysis_input(papers)

        for attempt in range(2):
            try:
                resp = self.client.responses.parse(
                    model=Config.LLM_MODEL,
                    instructions=_ANALYSIS_INSTRUCTIONS,
                    input=[{"role": "user", "content": user}],
                    text_format=PaperAnalysisBatch,
                    reasoning=_reasoning_config(),
                    max_output_tokens=5000,
                    store=False,
                )
                result = getattr(resp, "output_parsed", None)
                if result is None:
                    raise ValueError("Missing structured paper analysis output")

                analyses = result.papers
                self._apply_results(papers, analyses)
                return
            except Exception as exc:
                logger.error("LLM API error (attempt %d): %s", attempt + 1, exc)
                time.sleep(_RETRY_SLEEP)

        self._apply_defaults(papers)

    def _apply_results(self, papers: List[Paper], analyses: list):
        for item in analyses:
            idx = item.index - 1
            if 0 <= idx < len(papers):
                papers[idx].topic = item.topic or "Other Healthcare Topics"
                papers[idx].study_type = item.study_type or "Other / Unclear"
                papers[idx].research_area = item.research_area or ""
                papers[idx].patient_group = item.patient_group or "No human subjects"
                papers[idx].relevance_score = item.relevance_score or 3
                papers[idx].summary = item.summary or ""
                papers[idx].key_findings = item.key_findings or []
        self._apply_defaults([p for p in papers if not p.topic])

    def _apply_defaults(self, papers: List[Paper]):
        for p in papers:
            if not p.topic:
                p.topic         = "Other Healthcare Topics"
                p.study_type    = "Other / Unclear"
                p.research_area = ""
                p.patient_group = "No human subjects"
                p.relevance_score = 3
                p.summary = (p.abstract[:400] + "...") if len(p.abstract) > 400 else p.abstract
                p.key_findings  = []
