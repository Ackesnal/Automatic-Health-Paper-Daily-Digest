from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Paper:
    title: str
    authors: List[str]
    abstract: str
    url: str
    pdf_url: str
    source: str          # 'medRxiv' or 'PubMed'
    published: datetime
    paper_id: str
    journal: str = ""    # journal / venue name as returned by the source API

    # Filled after LLM processing
    topic: str = ""
    study_type: str = ""        # e.g. RCT, Systematic Review, Observational Study …
    research_area: str = ""     # specific sub-area, e.g. "Diabetes Management"
    patient_group: str = ""     # Paediatric / Neonatal / Adult / Mixed / No human subjects
    care_setting: str = ""      # Intensive Care / Emergency Department / Both / Other
    importance_score: int = 0
    summary: str = ""
    key_findings: List[str] = field(default_factory=list)
    full_text: Optional[str] = None

    def __post_init__(self):
        # Cap abstract length to avoid excessive token usage
        if len(self.abstract) > 2000:
            self.abstract = self.abstract[:2000] + "..."
