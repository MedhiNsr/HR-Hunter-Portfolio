import json
from pathlib import Path

from agent_hr import ROOT
from job_intelligence import clean_job_title


def build_portal_answers(title, company, location):
    return {
        "first_name": "Candidate",
        "last_name": "Candidate",
        "email": "candidate@example.com",
        "phone": "+352 000 00 00 00",
        "linkedin": "https://www.linkedin.com/in/demo-candidate/",
        "location": "Paris / Luxembourg",
        "availability": "Immediately available",
        "work_authorization": "French citizen, no visa sponsorship required for Luxembourg or France",
        "desired_role": clean_job_title(title),
        "target_company": company,
        "target_location": location,
        "salary_expectation": "Open to discussion",
        "notice_period": "No notice period",
        "languages": "French native, English fluent C2, Spanish fluent C2",
    }


def create_portal_pack(application_id, title, company, location, url, subject, body, cv_path, cover_letter_path=""):
    folder = ROOT / "applications" / f"application_{application_id:04d}"
    folder.mkdir(parents=True, exist_ok=True)
    pack = {
        "application_id": application_id,
        "title": clean_job_title(title),
        "company": company,
        "location": location,
        "url": url,
        "cv_path": str(cv_path),
        "cover_letter_path": str(cover_letter_path),
        "email_subject": subject,
        "message": body,
        "form_answers": build_portal_answers(title, company, location),
        "instructions": [
            "Open the portal URL.",
            "Use the CV prepared for this vacancy.",
            "Copy the prepared message when a motivation field is available.",
            "Validate before final submit if the portal asks irreversible questions.",
        ],
    }
    path = folder / "portal_pack.json"
    path.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
