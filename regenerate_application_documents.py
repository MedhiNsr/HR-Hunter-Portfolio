import argparse
import json
import sqlite3

from agent_hr import ROOT
from application_preparer import build_cover_letter, build_email
from cv_generator import generate_tailored_cv
from document_outputs import docx_to_pdf, text_to_pdf
from document_quality import build_quality_report
from job_analysis import analyse_job
from portal_pack import create_portal_pack


DB = ROOT / "agent_hr.sqlite3"


def regenerate(application_id):
    conn = sqlite3.connect(DB)
    try:
        row = conn.execute(
            """
            SELECT jobs.title, jobs.company, jobs.location, jobs.source_url, jobs.description,
                   applications.recipient_name, applications.recipient_email
            FROM applications JOIN jobs ON jobs.id=applications.job_id
            WHERE applications.id=?
            """,
            (application_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Application {application_id} not found")
        title, company, location, url, description, recipient_name, recipient_email = row
        analysis = analyse_job(title, company, location, description)
        subject, email_body = build_email(
            title, company, location, url, description, recipient_name or "", recipient_email or ""
        )
        cover_letter = build_cover_letter(title, company, location, description, recipient_name or "")
        folder = ROOT / "applications" / f"application_{application_id:04d}"
        folder.mkdir(parents=True, exist_ok=True)
        email_path = folder / "email_draft.txt"
        email_path.write_text(f"Subject: {subject}\n\n{email_body}", encoding="utf-8")
        cv_docx = generate_tailored_cv(application_id, title, company, location, description, analysis=analysis)
        cv_pdf = docx_to_pdf(cv_docx)
        safe_company = "".join(ch if ch.isalnum() else "_" for ch in company).strip("_")[:45] or "Company"
        letter_pdf = text_to_pdf(
            cover_letter,
            folder / f"Demo_Candidate_Cover_Letter_{safe_company}.pdf",
            title=None,
        )
        quality_report = build_quality_report(cv_pdf, letter_pdf, analysis=analysis, docx_path=cv_docx)
        if not quality_report["passed"]:
            raise ValueError("Document quality control failed: " + "; ".join(quality_report["errors"]))
        portal_pack = create_portal_pack(
            application_id, title, company, location, url, subject, email_body, cv_pdf, letter_pdf
        )
        conn.execute(
            """
            UPDATE applications
            SET cv_path=?, cover_letter_path=?, email_subject=?, email_body=?, score=?,
                quality_report_json=?, document_fingerprint=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                str(cv_pdf), str(letter_pdf), subject, email_body, analysis["score"],
                json.dumps(quality_report, ensure_ascii=False, sort_keys=True),
                quality_report["fingerprint"], application_id,
            ),
        )
        conn.execute(
            """
            UPDATE jobs
            SET score=?, analysis_json=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=(SELECT job_id FROM applications WHERE id=?)
            """,
            (analysis["score"], json.dumps(analysis, ensure_ascii=False, sort_keys=True), application_id),
        )
        conn.commit()
        return {
            "application_id": application_id,
            "cv_docx": str(cv_docx),
            "cv_pdf": str(cv_pdf),
            "cover_letter_pdf": str(letter_pdf),
            "email_draft": str(email_path),
            "portal_pack": str(portal_pack),
            "quality_control": quality_report,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("application_id", type=int)
    args = parser.parse_args()
    print(json.dumps(regenerate(args.application_id), indent=2, ensure_ascii=False))
