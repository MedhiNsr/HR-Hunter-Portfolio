import argparse
import json

from approval_worker import process_updates
from application_preparer import prepare_validated_applications
from dashboard import build_dashboard
from follow_up_worker import process_due_followups
from job_search import run_search
from lusha_recruiter_queue import queue_missing_recruiters
from reporting import build_daily_report, build_telegram_report, save_report
from telegram_client import send_telegram_message


def run_cycle(search=False, send_report=False, limit_per_term=1):
    result = {
        "search": None,
        "approvals": None,
        "prepared": [],
        "followups": [],
        "lusha_queue": [],
        "report": None,
    }
    if search:
        result["search"] = run_search(limit_per_term=limit_per_term, dry_run=False)
    result["approvals"] = process_updates()
    result["prepared"] = prepare_validated_applications()
    result["dashboard"] = build_dashboard()
    result["lusha_queue"] = queue_missing_recruiters(limit=10)
    result["followups"] = process_due_followups()
    report = build_daily_report()
    report_path = save_report(report)
    result["report"] = str(report_path)
    if send_report:
        send_telegram_message(build_telegram_report())
    return result


def main():
    parser = argparse.ArgumentParser(description="Run one Agent HR cycle.")
    parser.add_argument("--search", action="store_true", help="Search job sources during this cycle.")
    parser.add_argument("--send-report", action="store_true", help="Send the report to Telegram.")
    parser.add_argument("--limit-per-term", type=int, default=1)
    args = parser.parse_args()
    print(json.dumps(run_cycle(search=args.search, send_report=args.send_report, limit_per_term=args.limit_per_term), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
