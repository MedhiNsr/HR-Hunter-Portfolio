import argparse
import json
from pathlib import Path

from env_loader import load_env
from gmail_sender import send_email, verify_gmail_login
from telegram_client import get_bot_identity, get_telegram_updates, send_telegram_message


ROOT = Path(__file__).resolve().parent


def mask(value):
    if not value:
        return "missing"
    if len(value) <= 8:
        return "configured"
    return f"{value[:4]}...{value[-4:]}"


def check_env():
    env = load_env(ROOT)
    return {
        "agent_mode": env.get("AGENT_MODE", "dry_run"),
        "telegram_bot_token": mask(env.get("TELEGRAM_BOT_TOKEN", "")),
        "telegram_chat_id": env.get("TELEGRAM_CHAT_ID", "missing") or "missing",
        "gmail_address": env.get("GMAIL_ADDRESS", "missing") or "missing",
        "gmail_app_password": mask(env.get("GMAIL_APP_PASSWORD", "")),
        "gmail_test_recipient": env.get("GMAIL_TEST_RECIPIENT", "missing") or "missing",
    }


def check_telegram(send_test=False):
    result = {"identity": None, "updates": None, "send_test": None}
    result["identity"] = get_bot_identity()
    result["updates"] = get_telegram_updates()
    if send_test:
        result["send_test"] = send_telegram_message("Agent HR: test Telegram reussi.")
    return result


def check_gmail(send_test=False):
    env = load_env(ROOT)
    result = {"login": verify_gmail_login(), "send_test": None}
    if send_test:
        recipient = env.get("GMAIL_TEST_RECIPIENT") or env.get("GMAIL_ADDRESS")
        result["send_test"] = send_email(
            recipient,
            "Agent HR - test Gmail",
            "Test de connexion Gmail reussi pour l'Agent HR de Candidate.",
        )
    return result


def main():
    parser = argparse.ArgumentParser(description="Check Agent HR Telegram and Gmail connections.")
    parser.add_argument("--telegram", action="store_true")
    parser.add_argument("--gmail", action="store_true")
    parser.add_argument("--send-test", action="store_true")
    args = parser.parse_args()

    result = {"env": check_env()}
    if args.telegram:
        result["telegram"] = check_telegram(send_test=args.send_test)
    if args.gmail:
        result["gmail"] = check_gmail(send_test=args.send_test)
    if not args.telegram and not args.gmail:
        result["message"] = "Use --telegram and/or --gmail. Add --send-test to send a real test when AGENT_MODE=live."
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
