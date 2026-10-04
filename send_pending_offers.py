import sqlite3

from agent_hr import JobInput, ROOT, score_job
from telegram_client import send_telegram_message
from workflow import build_application_proposal, load_json


DB = ROOT / "agent_hr.sqlite3"


def send_usage_message():
    send_telegram_message(
        "Mode d emploi Agent HR\n\n"
        "Je vais envoyer les offres une par une.\n"
        "Pour chaque offre, repondez uniquement avec le numero indique :\n"
        "- oui 11 = on postule\n"
        "- non 11 = on rejette\n\n"
        "Si une offre peut etre envoyee par email a un contact recruteur fiable Luxembourg/EMEA, "
        "je prepare le CV PDF ATS et j envoie apres validation.\n"
        "Si le canal est LinkedIn ou portail, je prepare les documents PDF et le lien pour postuler manuellement.\n\n"
        "Je n enverrai plus de messages techniques, Lusha ou logs de dev ici."
    )


def send_pending_offers():
    rules = load_json(ROOT / "config" / "scoring_rules.json")
    sent = []
    with sqlite3.connect(DB) as conn:
        rows = conn.execute(
            """
            SELECT applications.id,
                   jobs.source,
                   jobs.source_url,
                   jobs.title,
                   jobs.company,
                   jobs.location,
                   jobs.description,
                   jobs.contact_email,
                   jobs.application_channel
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            WHERE applications.status='proposed'
              AND jobs.status='proposed'
            ORDER BY applications.id
            """
        ).fetchall()

    for app_id, source, url, title, company, location, description, contact_email, channel in rows:
        job = JobInput(source, url, title, company, location, description, contact_email, channel)
        score, reasons, risks = score_job(job, rules)
        send_telegram_message(build_application_proposal(app_id, job, score, reasons, risks))
        sent.append(app_id)
    return sent


if __name__ == "__main__":
    send_usage_message()
    print(send_pending_offers())
