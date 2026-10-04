import argparse
import json
import sqlite3

from agent_hr import ROOT, ensure_database


DB = ROOT / "agent_hr.sqlite3"

COMMON_ALLOWED_RECRUITER_LOCATION_KEYWORDS = ["europe", "emea"]

TARGET_LOCATION_ALLOWED_KEYWORDS = {
    "luxembourg": ["luxembourg"],
    "paris": ["france", "paris"],
    "france": ["france", "paris"],
}

BLOCKED_RECRUITER_LOCATION_KEYWORDS = [
    "united states",
    "washington",
    "district of columbia",
    "new york",
    "canada",
    "hong kong",
]

GENERIC_EMAIL_PREFIXES = {
    "career", "careers", "contact", "hr", "info", "job", "jobs",
    "recruiting", "recruitment", "recrutement", "talent", "people",
}

RECRUITER_TITLE_KEYWORDS = ["talent", "recruit", "human resources", "hr business partner", "people partner"]
MANAGER_TITLE_KEYWORDS = ["compliance", "risk", "aml", "kyc", "financial crime", "manager", "head"]


def normalize_company(value):
    return (value or "").lower().replace("www.", "").strip()


def email_is_named(email):
    local = (email or "").split("@", 1)[0].lower().strip()
    if not local or local in GENERIC_EMAIL_PREFIXES:
        return False
    if any(local.startswith(prefix + ".") or local.startswith(prefix + "-") for prefix in GENERIC_EMAIL_PREFIXES):
        return False
    return "." in local or "-" in local or len(local) >= 7


def contact_location_class(location, notes="", target_location=""):
    text = f"{location or ''} {notes or ''}".lower()
    target = (target_location or "").lower()
    if "luxembourg" in target and "luxembourg" in text:
        return "local"
    if any(place in target for place in ["paris", "france"]) and any(place in text for place in ["paris", "france"]):
        return "local"
    if any(keyword in text for keyword in COMMON_ALLOWED_RECRUITER_LOCATION_KEYWORDS):
        return "emea"
    return "other"


def score_contact_candidate(title="", email="", linkedin="", location="", notes="", target_location="", stored_priority=50):
    lowered_title = (title or "").lower()
    named = email_is_named(email)
    location_class = contact_location_class(location, notes, target_location)

    if any(keyword in lowered_title for keyword in RECRUITER_TITLE_KEYWORDS):
        role = "recruiter"
        score = 60
    elif any(keyword in lowered_title for keyword in MANAGER_TITLE_KEYWORDS):
        role = "business_manager"
        score = 45
    else:
        role = "other_contact"
        score = 35

    if location_class == "local":
        score += 25
    elif location_class == "emea":
        score += 15
    if named:
        score += 8
    if linkedin:
        score += 4
    score += max(0, min(3, int(stored_priority or 0) // 30))
    score = min(100, score)
    reason = f"{role}; {location_class}; {'named' if named else 'generic'} email"
    return {"score": score, "reason": reason, "is_named": named, "role": role, "location_class": location_class}


def recruiter_location_is_allowed(location, notes="", target_location=""):
    text = f"{location or ''} {notes or ''}".lower()
    if any(keyword in text for keyword in BLOCKED_RECRUITER_LOCATION_KEYWORDS):
        return False
    if any(keyword in text for keyword in COMMON_ALLOWED_RECRUITER_LOCATION_KEYWORDS):
        return True

    target_text = (target_location or "").lower()
    target_keywords = []
    for target, allowed_keywords in TARGET_LOCATION_ALLOWED_KEYWORDS.items():
        if target in target_text:
            target_keywords.extend(allowed_keywords)

    if target_keywords:
        return any(keyword in text for keyword in target_keywords)
    return False


def upsert_recruiter(contact):
    ensure_database()
    with sqlite3.connect(DB) as conn:
        conn.execute(
            """
            INSERT INTO recruiter_contacts(source, full_name, title, company, domain, email, linkedin, location, priority, notes)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(email) DO UPDATE SET
                full_name=excluded.full_name,
                title=excluded.title,
                company=excluded.company,
                domain=excluded.domain,
                linkedin=excluded.linkedin,
                location=excluded.location,
                priority=excluded.priority,
                notes=excluded.notes,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                contact.get("source", "Lusha"),
                contact["full_name"],
                contact.get("title", ""),
                contact.get("company", ""),
                normalize_company(contact.get("domain", "")),
                contact["email"],
                contact.get("linkedin", ""),
                contact.get("location", "Luxembourg"),
                contact.get("priority", 50),
                contact.get("notes", ""),
            ),
        )


def find_recruiter_for_company(company, description="", source_url="", target_location=""):
    ensure_database()
    haystack = " ".join([company or "", description or "", source_url or ""]).lower()
    with sqlite3.connect(DB) as conn:
        rows = conn.execute(
            """
            SELECT full_name, title, company, domain, email, linkedin, location, priority, notes
            FROM recruiter_contacts
            ORDER BY priority DESC, updated_at DESC
            """
        ).fetchall()
    candidates = []
    for full_name, title, contact_company, domain, email, linkedin, location, priority, notes in rows:
        if not recruiter_location_is_allowed(location, notes, target_location):
            continue
        company_key = normalize_company(contact_company)
        domain_key = normalize_company(domain)
        if (company_key and company_key in haystack) or (domain_key and domain_key in haystack):
            scored = score_contact_candidate(
                title=title,
                email=email,
                linkedin=linkedin,
                location=location,
                notes=notes,
                target_location=target_location,
                stored_priority=priority,
            )
            candidates.append({
                "full_name": full_name,
                "title": title,
                "company": contact_company,
                "domain": domain,
                "email": email,
                "linkedin": linkedin,
                "location": location,
                "priority": priority,
                "contact_score": scored["score"],
                "contact_reason": scored["reason"],
                "is_named": scored["is_named"],
            })
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["contact_score"], item["priority"]))


def import_json(path):
    contacts = json.loads(open(path, encoding="utf-8").read())
    for contact in contacts:
        upsert_recruiter(contact)
    return len(contacts)


def main():
    parser = argparse.ArgumentParser(description="Manage recruiter contacts.")
    parser.add_argument("--import-json")
    args = parser.parse_args()
    if args.import_json:
        print(import_json(args.import_json))


if __name__ == "__main__":
    main()
