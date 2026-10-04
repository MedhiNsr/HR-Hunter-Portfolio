import csv
import sqlite3

from agent_hr import ROOT, ensure_database


DB = ROOT / "agent_hr.sqlite3"
DASHBOARD_DIR = ROOT / "reports"


def next_action(status, recipient_email, follow_up_due_at):
    if status == "proposed":
        return "Awaiting Telegram yes/no"
    if status == "review_required":
        return "Awaiting Telegram review yes/no"
    if status == "contact_review":
        return "Awaiting Telegram contact confirmation"
    if status == "manual_action_required":
        return "Manual application / LinkedIn action required"
    if status == "manual_reminder_sent":
        return "Manual reminder sent; waiting for update"
    if status == "sent":
        return f"Follow up due {follow_up_due_at}" if follow_up_due_at else "Waiting for reply"
    if status == "follow_up_1_sent":
        return f"Second follow-up due {follow_up_due_at}" if follow_up_due_at else "Waiting for reply"
    if status in {"closed", "rejected", "rejected_by_quality"}:
        return "No action"
    if recipient_email:
        return "Email contact available"
    return "Review"


def build_dashboard():
    ensure_database()
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = DASHBOARD_DIR / "pipeline_dashboard.csv"
    md_path = DASHBOARD_DIR / "pipeline_dashboard.md"
    with sqlite3.connect(DB) as conn:
        rows = conn.execute(
            """
            SELECT applications.id,
                   jobs.title,
                   jobs.company,
                   jobs.location,
                   jobs.score,
                   applications.status,
                   jobs.application_channel,
                   applications.recipient_email,
                   applications.follow_up_due_at,
                   jobs.source_url
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            ORDER BY applications.updated_at DESC, applications.id DESC
            """
        ).fetchall()

    headers = [
        "app_id",
        "title",
        "company",
        "location",
        "score",
        "status",
        "channel",
        "contact",
        "next_action",
        "url",
    ]
    records = []
    for app_id, title, company, location, score, status, channel, contact, due, url in rows:
        records.append([
            app_id,
            title,
            company,
            location,
            score,
            status,
            channel,
            contact,
            next_action(status, contact, due),
            url,
        ])

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(records)

    lines = ["# Agent HR Candidate - Pipeline", ""]
    lines.append("| App | Offre | Entreprise | Score | Statut | Contact | Prochaine action |")
    lines.append("|---:|---|---|---:|---|---|---|")
    for row in records[:25]:
        app_id, title, company, _location, score, status, _channel, contact, action, _url = row
        lines.append(f"| {app_id} | {title} | {company} | {score} | {status} | {contact or '-'} | {action} |")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"csv": str(csv_path), "markdown": str(md_path), "count": len(records)}


if __name__ == "__main__":
    print(build_dashboard())
