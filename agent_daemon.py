import argparse
import json
import time
from datetime import datetime, date

from approval_worker import process_updates
from application_preparer import prepare_validated_applications
from dashboard import build_dashboard
from follow_up_worker import process_due_followups
from gmail_inbox_monitor import poll_gmail_replies
from job_search import run_search
from lusha_recruiter_queue import queue_missing_recruiters
from reporting import (
    build_daily_report,
    build_morning_message,
    build_telegram_report,
    record_scheduled_notification,
    save_report,
    scheduled_notification_sent,
)
from telegram_client import send_telegram_message


def should_run(last_run_ts, interval_seconds):
    return last_run_ts is None or (time.time() - last_run_ts) >= interval_seconds


def run_daemon(search_interval_minutes=120, approval_interval_seconds=10, followup_interval_minutes=30, limit_per_term=1):
    last_search = None
    last_followup = None
    last_inbox_check = None
    while True:
        summary = {"approvals": None, "prepared": [], "followups": [], "search": None, "lusha_queue": [], "gmail": None}

        try:
            summary["approvals"] = process_updates()
            summary["prepared"] = prepare_validated_applications()
            build_dashboard()
            summary["lusha_queue"] = queue_missing_recruiters(limit=10)

            if should_run(last_followup, followup_interval_minutes * 60):
                summary["followups"] = process_due_followups()
                last_followup = time.time()

            if should_run(last_inbox_check, 10 * 60):
                summary["gmail"] = poll_gmail_replies()
                last_inbox_check = time.time()

            if should_run(last_search, search_interval_minutes * 60):
                print(json.dumps({"event": "search_started", "at": datetime.now().isoformat()}), flush=True)
                summary["search"] = run_search(limit_per_term=limit_per_term, dry_run=False)
                last_search = time.time()
                print(
                    json.dumps({"event": "search_completed", "result": summary["search"]}, ensure_ascii=True),
                    flush=True,
                )

            now = datetime.now()
            morning_window = (now.hour == 9 and now.minute >= 30) or 10 <= now.hour < 12
            if morning_window and not scheduled_notification_sent("morning_message_sent"):
                result = send_telegram_message(build_morning_message())
                if result.get("ok"):
                    record_scheduled_notification("morning_message_sent")

            if now.hour >= 18 and not scheduled_notification_sent("daily_report_sent"):
                report = build_daily_report()
                save_report(report)
                result = send_telegram_message(build_telegram_report())
                if result.get("ok"):
                    record_scheduled_notification("daily_report_sent")

            if any([
                summary["approvals"] and summary["approvals"].get("processed_messages"),
                summary["prepared"],
                summary["followups"],
                summary["gmail"] and summary["gmail"].get("replies"),
                summary["lusha_queue"],
                summary["search"] and summary["search"].get("proposed"),
            ]):
                print(json.dumps(summary, ensure_ascii=True), flush=True)
        except Exception as exc:
            print(f"ERROR: {exc}", flush=True)

        time.sleep(approval_interval_seconds)


def main():
    parser = argparse.ArgumentParser(description="Run Agent HR continuously.")
    parser.add_argument("--search-interval-minutes", type=int, default=120)
    parser.add_argument("--approval-interval-seconds", type=int, default=10)
    parser.add_argument("--followup-interval-minutes", type=int, default=30)
    parser.add_argument("--limit-per-term", type=int, default=1)
    args = parser.parse_args()
    run_daemon(
        search_interval_minutes=args.search_interval_minutes,
        approval_interval_seconds=args.approval_interval_seconds,
        followup_interval_minutes=args.followup_interval_minutes,
        limit_per_term=args.limit_per_term,
    )


if __name__ == "__main__":
    main()
