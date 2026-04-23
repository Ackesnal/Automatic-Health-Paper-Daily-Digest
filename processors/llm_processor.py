import json
import logging
import time
from collections import Counter
from typing import Dict, List

from openai import OpenAI

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

_BATCH = 6          # papers per LLM call
_RETRY_SLEEP = 5    # seconds between retries


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
            f"You are a medical research editor writing a concise header introduction "
            f"for a daily healthcare research email digest.\n\n"
            f"Date: {date_str}\n"
            f"Total papers: {len(papers)}\n"
            f"Average relevance score: {avg:.1f}/5\n"
            f"Top topics: {', '.join(f'{t} ({c})' for t, c in top3)}\n"
            f"Highest-impact titles: {'; '.join(high_impact[:3]) or 'none'}\n\n"
            "Write 2-3 sentences that highlight today's key themes and most "
            "significant findings. Be concise and informative."
        )
        try:
            resp = self.client.chat.completions.create(
                model=Config.LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_completion_tokens=600,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            logger.error("Error generating digest intro: %s", exc)
            return (
                f"Today's digest covers {len(papers)} recent papers across "
                f"{len(topic_counts)} healthcare research areas."
            )

    def generate_daily_summary(self, papers: List[Paper], date_str: str) -> str:
        """
        Generate a comprehensive daily overview covering:
          - overall landscape of today's research
          - distribution by topic and study type
          - most significant findings
          - emerging trends or notable patterns
        """
        if not papers:
            return "No new papers today."

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
        ) or "  (none today)"

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

        prompt = f"""You are a senior medical research editor. Write a structured daily overview for today's healthcare research digest, consisting of exactly THREE paragraphs separated by a blank line.

Date: {date_str}
Total papers: {len(papers)} ({len(paeds_papers)} paediatric)
Sources: PubMed + medRxiv

[Top Topics (up to 5)]
{chr(10).join(f"  {t}: {c} paper(s)" for t, c in top_topics)}

[Study Type Distribution (up to 5)]
{chr(10).join(f"  {t}: {c} paper(s)" for t, c in top_types) or "  (no data)"}

[Specific Research Areas (up to 5)]
{chr(10).join(f"  {a}: {c} paper(s)" for a, c in top_areas) or "  (no data)"}

[Paediatric Papers]
{paeds_block}

[High-Impact Papers (score >= 4)]
{high_block}

Write EXACTLY three paragraphs:

PARAGRAPH 1 (100-150 words): General landscape summary. Cover the dominant topics, distribution of study types (e.g. proportion of RCTs, reviews, observational studies), and overall breadth of today's research.

PARAGRAPH 2 (60-100 words): Paediatric research focus. If there are paediatric papers, summarise their topics and key findings. If there are none, state clearly: "No paediatric-focused papers are featured in today's digest."

PARAGRAPH 3 (80-120 words): Key contributions. Highlight the core findings of the 2-3 most important papers (highest relevance score), explaining their significance for clinical practice.

Use clear, professional language aimed at healthcare practitioners. Do not use headers or bullet points."""

        for attempt in range(2):
            try:
                resp = self.client.chat.completions.create(
                    model=Config.LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.5,
                    max_completion_tokens=1000,
                )
                return resp.choices[0].message.content.strip()
            except Exception as exc:
                logger.error("Error generating daily summary (attempt %d): %s", attempt + 1, exc)
                time.sleep(_RETRY_SLEEP)

        # Fallback
        return (
            f"Today's digest covers {len(papers)} healthcare research papers across "
            f"{len(topic_counter)} topic areas. "
            f"Leading themes include: {', '.join(t for t, _ in top_topics[:3])}."
        )

    # ── private ──────────────────────────────────────────────────────────────

    def _analyze_batch(self, papers: List[Paper]):
        """Call the LLM for one batch and update paper objects in-place."""
        papers_text = ""
        for idx, p in enumerate(papers, start=1):
            content = p.full_text[:3000] if p.full_text else p.abstract
            papers_text += (
                f"\n--- Paper {idx} ---\n"
                f"Title: {p.title}\n"
                f"Authors: {', '.join(p.authors[:3]) or 'Unknown'}\n"
                f"Source: {p.source}\n"
                f"Content: {content}\n"
            )

        system = (
            "You are a medical research analyst. "
            "Analyse the provided papers and return ONLY valid JSON."
        )
        user = f"""Analyse these {len(papers)} medical/healthcare research papers and return a JSON object.

{papers_text}

Return exactly this structure:
{{
  "papers": [
    {{
      "index": 1,
      "topic": "<topic from TOPICS list>",
      "study_type": "<study type from STUDY_TYPES list>",
      "research_area": "<specific sub-area in 3-6 words, e.g. 'Type 2 Diabetes Management'>",
      "patient_group": "<patient group from PATIENT_GROUPS list>",
      "relevance_score": <integer 1-5>,
      "summary": "<2-3 sentence plain-language summary>",
      "key_findings": ["<finding 1>", "<finding 2>", "<finding 3>"]
    }}
  ]
}}

TOPICS (pick the single best match):
{json.dumps(TOPICS)}

STUDY_TYPES (pick the single best match):
{json.dumps(STUDY_TYPES)}

PATIENT_GROUPS (pick the single best match):
{json.dumps(PATIENT_GROUPS)}

Relevance scoring:
  5 = major clinical breakthrough with clear patient impact
  4 = important finding with near-term medical application
  3 = solid research, potential healthcare relevance
  2 = preliminary / methodological work
  1 = marginal medical relevance

Rules:
- Provide exactly {len(papers)} objects in the same order as input.
- research_area must be specific (not a repeat of topic).
- patient_group: choose 'Paediatric' only if the study explicitly focuses on children/adolescents (<18 yrs); choose 'No human subjects' for animal/in vitro/computational studies; otherwise 'Adult' or 'Mixed / All Ages'.
- summary must be readable by a non-specialist.
- key_findings should be specific, factual statements."""

        for attempt in range(2):
            try:
                resp = self.client.chat.completions.create(
                    model=Config.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_completion_tokens=5000
                )
                result = json.loads(resp.choices[0].message.content)
                analyses = result.get("papers", [])
                self._apply_results(papers, analyses)
                return
            except json.JSONDecodeError as exc:
                logger.warning("JSON decode error (attempt %d): %s", attempt + 1, exc)
                time.sleep(_RETRY_SLEEP)
            except Exception as exc:
                logger.error("LLM API error (attempt %d): %s", attempt + 1, exc)
                time.sleep(_RETRY_SLEEP)

        self._apply_defaults(papers)

    def _apply_results(self, papers: List[Paper], analyses: list):
        for item in analyses:
            idx = int(item.get("index", 1)) - 1
            if 0 <= idx < len(papers):
                papers[idx].topic          = item.get("topic", "Other Healthcare Topics")
                papers[idx].study_type     = item.get("study_type", "Other / Unclear")
                papers[idx].research_area  = item.get("research_area", "")
                papers[idx].patient_group  = item.get("patient_group", "No human subjects")
                papers[idx].relevance_score = int(item.get("relevance_score", 3))
                papers[idx].summary        = item.get("summary", "")
                papers[idx].key_findings   = item.get("key_findings", [])
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
