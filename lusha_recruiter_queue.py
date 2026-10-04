import argparse
import json
import sqlite3
from pathlib import Path

from agent_hr import ROOT, ensure_database
DB = ROOT / "agent_hr.sqlite3"
QUEUE_PATH = ROOT / "logs" / "lusha_recruiter_queue.jsonl"


TARGET_TITLES = [
    "Talent Acquisition",
    "Recruiter",
    "HR Business Partner",
    "Compliance Manager",
    "Risk Manager",
    "AML Manager",
    "KYC Manager",
    "Financial Crime Manager",
]


def queue_missing_recruiters(limit=10):
    ensure_database()
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    queued = []
    with sqlite3.connect(DB) as conn:
        rows = conn.execute(
            """
            SELECT jobs.id, jobs.company, jobs.title, jobs.location, jobs.source_url
            FROM jobs
            JOIN applications ON applications.job_id = jobs.id
            WHERE jobs.score >= 60
              AND jobs.contact_email = ''
              AND jobs.company <> ''
              AND jobs.company <> 'A verifier'
              AND jobs.status NOT IN ('closed', 'rejected', 'rejected_by_quality')
              AND applications.status IN (
                  'proposed', 'validated', 'contact_review',
                  'contact_confirmed', 'manual_action_required'
              )
              AND NOT EXISTS (
                  SELECT 1 FROM recruiter_contacts
                  WHERE LOWER(recruiter_contacts.company) = LOWER(jobs.company)
                    AND recruiter_contacts.email <> ''
              )
            ORDER BY jobs.score DESC, jobs.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    for job_id, company, title, location, url in rows:
        queued.append(
            {
                "job_id": job_id,
                "company": company,
                "job_title": title,
                "location": location,
                "source_url": url,
                "target_titles": TARGET_TITLES,
                "status": "queued",
            }
        )

    previous = QUEUE_PATH.read_text(encoding="utf-8") if QUEUE_PATH.exists() else ""
    current = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in queued)
    if current == previous:
        return []
    QUEUE_PATH.write_text(current, encoding="utf-8")
    return queued


def main():
    parser = argparse.ArgumentParser(description="Queue recruiter lookups for Lusha.")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(queue_missing_recruiters(limit=args.limit), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
