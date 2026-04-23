import io
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_MAX_PAGES = 12          # pages to read per PDF
_MAX_CHARS = 15_000      # chars to pass to the LLM
_TIMEOUT = 60


def extract_text_from_pdf_url(pdf_url: str) -> Optional[str]:
    """Download a PDF and return extracted plain text, or None on failure."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; MedicalPaperDigest/1.0; Academic Research)"
        )
    }
    try:
        logger.info("Downloading PDF: %s", pdf_url)
        r = requests.get(pdf_url, headers=headers, timeout=_TIMEOUT)
        r.raise_for_status()
        return _extract_from_bytes(r.content)
    except requests.RequestException as exc:
        logger.warning("Failed to download PDF %s: %s", pdf_url, exc)
        return None


def _extract_from_bytes(pdf_bytes: bytes) -> Optional[str]:
    try:
        import pdfplumber  # imported lazily so it is only required when PDFs are enabled

        parts = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= _MAX_PAGES:
                    break
                text = page.extract_text()
                if text:
                    parts.append(text)

        if not parts:
            return None

        full = "\n\n".join(parts)
        if len(full) > _MAX_CHARS:
            full = full[:_MAX_CHARS] + "\n... [truncated]"
        return full

    except Exception as exc:
        logger.warning("PDF text extraction failed: %s", exc)
        return None
