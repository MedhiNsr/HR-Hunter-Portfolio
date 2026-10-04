import json

from telegram_client import get_telegram_updates


def extract_chats(updates):
    chats = []
    seen = set()
    for update in updates.get("result", []):
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id in seen or chat_id is None:
            continue
        seen.add(chat_id)
        chats.append(
            {
                "chat_id": chat_id,
                "type": chat.get("type", ""),
                "title": chat.get("title", ""),
                "username": chat.get("username", ""),
                "last_message": message.get("text", ""),
            }
        )
    return chats


def main():
    updates = get_telegram_updates()
    chats = extract_chats(updates)
    if not chats:
        print(
            "Aucun chat trouve. Ajoute le bot au groupe Telegram, envoie 'go agent' dans le groupe, puis relance ce test."
        )
        return
    print(json.dumps(chats, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
