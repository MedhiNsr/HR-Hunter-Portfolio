import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path

from agent_hr import ROOT, ensure_database
from telegram_client import send_telegram_message


DB = ROOT / "agent_hr.sqlite3"
REPORT_DIR = ROOT / "reports"


def rows_to_lines(rows):
    lines = []
    for row in rows:
        title, company, location, score, status, url = row
        lines.append(f"- {title} | {company} | {location} | {score}/100 | {status}\n  {url}")
    return lines


def build_daily_report():
    ensure_database()
    with sqlite3.connect(DB) as conn:
        job_counts = conn.execute(
            "SELECT status, COUNT(*) FROM jobs GROUP BY status ORDER BY status"
        ).fetchall()
        app_counts = conn.execute(
            "SELECT status, COUNT(*) FROM applications GROUP BY status ORDER BY status"
        ).fetchall()
        top_jobs = conn.execute(
            """
            SELECT title, company, location, score, status, source_url
            FROM jobs
            WHERE score >= 60
            ORDER BY updated_at DESC, score DESC
            LIMIT 10
            """
        ).fetchall()

    lines = ["Agent HR - rapport quotidien", ""]
    lines.append("Offres par statut:")
    if job_counts:
        lines.extend([f"- {status}: {count}" for status, count in job_counts])
    else:
        lines.append("- aucune offre enregistree")

    lines.append("")
    lines.append("Candidatures par statut:")
    if app_counts:
        lines.extend([f"- {status}: {count}" for status, count in app_counts])
    else:
        lines.append("- aucune candidature creee")

    lines.append("")
    lines.append("Dernieres offres pertinentes:")
    lines.extend(rows_to_lines(top_jobs) if top_jobs else ["- aucune offre au-dessus du seuil"])

    return "\n".join(lines)


def build_telegram_report():
    ensure_database()
    with sqlite3.connect(DB) as conn:
        discovered_today = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE DATE(created_at, 'localtime')=DATE('now', 'localtime')"
        ).fetchone()[0]
        proposed_today = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='job_proposed_telegram' "
            "AND DATE(created_at, 'localtime')=DATE('now', 'localtime')"
        ).fetchone()[0]
        approved_today = conn.execute(
            "SELECT COUNT(*) FROM applications WHERE approved_at IS NOT NULL "
            "AND DATE(approved_at, 'localtime')=DATE('now', 'localtime') "
            "AND status NOT IN ('rejected', 'closed')"
        ).fetchone()[0]
        sent_today = conn.execute(
            "SELECT COUNT(*) FROM applications WHERE sent_at IS NOT NULL "
            "AND DATE(sent_at, 'localtime')=DATE('now', 'localtime')"
        ).fetchone()[0]
        followups_today = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='follow_up_sent' "
            "AND DATE(created_at, 'localtime')=DATE('now', 'localtime')"
        ).fetchone()[0]
        acknowledgements_today = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='gmail_acknowledgement_detected' "
            "AND DATE(created_at, 'localtime')=DATE('now', 'localtime')"
        ).fetchone()[0]
        replies = conn.execute(
            """
            SELECT applications.status, jobs.title, jobs.company
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            WHERE applications.status IN ('positive_response', 'response_received', 'employer_rejected', 'interview', 'accepted')
              AND DATE(applications.updated_at, 'localtime')=DATE('now', 'localtime')
            ORDER BY applications.updated_at DESC
            LIMIT 5
            """
        ).fetchall()
        pending_count = conn.execute(
            "SELECT COUNT(*) FROM applications WHERE status IN ('proposed', 'review_required', 'contact_review')"
        ).fetchone()[0]
        manual_count = conn.execute(
            "SELECT COUNT(*) FROM applications WHERE status='manual_action_required'"
        ).fetchone()[0]
        sent_jobs = conn.execute(
            """
            SELECT jobs.title, jobs.company
            FROM applications JOIN jobs ON jobs.id=applications.job_id
            WHERE applications.sent_at IS NOT NULL
              AND DATE(applications.sent_at, 'localtime')=DATE('now', 'localtime')
            ORDER BY applications.sent_at DESC LIMIT 3
            """
        ).fetchall()

    positive = [row for row in replies if row[0] in {"positive_response", "interview", "accepted"}]
    neutral = [row for row in replies if row[0] == "response_received"]
    negative = [row for row in replies if row[0] == "employer_rejected"]

    lines = ["Candidate, voici ton point du jour.", ""]
    lines.append(f"Offres reperees: {discovered_today} | proposees: {proposed_today}")
    lines.append(f"Validees: {approved_today} | envoyees: {sent_today} | relances: {followups_today}")
    lines.append(
        f"Reponses humaines: {len(replies)} | confirmations recues: {acknowledgements_today} | a valider: {pending_count}"
    )
    if manual_count:
        lines.append(f"Actions manuelles restantes: {manual_count}")

    if positive:
        lines.extend(["", "Bonne nouvelle:"])
        for _, title, company in positive:
            lines.append(f"- Retour positif: {title} chez {company}")
    if neutral:
        lines.extend(["", "Reponses a examiner:"])
        for _, title, company in neutral:
            lines.append(f"- {title} chez {company}")
    if negative:
        lines.append(f"Refus recus aujourd'hui: {len(negative)}. On ajuste et on continue.")

    if sent_jobs:
        lines.extend(["", "Candidatures parties:"])
        lines.extend([f"- {title} | {company}" for title, company in sent_jobs])

    lines.append("")
    if sent_today or positive:
        lines.append("Chaque candidature bien ciblee nous rapproche du bon oui. Belle fin de journee, Candidate.")
    else:
        lines.append("Journee calme, mais la recherche continue. La constance finit par ouvrir les bonnes portes.")
    return "\n".join(lines)


MORNING_PHRASES = [
    "La constance transforme les petites avancees en vraies opportunites.",
    "On ne controle pas chaque reponse, mais on peut soigner chaque tentative.",
    "Une nouvelle journee, c'est une nouvelle porte qui peut s'ouvrir.",
    "Le bon poste ne demande pas d'etre parfaite, seulement d'etre vue au bon moment.",
    "Avancer avec methode vaut mieux que courir sans direction.",
    "Chaque candidature juste augmente la probabilite de la bonne rencontre.",
    "La patience n'est pas l'attente: c'est continuer intelligemment.",
]


def build_morning_message(on_date=None):
    on_date = on_date or date.today()
    phrase = MORNING_PHRASES[on_date.toordinal() % len(MORNING_PHRASES)]
    return (
        f"Bonjour Candidate,\n\n{phrase}\n\n"
        "Je commence la veille du jour: nouvelles offres, verification de leur disponibilite "
        "et preparation des candidatures les plus pertinentes. Je te sollicite seulement quand ton choix est necessaire. "
        "Belle journee a toi."
    )


def scheduled_notification_sent(event_type, on_date=None):
    ensure_database()
    key = (on_date or date.today()).isoformat()
    conn = sqlite3.connect(DB)
    try:
        return conn.execute(
            "SELECT 1 FROM events WHERE event_type=? AND detail=? LIMIT 1",
            (event_type, json.dumps({"local_date": key}, sort_keys=True)),
        ).fetchone() is not None
    finally:
        conn.close()


def record_scheduled_notification(event_type, on_date=None):
    ensure_database()
    key = (on_date or date.today()).isoformat()
    conn = sqlite3.connect(DB)
    try:
        conn.execute(
            "INSERT INTO events(event_type, detail) VALUES(?,?)",
            (event_type, json.dumps({"local_date": key}, sort_keys=True)),
        )
        conn.commit()
    finally:
        conn.close()


def build_telegram_report_old():
    ensure_database()
    with sqlite3.connect(DB) as conn:
        active_jobs = conn.execute(
            """
            SELECT title, company, location, score, source_url
            FROM jobs
            WHERE status='proposed'
            ORDER BY score DESC, updated_at DESC
            LIMIT 5
            """
        ).fetchall()
        app_counts = conn.execute(
            "SELECT status, COUNT(*) FROM applications GROUP BY status ORDER BY status"
        ).fetchall()

    lines = ["Agent HR Candidate - point d'avancement", ""]
    lines.append("Candidatures:")
    lines.extend([f"- {status}: {count}" for status, count in app_counts] or ["- aucune"])
    lines.append("")
    lines.append("Offres a valider:")
    if not active_jobs:
        lines.append("- aucune offre active pour l'instant")
    for title, company, location, score, url in active_jobs:
        lines.append(f"- {title} | {company} | {location} | {score}/100")
        lines.append(f"  {url}")
    lines.append("")
    lines.append("Repondez oui pour valider la derniere offre proposee, non pour la rejeter, ou rapport pour redemander le point.")
    return "\n".join(lines)


def save_report(text):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "daily_report_latest.md"
    path.write_text(text, encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser(description="Create or send Agent HR reports.")
    parser.add_argument("--send-telegram", action="store_true")
    args = parser.parse_args()
    report = build_daily_report()
    path = save_report(report)
    print(path)
    print(report)
    if args.send_telegram:
        send_telegram_message(build_telegram_report())


if __name__ == "__main__":
    main()
