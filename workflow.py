import argparse
import json
import sqlite3
from pathlib import Path

from agent_hr import JobInput, ROOT, score_job, save_job, telegram_proposal
from job_status_checker import check_job_is_open
from job_analysis import analyse_job
from job_intelligence import clean_job_title
from recruiter_contacts import find_recruiter_for_company
from telegram_client import send_telegram_message


DB = ROOT / "agent_hr.sqlite3"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def queue_for_human_review(job_id, job, score, reason, reasons, risks):
    with sqlite3.connect(DB) as conn:
        existing = conn.execute(
            """
            SELECT id FROM applications
            WHERE job_id=? AND status IN (
                'review_required', 'proposed', 'validated', 'contact_review',
                'contact_confirmed', 'manual_action_required', 'sent'
            )
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE applications
                SET status='review_required', score=?, notes=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=? AND status IN ('proposed', 'review_required')
                """,
                (score, reason, existing[0]),
            )
            return {"proposed": False, "score": score, "reason": "already_pending"}
        conn.execute(
            "UPDATE jobs SET status='needs_review', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (job_id,),
        )
        conn.execute(
            """
            INSERT INTO applications(job_id, channel, status, score, notes)
            VALUES(?,?,?,?,?)
            """,
            (job_id, "telegram_review", "review_required", score, reason),
        )
        app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    reason_text = ", ".join(reasons[:3]) if reasons else "match potentiel a verifier"
    risk_text = ", ".join(risks) if risks else "aucun risque majeur detecte"
    send_telegram_message(
        f"Candidate, cette offre merite ton regard mais certaines informations sont incompletes.\n\n"
        f"App {app_id} - {clean_job_title(job.title)}\n"
        f"Entreprise: {job.company or 'a verifier'}\n"
        f"Lieu: {job.location}\n"
        f"Match estime: {score}/100\n"
        f"Pourquoi je ne la jette pas: {reason_text}\n"
        f"A verifier: {reason}; {risk_text}\n"
        f"Lien: {job.source_url}\n\n"
        f"Repondre: oui {app_id} pour continuer, non {app_id} pour l'ecarter."
    )
    return {"proposed": True, "score": score, "reason": "human_review"}


def propose_job(job):
    rules = load_json(ROOT / "config" / "scoring_rules.json")
    analysis = analyse_job(job.title, job.company, job.location, job.description)
    score, reasons, risks = analysis["score"], analysis["reasons"], analysis["risks"]
    job_id = save_job(job, score)

    with sqlite3.connect(DB) as conn:
        stored_status = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    if stored_status == "closed":
        return {"proposed": False, "score": score, "reason": "previously_closed"}

    open_check = check_job_is_open(job.source_url, job.description, job.page_verified)
    if open_check["status"] == "closed":
        with sqlite3.connect(DB) as conn:
            conn.execute("UPDATE jobs SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", ("closed", job_id))
            conn.execute(
                "INSERT INTO events(event_type, detail) VALUES(?,?)",
                ("job_rejected_closed", json.dumps({"url": job.source_url, "reason": open_check["reason"]}, ensure_ascii=False)),
            )
        return {"proposed": False, "score": score, "reason": "closed"}
    if open_check["status"] == "unknown":
        risks.append("Ouverture de l'offre non confirmee automatiquement: verifier le lien")

    unknown_company = not job.company or job.company.strip().lower() in {
        "a verifier",
        "a vérifier",
        "unknown",
        "n/a",
    }
    if unknown_company:
        if score >= rules.get("minimum_score_to_review", 45):
            return queue_for_human_review(
                job_id, job, score, "entreprise non identifiee automatiquement", reasons, risks
            )
        with sqlite3.connect(DB) as conn:
            conn.execute("UPDATE jobs SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", ("rejected_by_quality", job_id))
            conn.execute(
                "UPDATE applications SET status='rejected_by_quality', score=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE job_id=? AND status IN ('proposed', 'review_required')",
                (score, job_id),
            )
        return {"proposed": False, "score": score, "reason": "unknown_company_low_score"}

    if not analysis["eligible_for_proposal"] and score >= rules.get("minimum_score_to_review", 35):
        return queue_for_human_review(
            job_id, job, score, "ecart de seniorite ou critere obligatoire", reasons, risks
        )

    if score < rules["minimum_score_to_propose"]:
        if score >= rules.get("minimum_score_to_review", 45):
            return queue_for_human_review(
                job_id, job, score, "score intermediaire", reasons, risks
            )
        with sqlite3.connect(DB) as conn:
            conn.execute("UPDATE jobs SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", ("rejected_by_score", job_id))
            conn.execute(
                "UPDATE applications SET status='rejected_by_score', score=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE job_id=? AND status IN ('proposed', 'review_required')",
                (score, job_id),
            )
            conn.execute(
                "INSERT INTO events(event_type, detail) VALUES(?,?)",
                ("job_rejected_by_score", json.dumps({"url": job.source_url, "score": score}, ensure_ascii=False)),
            )
        return {"proposed": False, "score": score}

    with sqlite3.connect(DB) as conn:
        conn.execute("UPDATE jobs SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", ("proposed", job_id))
        existing = conn.execute(
            """
            SELECT id FROM applications
            WHERE job_id=? AND status IN (
                'review_required', 'proposed', 'validated', 'contact_review',
                'contact_confirmed', 'prepared_dry_run', 'manual_action_required', 'sent'
            )
            LIMIT 1
            """,
            (job_id,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE applications SET score=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (score, existing[0]),
            )
            return {"proposed": False, "score": score, "reason": "already_pending"}
        else:
            conn.execute(
                """
                INSERT INTO applications(job_id, channel, status, score, notes)
                VALUES(?,?,?,?,?)
                """,
                (job_id, "telegram_validation", "proposed", score, "Waiting for Telegram approval."),
            )
            app_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    message = build_application_proposal(app_id, job, score, reasons, risks)
    result = send_telegram_message(message)
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "INSERT INTO events(event_type, detail) VALUES(?,?)",
            ("job_proposed_telegram", json.dumps({"url": job.source_url, "score": score, "telegram": result}, ensure_ascii=False)),
        )
    return {"proposed": True, "score": score}


def build_application_proposal(app_id, job, score, reasons, risks):
    analysis = analyse_job(job.title, job.company, job.location, job.description)
    risk_text = ", ".join(risks) if risks else "Aucun risque majeur detecte"
    reason_text = ", ".join(reasons[:5]) if reasons else "Match faible"
    dimensions = analysis["dimensions"]
    score_lines = (
        f"Competences {dimensions['skills']}/100 | Experience metier {dimensions['domain_experience']}/100\n"
        f"Seniorite {dimensions['seniority']}/100 | Secteur {dimensions['sector']}/100\n"
        f"Langues {dimensions['languages']}/100 | Formation {dimensions['education_certifications']}/100"
    )
    recruiter = find_recruiter_for_company(job.company, job.description, job.source_url, job.location)
    contact_lines = []
    if job.contact_email:
        contact_lines.append(f"Email cible: {job.contact_email}")
    elif recruiter:
        contact_lines.append(
            f"Contact pressenti: {recruiter['full_name']} - {recruiter.get('title', 'recruteur/manager')}"
        )
        contact_lines.append(f"Email cible: {recruiter['email']}")
        if recruiter.get("linkedin"):
            contact_lines.append(f"LinkedIn contact: {recruiter['linkedin']}")
        contact_lines.append(
            f"Qualite contact: {recruiter.get('contact_score', 0)}/100 - "
            f"{recruiter.get('contact_reason', 'a verifier')}"
        )
    else:
        contact_lines.append("Email cible: pas encore de contact fiable Luxembourg/EMEA.")
        contact_lines.append("Action si oui: preparation CV PDF + message + lien pour candidature manuelle.")
    contact_text = "\n".join(contact_lines)
    return (
        f"Candidate, j'ai trouve une offre a regarder.\n\n"
        f"App {app_id} - {clean_job_title(job.title)}\n"
        f"Entreprise: {job.company}\n"
        f"Lieu: {job.location}\n"
        f"Match global: {score}/100\n{score_lines}\n\n"
        f"Pourquoi ca peut etre interessant:\n{reason_text}\n\n"
        f"Point a verifier:\n{risk_text}\n\n"
        f"{contact_text}\n"
        f"Lien offre: {job.source_url}\n\n"
        f"Tu peux repondre simplement: oui {app_id} ou non {app_id}."
    )


def main():
    parser = argparse.ArgumentParser(description="Agent HR workflow.")
    parser.add_argument("--job-json", help="Path to a JSON file containing one job.")
    args = parser.parse_args()

    if not args.job_json:
        print("Use --job-json with source, source_url, title, company, location and description.")
        return

    data = load_json(args.job_json)
    job = JobInput(
        source=data["source"],
        source_url=data["source_url"],
        title=data["title"],
        company=data["company"],
        location=data["location"],
        description=data["description"],
        contact_email=data.get("contact_email", ""),
        application_channel=data.get("application_channel", "unknown"),
    )
    print(json.dumps(propose_job(job), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
