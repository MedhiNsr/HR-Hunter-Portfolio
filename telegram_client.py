import json
import mimetypes
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from env_loader import load_env


ROOT = Path(__file__).resolve().parent


def get_bot_identity():
    env = load_env(ROOT)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {"ok": False, "error": "missing TELEGRAM_BOT_TOKEN"}

    with urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def send_telegram_message(text):
    env = load_env(ROOT)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID", "")
    mode = env.get("AGENT_MODE", "dry_run")

    if mode == "dry_run" or not token or not chat_id:
        print("[DRY RUN] Telegram message:")
        print(text)
        return {"ok": True, "dry_run": True}

    results = []
    chunks = [text[i : i + 3500] for i in range(0, len(text), 3500)] or [""]
    for chunk in chunks:
        payload = json.dumps(
            {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
        ).encode("utf-8")
        request = Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=20) as response:
            results.append(json.loads(response.read().decode("utf-8")))
    return {"ok": all(item.get("ok") for item in results), "results": results}


def send_telegram_document(file_path, caption=""):
    env = load_env(ROOT)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID", "")
    mode = env.get("AGENT_MODE", "dry_run")
    path = Path(file_path)

    if mode == "dry_run" or not token or not chat_id:
        print("[DRY RUN] Telegram document:")
        print(path)
        if caption:
            print(caption)
        return {"ok": True, "dry_run": True}

    boundary = "----AgentHRBoundary7MA4YWxkTrZu0gW"
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    fields = {
        "chat_id": str(chat_id),
        "caption": caption[:1000],
    }

    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        f'Content-Disposition: form-data; name="document"; filename="{path.name}"\r\n'.encode("utf-8")
    )
    body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
    body.extend(path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    request = Request(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def get_telegram_updates(offset=None, timeout_seconds=5):
    env = load_env(ROOT)
    token = env.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("[DRY RUN] Telegram updates disabled until TELEGRAM_BOT_TOKEN is configured.")
        return {"ok": True, "result": []}

    params = {"timeout": timeout_seconds}
    if offset is not None:
        params["offset"] = offset
    query = urlencode(params)
    with urlopen(
        f"https://api.telegram.org/bot{token}/getUpdates?{query}",
        timeout=timeout_seconds + 10,
    ) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    result = send_telegram_message("Agent HR test: connexion Telegram prete.")
    print(json.dumps(result, indent=2, ensure_ascii=False))
