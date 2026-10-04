import argparse
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from job_analysis import analyse_job, compact_analysis


ROOT = Path(__file__).resolve().parent
DB = ROOT / "agent_hr.sqlite3"


@dataclass
class JobInput:
    source: str
    source_url: str
    title: str
    company: str
    location: str
    description: str
    contact_email: str = ""
    application_channel: str = "unknown"
    page_verified: bool = False


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(text):
    return re.sub(r"\s+", " ", text or "").strip().lower()


def contains_any(text, terms):
    original = text or ""
    haystack = normalize(text)
    exact_tokens = {"aml", "kyc", "vie", "cdi", "cdd", "sql", "hr"}
    for term in terms:
        needle = normalize(term)
        if needle == "vie":
            if re.search(r"(?<!\w)V\.?I\.?E\.?(?!\w)", original):
                return True
        elif needle in exact_tokens:
            if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
                return True
        elif needle in haystack:
            return True
    return False


def score_job(job, rules):
    analysis = analyse_job(job.title, job.company, job.location, job.description)
    return analysis["score"], analysis["reasons"], analysis["risks"]


def connect():
    return sqlite3.connect(DB)


def ensure_database():
    from init_agent_db import initialize_database

    initialize_database()


def save_job(job, score):
    ensure_database()
    analysis = analyse_job(job.title, job.company, job.location, job.description)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO jobs(source, source_url, title, company, location, description, score, status, contact_email, application_channel, analysis_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_url) DO UPDATE SET
                title=excluded.title,
                company=excluded.company,
                location=excluded.location,
                description=excluded.description,
                score=excluded.score,
                contact_email=excluded.contact_email,
                application_channel=excluded.application_channel,
                analysis_json=excluded.analysis_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                job.source,
                job.source_url,
                job.title,
                job.company,
                job.location,
                job.description,
                score,
                "scored",
                job.contact_email,
                job.application_channel,
                compact_analysis(analysis),
            ),
        )
        job_id = conn.execute("SELECT id FROM jobs WHERE source_url=?", (job.source_url,)).fetchone()[0]
        conn.execute(
            "INSERT INTO events(event_type, detail) VALUES(?,?)",
            ("job_scored", json.dumps({"url": job.source_url, "score": score}, ensure_ascii=False)),
        )
        return job_id


def telegram_proposal(job, score, reasons, risks, rules):
    recommendation = "A valider" if score >= rules["minimum_score_to_propose"] else "A ignorer"
    risk_text = ", ".join(risks) if risks else "Aucun risque majeur detecte"
    reason_text = ", ".join(reasons[:5]) if reasons else "Match faible"
    return (
        f"Offre detectee pour Candidate\n"
        f"{job.title} - {job.company}\n"
        f"Lieu: {job.location}\n"
        f"Score: {score}/100\n"
        f"Pourquoi ca matche: {reason_text}\n"
        f"Points de vigilance: {risk_text}\n"
        f"Action proposee: {recommendation}\n"
        f"Lien: {job.source_url}\n\n"
        f"Repondez OUI pour preparer/envoyer si le canal le permet, NON pour rejeter."
    )


def demo_score():
    ensure_database()
    rules = load_json(ROOT / "config" / "scoring_rules.json")
    job = JobInput(
        source="demo",
        source_url="https://example.com/demo-compliance-analyst-luxembourg",
        title="Junior Compliance Analyst AML/KYC",
        company="Example Bank Luxembourg",
        location="Luxembourg",
        description="Compliance analyst role focused on AML, KYC, due diligence, regulatory monitoring, English and French.",
    )
    score, reasons, risks = score_job(job, rules)
    save_job(job, score)
    print(telegram_proposal(job, score, reasons, risks, rules))


def main():
    parser = argparse.ArgumentParser(description="Agent HR local helper for Candidate job applications.")
    parser.add_argument("--demo-score", action="store_true", help="Score a demo offer and save it in the database.")
    args = parser.parse_args()
    if args.demo_score:
        demo_score()
    else:
        print("Agent HR ready. Use --demo-score for a local smoke test.")


if __name__ == "__main__":
    main()
