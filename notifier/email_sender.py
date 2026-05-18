import logging
import smtplib
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List

from config import Config
from models import Paper
from processors.llm_processor import TOPICS

logger = logging.getLogger(__name__)

# ── Topic colour palette ────────────────────────────────────────────────────

_TOPIC_COLORS: Dict[str, str] = {
    "Clinical Research & Trials":           "#1565C0",
    "Medical AI & Machine Learning":        "#6A1B9A",
    "Drug Discovery & Pharmacology":        "#E65100",
    "Genomics & Precision Medicine":        "#00695C",
    "Medical Imaging & Diagnostics":        "#0277BD",
    "Public Health & Epidemiology":         "#2E7D32",
    "Cardiology & Cardiovascular Disease":  "#C62828",
    "Oncology & Cancer Research":           "#4E342E",
    "Infectious Diseases":                  "#BF360C",
    "Neurology & Brain Disorders":          "#283593",
    "Surgery & Procedures":                 "#37474F",
    "Mental Health & Psychiatry":           "#880E4F",
    "Other Healthcare Topics":              "#546E7A",
}


def _color(topic: str) -> str:
    return _TOPIC_COLORS.get(topic, "#546E7A")


def _stars(score: int) -> str:
    filled = "&#9733;" * max(0, min(score, 5))
    empty  = "&#9734;" * (5 - max(0, min(score, 5)))
    return (
        f'<span style="color:#FFA000;">{filled}</span>'
        f'<span style="color:#BDBDBD;">{empty}</span>'
    )


_TOPIC_ORDER = {topic: index for index, topic in enumerate(TOPICS)}


def _ordered_topics(topics: List[str]) -> List[str]:
    return sorted(
        topics,
        key=lambda topic: (_TOPIC_ORDER.get(topic, len(_TOPIC_ORDER)), topic),
    )


# ── HTML builders ────────────────────────────────────────────────────────────

# ── Study-type badge colours ────────────────────────────────────────────────
_TYPE_BADGE: Dict[str, str] = {
    "Randomized Controlled Trial (RCT)":     "#2E7D32",
    "Systematic Review / Meta-Analysis":     "#1565C0",
    "Observational Study":                   "#E65100",
    "Cohort Study":                          "#00695C",
    "Cross-Sectional Study":                 "#6A1B9A",
    "Case Report / Case Series":             "#BF360C",
    "Computational / Modeling Study":        "#37474F",
    "Laboratory / In Vitro Study":           "#4E342E",
    "Clinical Guidelines / Review Article": "#0277BD",
    "Other / Unclear":                       "#757575",
}

_PATIENT_BADGE: Dict[str, str] = {
    "Paediatric":        "#E65100",   # deep orange
    "Adult":             "#1565C0",   # blue
    "Mixed / All Ages":  "#546E7A",   # blue-grey
    "No human subjects":    "#757575",   # grey
}


def _badge(text: str, bg: str) -> str:
    return (
        f'<span style="background:{bg};color:#fff;font-size:10px;font-weight:600;'
        f'padding:2px 7px;border-radius:10px;white-space:nowrap;">{text}</span>'
    )


def _paper_card(paper: Paper) -> str:
    color = _color(paper.topic)
    authors = ", ".join(paper.authors[:3])
    if len(paper.authors) > 3:
        authors += " et al."

    # Study type + research area badges
    badges = ""
    if paper.study_type:
        tc = _TYPE_BADGE.get(paper.study_type, "#757575")
        badges += _badge(paper.study_type, tc) + " "
    if paper.research_area:
        badges += _badge(paper.research_area, color) + " "
    if paper.patient_group:
        pg_color = _PATIENT_BADGE.get(paper.patient_group, "#757575")
        badges += _badge(paper.patient_group, pg_color)

    kf_html = ""
    if paper.key_findings:
        items = "".join(
            f'<li style="margin:4px 0;color:#424242;">{f}</li>'
            for f in paper.key_findings[:3]
        )
        kf_html = (
            '<div style="margin-top:10px;">'
            '<span style="font-size:11px;font-weight:bold;color:#757575;'
            'text-transform:uppercase;letter-spacing:0.5px;">Key Findings</span>'
            f'<ul style="margin:6px 0 0 0;padding-left:18px;font-size:13px;">{items}</ul>'
            "</div>"
        )

    pdf_link = ""
    if paper.pdf_url:
        pdf_link = (
            f' &nbsp;<a href="{paper.pdf_url}" '
            f'style="color:{color};text-decoration:none;font-size:11px;">'
            "&#128462; PDF</a>"
        )

    pub_str = paper.published.strftime("%Y-%m-%d") if paper.published else ""

    return f"""
<div style="background:#fff;border:1px solid #E0E0E0;border-left:4px solid {color};
            border-radius:4px;padding:16px;margin-bottom:12px;">
  <a href="{paper.url}"
     style="color:{color};text-decoration:none;font-size:15px;font-weight:600;line-height:1.5;
            display:block;margin-bottom:8px;">
    {paper.title}
  </a>
  <div style="font-size:12px;color:#757575;margin-bottom:8px;">
    <span style="margin-right:10px;">&#128100; {authors}</span>
    <span style="margin-right:10px;">&#128196; {paper.source}</span>
    <span style="margin-right:10px;">&#128197; {pub_str}</span>
    <span>{_stars(paper.relevance_score)}</span>
    {pdf_link}
  </div>
  <div style="margin-bottom:10px;">{badges}</div>
  <p style="font-size:13px;color:#424242;line-height:1.6;margin:0;">
    {paper.summary or paper.abstract[:350]}
  </p>
  {kf_html}
</div>"""


def _topics_distribution_chart(papers: List[Paper]) -> str:
    """Topic distribution bar chart with no surrounding description text."""
    from collections import Counter
    counts = Counter(p.topic for p in papers if p.topic)
    if not counts:
        return ""
    total = len(papers)
    rows = ""
    for topic in _ordered_topics(list(counts.keys())):
        cnt = counts[topic]
        pct = cnt / total * 100
        bar_w = max(4, int(pct * 2))  # scale to ~200px max
        bg = _color(topic)
        rows += f"""
<tr>
  <td style="font-size:12px;color:#424242;padding:4px 10px 4px 0;white-space:nowrap;">{topic}</td>
  <td style="padding:4px 8px;">
    <div style="background:{bg};height:12px;width:{bar_w}px;border-radius:3px;display:inline-block;"></div>
  </td>
  <td style="font-size:12px;color:#757575;padding:4px 0;">{cnt} ({pct:.0f}%)</td>
</tr>"""
    return f'<table cellpadding="0" cellspacing="0" width="100%">{rows}</table>'


def _build_html(papers: List[Paper], weekly_summary: str, date_str: str) -> str:
    # Split by patient group first
    paeds_all = sorted(
        [p for p in papers if p.patient_group == "Paediatric"],
        key=lambda x: x.relevance_score, reverse=True,
    )
    adult_all = [p for p in papers if p.patient_group != "Paediatric"]

    # ── Paediatric section (no topic subdivision) ────────────────────────────
    if paeds_all:
        paeds_cards = "".join(_paper_card(p) for p in paeds_all)
        plural_p = "s" if len(paeds_all) > 1 else ""
        paeds_html = f"""
<div style="margin-bottom:32px;">
  <div style="font-size:17px;font-weight:700;color:#1565C0;margin-bottom:16px;">
    &#128118; Paediatric Papers ({len(paeds_all)})
  </div>
  {paeds_cards}
</div>"""
    else:
        paeds_html = """
<div style="margin-bottom:32px;">
  <div style="background:#E65100;color:#fff;padding:10px 16px;border-radius:4px;margin-bottom:12px;">
    <span style="font-size:15px;font-weight:600;">&#128118; Paediatric Papers</span>
    <span style="font-size:12px;opacity:0.85;margin-left:8px;">(0 papers)</span>
  </div>
  <p style="color:#9E9E9E;font-size:13px;font-style:italic;margin:0;">
    No paediatric papers in this week's digest.
  </p>
</div>"""

    # ── Adult / General section grouped by TOPICS ────────────────────────────
    by_topic: Dict[str, List[Paper]] = defaultdict(list)
    for p in adult_all:
        by_topic[p.topic].append(p)
    for lst in by_topic.values():
        lst.sort(key=lambda x: x.relevance_score, reverse=True)
    sorted_topics = [
      (topic, by_topic[topic])
      for topic in _ordered_topics(list(by_topic.keys()))
    ]

    adult_topics_html = ""
    for topic, lst in sorted_topics:
        c = _color(topic)
        plural = "s" if len(lst) > 1 else ""
        cards = "".join(_paper_card(p) for p in lst)
        adult_topics_html += f"""
<div style="margin-bottom:28px;">
  <div style="background:{c};color:#fff;padding:10px 16px;border-radius:4px;margin-bottom:12px;">
    <span style="font-size:15px;font-weight:600;">{topic}</span>
    <span style="font-size:12px;opacity:0.85;margin-left:8px;">({len(lst)} paper{plural})</span>
  </div>
  {cards}
</div>"""

    adult_section_header = f"""
<div style="border-top:2px solid #E0E0E0;padding-top:20px;margin-bottom:20px;">
  <div style="font-size:17px;font-weight:700;color:#1565C0;margin-bottom:16px;">
    &#128100; Adult / General Papers ({len(adult_all)})
  </div>
  {adult_topics_html}
</div>"""

    topics_html = paeds_html + adult_section_header

    high = sum(1 for p in papers if p.relevance_score >= 4)
    topics_dist_html = _topics_distribution_chart(papers)
    _para_style = "font-size:14px;color:#1B5E20;line-height:1.9;margin:0 0 12px 0;"
    summary_paras_html = "".join(
        f'<p style="{_para_style}">{para.strip()}</p>'
        for para in weekly_summary.split("\n\n")
        if para.strip()
    )

    # Stats bar uses a table for broad email-client compatibility
    stats_table = f"""
<table width="100%" cellpadding="12" cellspacing="0"
       style="background:#C6B3D9;border:1px solid #7A5899;border-top:none;">
  <tr>
    <td width="33%" align="center" style="border-right:1px solid #7A5899;">
      <div style="font-size:26px;font-weight:700;color:#51247A;">{len(papers)}</div>
      <div style="font-size:13px;color:#51247A;font-weight:700;">TOTAL PAPERS</div>
    </td>
    <td width="33%" align="center" style="border-right:1px solid #7A5899;">
      <div style="font-size:26px;font-weight:700;color:#51247A;">{len(by_topic)}</div>
      <div style="font-size:13px;color:#51247A;font-weight:700;">TOPIC AREAS</div>
    </td>
    <td width="34%" align="center">
      <div style="font-size:26px;font-weight:700;color:#51247A;">{high}</div>
      <div style="font-size:13px;color:#51247A;font-weight:700;">HIGH-IMPACT (&#9733;&#9733;&#9733;&#9733;+)</div>
    </td>
  </tr>
</table>"""

    logo_html = ""
    if Config.EMAIL_LOGO_URL:
        logo_html = (
            f'<img src="{Config.EMAIL_LOGO_URL}" alt="Logo" '
            f'style="height:48px;width:auto;margin-bottom:10px;display:block;margin-left:auto;margin-right:auto;">'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Medical Research Digest &ndash; {date_str}</title>
</head>
<body style="margin:0;padding:0;background:#F5F5F5;
             font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:800px;margin:0 auto;padding:20px;">

  <!-- Header: table+bgcolor for Outlook/Gmail compatibility (CSS gradients not supported) -->
  <table width="100%" cellpadding="0" cellspacing="0"
         style="border-radius:8px 8px 0 0;overflow:hidden;">
    <tr>
      <td bgcolor="#51247A" align="center"
          style="background:#51247A;padding:24px 28px;
                 border-radius:8px 8px 0 0;text-align:center;">
        {logo_html}
        <h1 style="margin:0 0 6px 0;font-size:25px;color:#ffffff;
                   font-family:Arial,Helvetica,sans-serif;">
          Medical Research Weekly Digest
        </h1>
        <p style="margin:0;font-size:17px;color:#ffffff;opacity:.9;">{date_str}</p>
      </td>
    </tr>
  </table>

  {stats_table}

  <!-- Topics Distribution -->
  <div style="background:#fff;border:1px solid #E0E0E0;border-top:none;padding:16px 24px;">
    {topics_dist_html}
  </div>

  <!-- Weekly Summary -->
  <div style="background:#E8F5E9;border:1px solid #C8E6C9;border-top:none;padding:20px 24px;">
    <div style="font-size:17px;font-weight:700;color:#2E7D32;margin-bottom:10px;">
      &#128221; Weekly Overview
    </div>
    {summary_paras_html}
  </div>

  <!-- Papers by topic -->
  <div style="background:#fff;border:1px solid #E0E0E0;border-top:none;
              border-radius:0 0 8px 8px;padding:24px;">
    {topics_html}
  </div>

  <!-- Footer -->
  <div style="text-align:center;padding:18px;color:#9E9E9E;font-size:11px;">
    <p style="margin:0;">
      Generated by ChIRP Medical Paper Digest &nbsp;|&nbsp;
      <a href="https://pubmed.ncbi.nlm.nih.gov" style="color:#9E9E9E;">PubMed</a> &nbsp;|&nbsp;
      <a href="https://www.medrxiv.org" style="color:#9E9E9E;">medRxiv</a>
    </p>
    <p style="margin:6px 0 0 0;">
      Automated digest – Always verify information from original sources!
    </p>
  </div>

</div>
</body>
</html>"""


# ── Public API ───────────────────────────────────────────────────────────────

def send_email(papers: List[Paper], weekly_summary: str, date_str: str) -> bool:
    """Build and send the HTML digest email. Returns True on success."""
    if not papers:
        logger.warning("No papers to email \u2013 skipping.")
        return False

    html = _build_html(papers, weekly_summary, date_str)

    recipients = Config.email_recipients()
    if not recipients:
        logger.error("No recipients configured. Set EMAIL_RECIPIENT in .env.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"ChIRP Medical Research Digest | {date_str} | {len(papers)} papers"
    msg["From"] = Config.EMAIL_SENDER
    msg["To"] = ", ".join(recipients)

    # Plain-text fallback
    plain = f"ChIRP Medical Research Digest – {date_str}\n{len(papers)} papers\n\n"
    for p in papers[:15]:
        plain += f"[{p.source}] {p.title}\n{p.url}\n\n"

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        logger.info("Connecting to %s:%s …", Config.SMTP_SERVER, Config.SMTP_PORT)
        with smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT, timeout=30) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(Config.EMAIL_SENDER, Config.EMAIL_PASSWORD)
            srv.sendmail(Config.EMAIL_SENDER, recipients, msg.as_string())
        logger.info("Email sent to %s", ", ".join(recipients))
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "SMTP authentication failed. "
            "Check EMAIL_SENDER / EMAIL_PASSWORD in .env. "
            "For Gmail use an App Password."
        )
        return False
    except smtplib.SMTPResponseException as exc:
        # A 2xx code means the server accepted the message — treat as success.
        # This can happen when Ctrl+C interrupts the connection after sendmail()
        # already received a 250 OK, causing smtplib to raise instead of return.
        if 200 <= exc.smtp_code < 300:
            logger.info(
                "Email sent to %s (SMTP %d – success despite exception)",
                ", ".join(recipients), exc.smtp_code,
            )
            return True
        logger.error("Email sending failed (SMTP %d): %s", exc.smtp_code, exc.smtp_error)
        return False
    except Exception as exc:
        logger.error("Email sending failed: %s", exc)
        return False


def save_html_report(papers: List[Paper], weekly_summary: str, date_str: str, path: str):
    """Fallback: save the HTML digest to a local file."""
    html = _build_html(papers, weekly_summary, date_str)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("HTML report saved → %s", path)
