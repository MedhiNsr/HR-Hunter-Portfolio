import argparse
import sqlite3

from agent_hr import ROOT, ensure_database
from gmail_sender import send_email
from telegram_client import send_telegram_message


DB = ROOT / "agent_hr.sqlite3"


def build_follow_up(title, company, recipient_name="", second=False):
    prefix = "Second follow-up" if second else "Follow-up"
    subject = f"{prefix} - Application - {title} - Demo Candidate"
    first_name = (recipient_name or "").strip().split(" ", 1)[0]
    greeting = f"Hello {first_name}," if first_name else "Hello,"
    body = f"""{greeting}

I hope you are well.

I am following up on my application for the {title} position at {company}. I remain very interested in the opportunity and would be happy to provide any additional information that may be useful.

Kind regards,

Demo Candidate
+352 000 00 00 00
candidate@example.com
"""
    return subject, body


def process_due_followups(limit=10):
    ensure_database()
    processed = []
    with sqlite3.connect(DB) as conn:
        rows = conn.execute(
            """
            SELECT applications.id, applications.recipient_email, jobs.title, jobs.company,
                   applications.recipient_name, applications.recipient_is_named
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            WHERE applications.status IN ('sent', 'follow_up_1_sent', 'manual_action_required')
              AND applications.follow_up_due_at IS NOT NULL
              AND applications.follow_up_due_at <= CURRENT_TIMESTAMP
            ORDER BY applications.follow_up_due_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        for app_id, recipient, title, company, recipient_name, recipient_is_named in rows:
            status = conn.execute("SELECT status FROM applications WHERE id=?", (app_id,)).fetchone()[0]
            if status == "manual_action_required":
                conn.execute(
                    """
                    UPDATE applications
                    SET status='manual_reminder_sent',
                        follow_up_due_at=NULL,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (app_id,),
                )
                send_telegram_message(
                    f"Rappel candidature manuelle.\nApp {app_id}: {title} - {company}\nAction: postuler via le lien ou ajouter le recruteur sur LinkedIn."
                )
                processed.append({"application_id": app_id, "status": "manual_reminder"})
                continue

            if status == "follow_up_1_sent" and not recipient_is_named:
                conn.execute(
                    "UPDATE applications SET follow_up_due_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (app_id,),
                )
                processed.append({"application_id": app_id, "status": "second_followup_skipped_generic"})
                continue

            subject, body = build_follow_up(
                title, company, recipient_name=recipient_name, second=(status == "follow_up_1_sent")
            )
            try:
                result = send_email(recipient, subject, body)
                if result.get("dry_run"):
                    processed.append({"application_id": app_id, "status": "dry_run"})
                    continue
                conn.execute(
                    """
                    UPDATE applications
                    SET status=?,
                        follow_up_due_at=NULL,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        "follow_up_2_sent" if status == "follow_up_1_sent" else "follow_up_1_sent",
                        app_id,
                    ),
                )
                if status != "follow_up_1_sent" and recipient_is_named:
                    conn.execute(
                        "UPDATE applications SET follow_up_due_at=DATETIME(CURRENT_TIMESTAMP, '+9 days') WHERE id=?",
                        (app_id,),
                    )
                conn.execute(
                    "INSERT INTO events(event_type, detail) VALUES(?,?)",
                    ("follow_up_sent", f"application_id={app_id}; recipient={recipient}"),
                )
                send_telegram_message(
                    f"Relance envoyee.\nPoste: {title}\nEntreprise: {company}"
                )
                processed.append({"application_id": app_id, "status": "sent"})
            except Exception as exc:
                conn.execute(
                    """
                    UPDATE applications
                    SET status='follow_up_failed', sent_error=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (str(exc), app_id),
                )
                send_telegram_message(
                    f"Relance non envoyee automatiquement.\nPoste: {title}\nEntreprise: {company}\nAction: verifier ou envoyer manuellement."
                )
                processed.append({"application_id": app_id, "status": "failed", "error": str(exc)})
    return processed


def main():
    parser = argparse.ArgumentParser(description="Send due follow-ups for Agent HR.")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    print(process_due_followups(limit=args.limit))


if __name__ == "__main__":
    main()
