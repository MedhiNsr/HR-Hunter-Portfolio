import json
import sqlite3
import argparse
import time
import re

from agent_hr import ROOT, ensure_database
from reporting import build_telegram_report
from telegram_client import get_telegram_updates, send_telegram_message
from job_intelligence import clean_job_title


DB = ROOT / "agent_hr.sqlite3"
OFFSET_FILE = ROOT / "logs" / "telegram_offset.txt"


def connect_db():
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def load_policy():
    return json.loads((ROOT / "config" / "agent_policy.json").read_text(encoding="utf-8"))


def get_offset():
    if not OFFSET_FILE.exists():
        return None
    raw = OFFSET_FILE.read_text(encoding="utf-8").strip()
    return int(raw) if raw else None


def save_offset(offset):
    OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    OFFSET_FILE.write_text(str(offset), encoding="utf-8")


def latest_pending_application(conn):
    return conn.execute(
        """
        SELECT applications.id, jobs.title, jobs.company
        FROM applications
        JOIN jobs ON jobs.id = applications.job_id
        WHERE applications.status IN ('proposed', 'review_required')
        ORDER BY applications.id DESC
        LIMIT 1
        """
    ).fetchone()


def pending_application_by_id(conn, app_id):
    return conn.execute(
        """
        SELECT applications.id, jobs.title, jobs.company
        FROM applications
        JOIN jobs ON jobs.id = applications.job_id
        WHERE applications.id = ?
          AND applications.status IN ('proposed', 'review_required')
        LIMIT 1
        """,
        (app_id,),
    ).fetchone()


def classify_reply(text, policy):
    normalized = (text or "").strip().lower()
    first_word = normalized.split()[0] if normalized.split() else ""
    if first_word in policy["telegram"]["approval_words"]:
        return "approved"
    if first_word in policy["telegram"]["rejection_words"]:
        return "rejected"
    return None


def extract_application_id(text):
    match = re.search(r"\b(?:app|candidature)?\s*(\d+)\b", text or "", flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def apply_decision(decision, actor_name, application_id=None):
    ensure_database()
    should_prepare = False
    with connect_db() as conn:
        if application_id:
            contact_review = conn.execute(
                """
                SELECT applications.id, jobs.title, jobs.company
                FROM applications
                JOIN jobs ON jobs.id=applications.job_id
                WHERE applications.id=? AND applications.status='contact_review'
                """,
                (application_id,),
            ).fetchone()
            if contact_review:
                app_id, title, company = contact_review
                if decision == "approved":
                    return f"Pour confirmer le destinataire de {title} - {company}, reponds: ok contact {app_id}."
                conn.execute(
                    """
                    UPDATE applications
                    SET status='rejected', approved_by=?, approved_at=CURRENT_TIMESTAMP,
                        notes='Recipient contact rejected from Telegram.', updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (actor_name, app_id),
                )
                return f"Contact et candidature ecartes pour {title} - {company}. Je continue la recherche."

        if not application_id:
            pending_count = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE status IN ('proposed', 'review_required')"
            ).fetchone()[0]
            if pending_count > 1:
                return (
                    "Plusieurs candidatures sont en attente. "
                    "Merci de preciser le numero: oui 11, non 12, ou oui 11 non 12."
                )
        pending = pending_application_by_id(conn, application_id) if application_id else latest_pending_application(conn)
        if not pending:
            return "Aucune candidature en attente de validation pour cette selection."

        app_id, title, company = pending
        if decision == "approved":
            conn.execute(
                """
                UPDATE applications
                SET status='validated', approved_by=?, approved_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (actor_name, app_id),
            )
            message = (
                f"C'est note Candidate: tu valides {clean_job_title(title)} chez {company}.\n\n"
                "Rien n'est encore envoye. Je prepare maintenant le CV PDF et la lettre.\n"
                "- Si je trouve un email fiable, je te demanderai un deuxieme accord avant l'envoi.\n"
                "- Si la candidature doit se faire sur le site, je t'enverrai les documents et j'indiquerai clairement que c'est a toi de les deposer."
            )
            should_prepare = True
        else:
            conn.execute(
                """
                UPDATE applications
                SET status='rejected', approved_by=?, approved_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (actor_name, app_id),
            )
            message = f"C'est note, on laisse tomber {title} - {company}. Je continue a chercher mieux."

        conn.execute(
            "INSERT INTO events(event_type, detail) VALUES(?,?)",
            ("telegram_decision", json.dumps({"application_id": app_id, "decision": decision, "actor": actor_name}, ensure_ascii=False)),
        )
    if should_prepare:
        from application_preparer import prepare_validated_applications

        prepare_validated_applications(limit=1)
    return message


def attach_email_to_latest_application(email, actor_name):
    ensure_database()
    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT applications.id, jobs.title, jobs.company
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            WHERE applications.status IN ('proposed', 'review_required', 'validated', 'manual_action_required', 'send_failed')
            ORDER BY applications.updated_at DESC, applications.id DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return "Aucune candidature active a laquelle rattacher cet email."
        app_id, title, company = row
        conn.execute(
            """
            UPDATE applications
            SET recipient_email=?, status='validated', approved_by=?, approved_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (email, actor_name, app_id),
        )
        conn.execute(
            "INSERT INTO events(event_type, detail) VALUES(?,?)",
            ("recipient_email_added", json.dumps({"application_id": app_id, "email": email, "actor": actor_name}, ensure_ascii=False)),
        )

    from application_preparer import prepare_validated_applications

    prepare_validated_applications(limit=1)
    return f"Parfait, email ajoute pour {title} - {company}. Je prepare la candidature proprement."


def close_application(application_id, actor_name):
    ensure_database()
    if not application_id:
        return "Merci de preciser le numero: ferme 12."
    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT applications.id, applications.job_id, jobs.title, jobs.company
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            WHERE applications.id=?
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
        if not row:
            return f"Aucune candidature trouvee pour App {application_id}."
        app_id, job_id, title, company = row
        conn.execute(
            """
            UPDATE applications
            SET status='closed', approved_by=?, approved_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP,
                notes='Closed manually from Telegram because the offer is no longer accepting applications.'
            WHERE id=?
            """,
            (actor_name, app_id),
        )
        conn.execute(
            "UPDATE jobs SET status='closed', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (job_id,),
        )
        conn.execute(
            "INSERT INTO events(event_type, detail) VALUES(?,?)",
            ("application_closed", json.dumps({"application_id": app_id, "actor": actor_name}, ensure_ascii=False)),
        )
    return f"Bien vu, offre fermee retiree: App {app_id} - {title} - {company}."


def confirm_contact(application_id, actor_name):
    ensure_database()
    if not application_id:
        return "Merci de preciser le numero: ok contact 13."
    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT applications.id, jobs.title, jobs.company
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            WHERE applications.id=?
              AND applications.status='contact_review'
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
        if not row:
            return f"Aucun contact en attente de confirmation pour App {application_id}."
        app_id, title, company = row
        conn.execute(
            """
            UPDATE applications
            SET status='contact_confirmed',
                approved_by=?,
                approved_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (actor_name, app_id),
        )
        conn.execute(
            "INSERT INTO events(event_type, detail) VALUES(?,?)",
            ("contact_confirmed", json.dumps({"application_id": app_id, "actor": actor_name}, ensure_ascii=False)),
        )

    from application_preparer import prepare_validated_applications

    prepare_validated_applications(limit=1)
    return f"Contact confirme pour App {app_id}. Je lance l'envoi proprement pour {title} - {company}."


def build_status_message():
    ensure_database()
    with connect_db() as conn:
        pending = conn.execute(
            """
            SELECT COUNT(*)
            FROM applications
            WHERE status IN ('proposed', 'review_required')
            """
        ).fetchone()[0]
        validated = conn.execute(
            """
            SELECT COUNT(*)
            FROM applications
            WHERE status IN ('validated', 'prepared')
            """
        ).fetchone()[0]
        sent = conn.execute(
            """
            SELECT COUNT(*)
            FROM applications
            WHERE status = 'sent'
            """
        ).fetchone()[0]
        last_job = conn.execute(
            """
            SELECT title, company, score, status
            FROM jobs
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()

    lines = [
        "Agent HR - statut",
        f"Candidatures en attente: {pending}",
        f"Validees / preparees: {validated}",
        f"Envoyees: {sent}",
    ]
    if last_job:
        title, company, score, status = last_job
        lines.append(f"Derniere offre: {title} - {company} ({score}/100, {status})")
    return "\n".join(lines)


def help_message():
    return (
        "Commandes Agent HR:\n"
        "- ping: verifier que le bot repond\n"
        "- status: voir l'etat des candidatures\n"
        "- rapport: recevoir le rapport du jour\n"
        "- oui 13: valider une candidature precise\n"
        "- non 13: rejeter une candidature precise\n"
        "- ferme 13: retirer une offre fermee\n"
        "- ok contact 13: confirmer le destinataire email avant envoi\n"
        "- oui: valider la derniere candidature proposee si une seule decision est evidente\n"
        "- non: rejeter la derniere candidature proposee\n"
        "- aide: afficher ce message"
    )


def handle_text_message(text, actor):
    normalized = (text or "").strip().lower()
    email_match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text or "")
    if normalized.startswith("email ") and email_match:
        return attach_email_to_latest_application(email_match.group(0), actor)
    if normalized.startswith(("ferme ", "fermé ", "closed ", "close ")):
        return close_application(extract_application_id(text), actor)
    if normalized.startswith(("ok contact", "contact ok", "confirme contact", "valide contact")):
        return confirm_contact(extract_application_id(text), actor)
    policy = load_policy()

    multi_decisions = re.findall(r"\b(oui|yes|ok|go|valide|validé|non|no|reject|rejette|rejeté)\s+(?:app\s*)?(\d+)\b", normalized)
    if multi_decisions:
        responses = []
        for word, app_id in multi_decisions:
            decision = classify_reply(word, policy)
            if decision:
                responses.append(apply_decision(decision, actor, int(app_id)))
        return "\n\n".join(responses) if responses else None

    decision = classify_reply(normalized, policy)
    if decision:
        return apply_decision(decision, actor, extract_application_id(text))
    if normalized in {"ping", "/ping"}:
        return "pong - Agent HR est connecte."
    if normalized in {"status", "/status", "statut", "/statut"}:
        return build_status_message()
    if normalized in {"rapport", "/rapport", "report", "/report"}:
        return build_telegram_report()
    if normalized in {"aide", "/aide", "help", "/help", "/start"}:
        return help_message()
    return None


def process_updates():
    offset = get_offset()
    updates = get_telegram_updates(offset=offset)
    processed = 0

    for update in updates.get("result", []):
        update_id = update.get("update_id")
        if update_id is not None:
            save_offset(update_id + 1)

        message = update.get("message") or update.get("edited_message") or {}
        text = message.get("text", "")
        actor = (message.get("from") or {}).get("first_name", "Telegram")
        response = handle_text_message(text, actor)
        if not response:
            continue

        send_telegram_message(response)
        processed += 1

    return {"processed_messages": processed}


def listen_forever(interval_seconds=5):
    print("Agent HR Telegram listener started. Press Ctrl+C to stop.")
    while True:
        result = process_updates()
        if result.get("processed_messages"):
            print(json.dumps(result, ensure_ascii=True))
        time.sleep(interval_seconds)


def main():
    parser = argparse.ArgumentParser(description="Process Telegram approvals for Agent HR.")
    parser.add_argument("--simulate", choices=["oui", "non"], help="Apply a local test approval or rejection.")
    parser.add_argument("--actor", default="Local test")
    parser.add_argument("--listen", action="store_true", help="Keep listening for Telegram commands.")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in seconds for --listen.")
    args = parser.parse_args()

    if args.listen:
        listen_forever(interval_seconds=args.interval)
        return

    if args.simulate:
        policy = load_policy()
        decision = classify_reply(args.simulate, policy)
        print(apply_decision(decision, args.actor))
        return

    print(json.dumps(process_updates(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
