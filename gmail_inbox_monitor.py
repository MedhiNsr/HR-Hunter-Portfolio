import hashlib
import imaplib
import json
import re
import sqlite3
from datetime import datetime, timedelta
from email import message_from_bytes
from email.header import decode_header
from email.utils import parseaddr

from agent_hr import ROOT, ensure_database
from env_loader import load_env


DB = ROOT / "agent_hr.sqlite3"


def decode_value(value):
    parts = []
    for item, encoding in decode_header(value or ""):
        if isinstance(item, bytes):
            parts.append(item.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(item)
    return "".join(parts)


def message_body(message):
    chunks = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_type() not in {"text/plain", "text/html"}:
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            chunks.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
        except Exception:
            continue
    return re.sub(r"<[^>]+>", " ", " ".join(chunks))[:12000]


def normalize_subject(subject):
    value = decode_value(subject).lower().strip()
    return re.sub(r"^(?:(?:re|fw|fwd|tr)\s*:\s*)+", "", value).strip()


def classify_reply(sender, subject, body):
    text = f"{subject} {body}".lower()
    sender_lower = sender.lower()
    acknowledgement = [
        "we have received your application",
        "application has been received",
        "thank you for applying",
        "merci pour votre candidature",
        "candidature a bien ete recue",
        "candidature a bien été reçue",
        "automated message",
        "message automatique",
    ]
    negative = [
        "unfortunately",
        "we will not be moving forward",
        "not been selected",
        "other candidates",
        "nous ne donnerons pas suite",
        "candidature non retenue",
        "malheureusement",
        "regret to inform",
    ]
    positive = [
        "interview",
        "next step",
        "shortlisted",
        "availability for a call",
        "schedule a call",
        "meet with",
        "entretien",
        "prochain entretien",
        "prochaine etape",
        "prochaine étape",
        "vos disponibilites",
        "vos disponibilités",
        "échanger avec vous",
        "echange avec vous",
    ]
    if "no-reply" in sender_lower or "noreply" in sender_lower or any(term in text for term in acknowledgement):
        return "acknowledgement"
    if any(term in text for term in negative):
        return "negative"
    if any(term in text for term in positive):
        return "positive"
    return "neutral"


def relevant_application(applications, sender, subject):
    normalized = normalize_subject(subject)
    sender = sender.lower()
    for row in applications:
        if sender and sender == (row[1] or "").lower():
            return row
    for row in applications:
        sent_subject = normalize_subject(row[2])
        if normalized and sent_subject and (normalized in sent_subject or sent_subject in normalized):
            return row
    return None


def poll_gmail_replies(days_back=7, limit=60):
    ensure_database()
    env = load_env(ROOT)
    address = env.get("GMAIL_ADDRESS", "")
    password = env.get("GMAIL_APP_PASSWORD", "")
    if not address or not password:
        return {"checked": 0, "replies": [], "error": "gmail_not_configured"}

    with sqlite3.connect(DB) as conn:
        applications = conn.execute(
            """
            SELECT applications.id, applications.recipient_email, applications.email_subject,
                   jobs.title, jobs.company, applications.status
            FROM applications JOIN jobs ON jobs.id=applications.job_id
            WHERE applications.sent_at IS NOT NULL
               OR applications.status IN ('sent', 'follow_up_1_sent', 'follow_up_2_sent')
            ORDER BY applications.id DESC
            """
        ).fetchall()
    if not applications:
        return {"checked": 0, "replies": []}

    processed = []
    checked = 0
    mailbox = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        mailbox.login(address, password)
        mailbox.select("INBOX", readonly=True)
        since = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
        status, data = mailbox.search(None, "SINCE", since)
        if status != "OK":
            return {"checked": 0, "replies": [], "error": "gmail_search_failed"}
        message_ids = (data[0].split() if data and data[0] else [])[-limit:]
        for message_number in message_ids:
            status, payload = mailbox.fetch(message_number, "(BODY.PEEK[])")
            if status != "OK":
                continue
            raw = next((item[1] for item in payload if isinstance(item, tuple)), None)
            if not raw:
                continue
            checked += 1
            message = message_from_bytes(raw)
            sender = parseaddr(decode_value(message.get("From", "")))[1]
            if sender.lower() == address.lower():
                continue
            subject = decode_value(message.get("Subject", ""))
            application = relevant_application(applications, sender, subject)
            if not application:
                continue
            fingerprint = hashlib.sha256(
                (message.get("Message-ID", "") + sender + subject).encode("utf-8", errors="ignore")
            ).hexdigest()
            with sqlite3.connect(DB) as conn:
                if conn.execute(
                    "SELECT 1 FROM events WHERE event_type IN ('gmail_reply_detected','gmail_acknowledgement_detected') "
                    "AND detail LIKE ? LIMIT 1",
                    (f'%"fingerprint": "{fingerprint}"%',),
                ).fetchone():
                    continue
                app_id, _, _, title, company, current_status = application
                sentiment = classify_reply(sender, subject, message_body(message))
                detail = json.dumps(
                    {
                        "application_id": app_id,
                        "fingerprint": fingerprint,
                        "sender": sender,
                        "subject": subject,
                        "sentiment": sentiment,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                if sentiment == "acknowledgement":
                    conn.execute(
                        "INSERT INTO events(event_type, detail) VALUES(?,?)",
                        ("gmail_acknowledgement_detected", detail),
                    )
                else:
                    new_status = {
                        "positive": "positive_response",
                        "negative": "employer_rejected",
                        "neutral": "response_received",
                    }[sentiment]
                    if current_status not in {"interview", "accepted"}:
                        conn.execute(
                            "UPDATE applications SET status=?, follow_up_due_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            (new_status, app_id),
                        )
                    conn.execute(
                        "INSERT INTO events(event_type, detail) VALUES(?,?)",
                        ("gmail_reply_detected", detail),
                    )
                processed.append(
                    {"application_id": app_id, "title": title, "company": company, "sentiment": sentiment}
                )
    finally:
        try:
            mailbox.logout()
        except Exception:
            pass
    return {"checked": checked, "replies": processed}


if __name__ == "__main__":
    print(json.dumps(poll_gmail_replies(), indent=2, ensure_ascii=False))
