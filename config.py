import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # LLM
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-5.5")
    LLM_REASONING_EFFORT: str = os.getenv("LLM_REASONING_EFFORT", "low")
    LLM_TEXT_VERBOSITY: str = os.getenv("LLM_TEXT_VERBOSITY", "low")

    # Email
    EMAIL_SENDER: str = os.getenv("EMAIL_SENDER", "")
    EMAIL_PASSWORD: str = os.getenv("EMAIL_PASSWORD", "")
    # Comma-separated list of recipient addresses, e.g. "a@x.com,b@y.com"
    EMAIL_RECIPIENT: str = os.getenv("EMAIL_RECIPIENT", "")
    SMTP_SERVER: str = os.getenv("SMTP_SERVER", "smtp.gmail.com")

    @classmethod
    def email_recipients(cls) -> list:
        """Return EMAIL_RECIPIENT split on commas, stripped of whitespace."""
        return [r.strip() for r in cls.EMAIL_RECIPIENT.split(",") if r.strip()]
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    # Optional logo URL shown in email header (leave empty to use emoji only)
    EMAIL_LOGO_URL: str = os.getenv("EMAIL_LOGO_URL", "")

    # Fetch
    MAX_PAPERS_MEDRXIV: int = int(os.getenv("MAX_PAPERS_MEDRXIV", "30"))
    MAX_PAPERS_PUBMED: int = int(os.getenv("MAX_PAPERS_PUBMED", "20"))
    DAYS_BACK: int = int(os.getenv("DAYS_BACK", "1"))

    # Scheduling
    SCHEDULE_TIME: str = os.getenv("SCHEDULE_TIME", "08:00")

    # PubMed
    PUBMED_EMAIL: str = os.getenv("PUBMED_EMAIL", os.getenv("EMAIL_RECIPIENT", ""))

    # Search queries
    PUBMED_SEARCH_QUERY: str = os.getenv(
        "PUBMED_SEARCH_QUERY",
        (
            "healthcare OR medicine OR clinical OR diagnosis OR patient"
        ),
    )

    # PDF
    DOWNLOAD_PDFS: bool = os.getenv("DOWNLOAD_PDFS", "false").lower() == "true"
    MAX_PDF_PAPERS: int = int(os.getenv("MAX_PDF_PAPERS", "5"))
