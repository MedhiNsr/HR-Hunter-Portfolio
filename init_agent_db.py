import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DB = ROOT / "agent_hr.sqlite3"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def initialize_database(verbose=False):
    conn = sqlite3.connect(DB, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL,
                description TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'found',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                score INTEGER NOT NULL,
                cv_path TEXT NOT NULL DEFAULT '',
                cover_letter_path TEXT NOT NULL DEFAULT '',
                email_subject TEXT NOT NULL DEFAULT '',
                email_body TEXT NOT NULL DEFAULT '',
                telegram_message_id TEXT NOT NULL DEFAULT '',
                approved_by TEXT NOT NULL DEFAULT '',
                approved_at TEXT,
                sent_at TEXT,
                follow_up_due_at TEXT,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS recruiter_contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL DEFAULT 'manual',
                full_name TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                company TEXT NOT NULL DEFAULT '',
                domain TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL UNIQUE,
                linkedin TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                priority INTEGER NOT NULL DEFAULT 50,
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        ensure_columns(conn, "jobs", {
            "contact_email": "TEXT NOT NULL DEFAULT ''",
            "application_channel": "TEXT NOT NULL DEFAULT 'unknown'",
            "analysis_json": "TEXT NOT NULL DEFAULT '{}'",
        })
        ensure_columns(conn, "applications", {
            "recipient_email": "TEXT NOT NULL DEFAULT ''",
            "recipient_name": "TEXT NOT NULL DEFAULT ''",
            "recipient_linkedin": "TEXT NOT NULL DEFAULT ''",
            "recipient_is_named": "INTEGER NOT NULL DEFAULT 0",
            "contact_score": "INTEGER NOT NULL DEFAULT 0",
            "contact_reason": "TEXT NOT NULL DEFAULT ''",
            "sent_error": "TEXT NOT NULL DEFAULT ''",
            "quality_report_json": "TEXT NOT NULL DEFAULT '{}'",
            "document_fingerprint": "TEXT NOT NULL DEFAULT ''",
        })

        profile = load_json(ROOT / "profile" / "candidate_profile.json")
        scoring = load_json(ROOT / "config" / "scoring_rules.json")
        policy = load_json(ROOT / "config" / "agent_policy.json")
        for key, value in {
            "profile": profile,
            "scoring_rules": scoring,
            "agent_policy": policy,
        }.items():
            conn.execute(
                "INSERT OR REPLACE INTO config(key, value, updated_at) VALUES(?,?,CURRENT_TIMESTAMP)",
                (key, json.dumps(value, ensure_ascii=False, indent=2)),
            )
        conn.execute("INSERT INTO events(event_type, detail) VALUES(?,?)", ("init", "Agent HR database initialized."))
        conn.commit()
        if verbose:
            print(DB)
    finally:
        conn.close()


def ensure_columns(conn, table, columns):
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


if __name__ == "__main__":
    initialize_database(verbose=True)
