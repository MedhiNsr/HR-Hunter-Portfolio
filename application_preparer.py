import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path

from agent_hr import ROOT, ensure_database
from cv_generator import generate_tailored_cv
from document_quality import build_quality_report
from document_outputs import docx_to_pdf, text_to_pdf
from gmail_sender import send_email
from job_analysis import analyse_job
from job_intelligence import clean_job_title
from portal_pack import create_portal_pack
from recruiter_contacts import (
    find_recruiter_for_company,
    recruiter_location_is_allowed,
    score_contact_candidate,
)
from telegram_client import send_telegram_document, send_telegram_message


DB = ROOT / "agent_hr.sqlite3"
APPLICATION_DIR = ROOT / "applications"
def first_name_from_contact(name="", email=""):
    name = (name or "").strip()
    if name:
        return name.split()[0].strip(" ,")
    local_part = (email or "").split("@", 1)[0]
    if "." in local_part:
        candidate = local_part.split(".", 1)[0]
        if candidate and candidate.lower() not in {"hr", "jobs", "careers", "recruitment", "recrutement"}:
            return candidate.capitalize()
    return ""


def build_email(title, company, location, url, description, recipient_name="", recipient_email=""):
    analysis = analyse_job(title, company, location, description)
    job_title = analysis["job_title"]
    family = analysis["role_family"]
    subject = f"Application for {job_title} - Demo Candidate"
    first_name = first_name_from_contact(recipient_name, recipient_email)
    greeting = f"Hello {first_name}," if first_name else "Hello,"
    if family == "operational_risk":
        evidence = "At EURUS, I supported banks and insurers with DORA maturity assessments, risk matrices, regulatory monitoring and prioritised remediation roadmaps."
        contribution = "The role's focus on operational risk and control effectiveness is therefore a close fit with the work I have already performed in regulated environments."
    elif family == "aml_kyc":
        evidence = "My financial-services consulting experience covers regulatory monitoring, internal controls and risk assessment, and I am currently completing specialist AML/KYC training."
        contribution = "I would bring careful analysis and reliable documentation while developing the direct case-handling experience required in an AML/KYC team."
    elif family == "change_transformation":
        evidence = "At AP-HP and DXC Technology, I supported software deployments, user adoption, training, operational procedures and PMO follow-up in complex transformation programmes."
        contribution = "That combination of delivery discipline and stakeholder coordination is directly relevant to the change responsibilities described in the role."
    else:
        evidence = "At EURUS, I worked on regulatory monitoring, internal controls, risk assessment and remediation planning for regulated organisations."
        contribution = "My earlier transformation assignments also strengthened my ability to document processes and coordinate stakeholders in complex environments."
    body = f"""{greeting}

I am applying for the {job_title} position at {company}.

{evidence}

{contribution}

I am available immediately, fluent in French, English and Spanish, and authorised to work in Luxembourg and France without sponsorship.

My CV is attached. I would welcome the opportunity to discuss my application.

Kind regards,

Demo Candidate
+352 000 00 00 00
candidate@example.com
LinkedIn: https://www.linkedin.com/in/demo-candidate/

"""
    return subject, body


def build_cover_letter(title, company, location, description, recipient_name=""):
    analysis = analyse_job(title, company, location, description)
    job_title = analysis["job_title"]
    family = analysis["role_family"]
    first_name = first_name_from_contact(recipient_name, "")
    addressee = recipient_name.strip() if recipient_name else "Recruitment Team"
    greeting = f"Dear {first_name}," if first_name else "Dear Recruitment Team,"
    supported = analysis["supported_keywords"][:3]
    focus = ", ".join(supported[:-1]) + (f" and {supported[-1]}" if len(supported) > 1 else (supported[0] if supported else "the role's core responsibilities"))
    if family == "operational_risk":
        if "banque centrale" in company.lower():
            opening = (
                f"I am applying for the {job_title} position at {company}. The opportunity to support operational-risk oversight "
                "in a central-banking environment is particularly relevant to my recent consulting work."
            )
        else:
            opening = (
                f"I am applying for the {job_title} position at {company}. Its focus on {focus} closely matches my recent "
                "consulting work for financial institutions."
            )
        paragraphs = [
            opening,
            (
                "At EURUS, I supported DORA maturity assessments for banks and insurers. I identified resilience and control gaps, "
                "used risk matrices to prioritise issues, monitored DORA, NIS2 and ISO 27001, and helped translate findings into "
                "workable remediation roadmaps."
            ),
            (
                "My earlier assignments at AP-HP and DXC Technology added a practical delivery dimension: process documentation, "
                "stakeholder coordination, user training and structured follow-up. I would bring that combination of risk analysis "
                "and implementation discipline to the team."
            ),
        ]
    elif family == "aml_kyc":
        paragraphs = [
            (
                f"I am applying for the {job_title} position at {company}. The role offers a credible next step from my work in "
                "regulatory compliance and internal controls towards a dedicated AML/KYC position. Its responsibilities around "
                "client reviews and transaction monitoring are areas in which I am ready to build direct practical experience."
            ),
            (
                "At EURUS, I monitored regulatory developments, assessed control frameworks and supported remediation planning for "
                "banks and insurers. This required careful analysis, reliable documentation and close coordination with client stakeholders."
            ),
            (
                "I am currently completing specialist AML/KYC training. I would bring a rigorous consulting foundation while "
                "building the direct operational experience expected from an early-career member of the team."
            ),
        ]
    elif family == "change_transformation":
        paragraphs = [
            (
                f"I am applying for the {job_title} position at {company}. The emphasis on {focus} is closely aligned with my "
                "experience supporting technology-enabled change in complex organisations. The position brings together the "
                "delivery, communication and adoption work that has shaped my assignments since 2023."
            ),
            (
                "At AP-HP, I supported the deployment of the ORBIS patient-record system by preparing procedures and user guides, "
                "training staff, monitoring progress and helping departments after go-live."
            ),
            (
                "At DXC Technology, I contributed to project-scoping workshops, PMO reporting, strategic roadmaps and operating-model "
                "work. These assignments developed the practical coordination and communication skills needed to move change from plan to adoption."
            ),
        ]
    else:
        paragraphs = [
            (
                f"I am applying for the {job_title} position at {company}. The role's emphasis on {focus} reflects the core of my "
                "recent work in regulated environments."
            ),
            (
                "At EURUS, I supported financial-services clients with regulatory monitoring, internal-control work, risk assessment "
                "and remediation planning. I also prepared workshops and training materials to make regulatory requirements usable in practice."
            ),
            (
                "Earlier transformation roles strengthened my process documentation and stakeholder coordination. Together, these experiences "
                "would allow me to contribute structured analysis without losing sight of implementation."
            ),
        ]
    work_country = "France" if "paris" in (location or "").lower() else "Luxembourg and France"
    closing = (
        f"A native French speaker fluent in English and Spanish, I am available immediately and authorised to work in {work_country} "
        "without sponsorship. I would welcome the opportunity to discuss how my experience could support your team."
    )
    lines = [
        "Demo Candidate",
        f"{location} | +352 000 00 00 00 | candidate@example.com",
        "linkedin.com/in/demo-candidate",
        "",
        date.today().strftime("%d %B %Y"),
        addressee,
        company,
        location,
        "",
        f"Application for {job_title}",
        "",
        greeting,
        "",
    ]
    for paragraph in paragraphs:
        lines.extend([paragraph, ""])
    lines.extend([closing, "", "Kind regards,", "", "Demo Candidate"])
    return "\n".join(lines)


def prepare_validated_applications(limit=10, application_id=None):
    ensure_database()
    APPLICATION_DIR.mkdir(parents=True, exist_ok=True)
    prepared = []

    with sqlite3.connect(DB, timeout=30) as conn:
        conn.execute("PRAGMA busy_timeout=30000")
        rows = conn.execute(
            """
            SELECT applications.id, jobs.title, jobs.company, jobs.location, jobs.source_url,
                   applications.recipient_email,
                   jobs.contact_email,
                   jobs.application_channel,
                   jobs.description,
                   applications.status,
                   applications.recipient_name,
                   applications.recipient_linkedin,
                   applications.recipient_is_named,
                   applications.contact_score,
                   applications.contact_reason
            FROM applications
            JOIN jobs ON jobs.id = applications.job_id
            WHERE applications.status IN ('validated', 'contact_confirmed')
              AND (? IS NULL OR applications.id = ?)
            ORDER BY applications.approved_at ASC
            LIMIT ?
            """,
            (application_id, application_id, limit),
        ).fetchall()

        for (
            app_id, title, company, location, url, application_email, job_email,
            application_channel, description, current_status, stored_name,
            stored_linkedin, stored_is_named, stored_contact_score, stored_contact_reason,
        ) in rows:
            analysis = analyse_job(title, company, location, description)
            final_score = analysis["score"]
            conn.execute(
                "UPDATE jobs SET score=?, analysis_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=(SELECT job_id FROM applications WHERE id=?)",
                (final_score, json.dumps(analysis, ensure_ascii=False, sort_keys=True), app_id),
            )
            conn.execute("UPDATE applications SET score=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (final_score, app_id))
            conn.commit()
            seniority_block = analysis["seniority"]["senior_title"] and (analysis["seniority"]["required_years"] or 0) >= 5
            if final_score < 45 or seniority_block:
                conn.execute(
                    """
                    UPDATE applications
                    SET status='candidate_mismatch_review', notes=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    ("Preparation blocked after source-CV comparison: " + "; ".join(analysis["risks"]), app_id),
                )
                send_telegram_message(
                    f"Candidate, je n'ai rien envoye pour l'App {app_id} ({clean_job_title(title)} - {company}).\n"
                    "L'analyse detaillee confirme un ecart trop important sur la seniorite ou un critere obligatoire. "
                    "Je la conserve en revue plutot que de deformer ton parcours."
                )
                prepared.append(f"BLOCKED application {app_id}: candidate mismatch")
                continue
            recruiter_match = None
            recipient_email = application_email or job_email
            recipient_name = stored_name or ""
            recipient_linkedin = stored_linkedin or ""
            recipient_is_named = bool(stored_is_named)
            contact_score = int(stored_contact_score or 0)
            contact_reason = stored_contact_reason or ""
            if not recipient_email:
                recruiter_match = find_recruiter_for_company(company, description, url, location)
                if recruiter_match:
                    if recruiter_location_is_allowed(recruiter_match.get("location", ""), target_location=location):
                        recipient_email = recruiter_match["email"]
                        application_channel = "email_lusha_recruiter_match"
                        recipient_name = recruiter_match.get("full_name", "")
                        recipient_linkedin = recruiter_match.get("linkedin", "")
                        recipient_is_named = bool(recruiter_match.get("is_named"))
                        contact_score = recruiter_match.get("contact_score", 0)
                        contact_reason = recruiter_match.get("contact_reason", "")
                    else:
                        recruiter_match = None
            elif not contact_reason:
                recipient_name = recipient_name or first_name_from_contact("", recipient_email)
                scored_contact = score_contact_candidate(
                    title="job contact",
                    email=recipient_email,
                    linkedin=recipient_linkedin,
                    location=location,
                    target_location=location,
                    stored_priority=30,
                )
                recipient_is_named = scored_contact["is_named"]
                contact_score = scored_contact["score"]
                contact_reason = "contact from job posting; " + scored_contact["reason"]
            subject, body = build_email(title, company, location, url, description, recipient_name, recipient_email)
            cover_letter = build_cover_letter(title, company, location, description, recipient_name)
            folder = APPLICATION_DIR / f"application_{app_id:04d}"
            folder.mkdir(parents=True, exist_ok=True)
            email_path = folder / "email_draft.txt"
            email_path.write_text(f"Subject: {subject}\n\n{body}", encoding="utf-8")
            tailored_cv_docx = generate_tailored_cv(app_id, title, company, location, description, analysis=analysis)
            tailored_cv_pdf = docx_to_pdf(tailored_cv_docx)
            safe_company = "".join(ch if ch.isalnum() else "_" for ch in company).strip("_")[:45] or "Company"
            letter_pdf = text_to_pdf(
                cover_letter,
                folder / f"Demo_Candidate_Cover_Letter_{safe_company}.pdf",
                title=None,
            )
            quality_report = build_quality_report(
                tailored_cv_pdf, letter_pdf, analysis=analysis, docx_path=tailored_cv_docx
            )
            documents_ok, quality_errors = quality_report["passed"], quality_report["errors"]
            if not documents_ok:
                conn.execute(
                    """
                    UPDATE applications
                    SET status='document_review_required',
                        cv_path=?,
                        cover_letter_path=?,
                        email_subject=?,
                        email_body=?,
                        notes=?,
                        quality_report_json=?,
                        document_fingerprint=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        str(tailored_cv_pdf), str(letter_pdf), subject, body,
                        "Documents blocked by quality control: " + "; ".join(quality_errors),
                        json.dumps(quality_report, ensure_ascii=False, sort_keys=True),
                        quality_report.get("fingerprint", ""), app_id,
                    ),
                )
                conn.execute(
                    "INSERT INTO events(event_type, detail) VALUES(?,?)",
                    ("document_quality_blocked", f"application_id={app_id}; errors={' | '.join(quality_errors)}"),
                )
                prepared.append(f"BLOCKED application {app_id}: {'; '.join(quality_errors)}")
                continue

            conn.execute(
                """
                UPDATE applications
                SET cv_path=?, cover_letter_path=?, quality_report_json=?, document_fingerprint=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    str(tailored_cv_pdf), str(letter_pdf),
                    json.dumps(quality_report, ensure_ascii=False, sort_keys=True),
                    quality_report["fingerprint"], app_id,
                ),
            )
            conn.commit()

            if recipient_email:
                if current_status != "contact_confirmed":
                    conn.execute(
                        """
                        UPDATE applications
                        SET status='contact_review',
                            recipient_email=?,
                            recipient_name=?,
                            recipient_linkedin=?,
                            recipient_is_named=?,
                            contact_score=?,
                            contact_reason=?,
                            email_subject=?,
                            email_body=?,
                            cv_path=?,
                            cover_letter_path=?,
                            notes='Waiting for second Telegram confirmation of recipient contact.',
                            updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                        """,
                        (
                            recipient_email, recipient_name, recipient_linkedin,
                            int(recipient_is_named), contact_score, contact_reason,
                            subject, body, str(tailored_cv_pdf), str(letter_pdf), app_id,
                        ),
                    )
                    conn.commit()
                    contact_name = recipient_name or "boite de recrutement generique"
                    send_telegram_message(
                        f"Candidate, la candidature est prete mais rien n'a encore ete envoye.\n\n"
                        f"App {app_id}: {clean_job_title(title)} - {company}\n"
                        f"Le bot propose d'envoyer l'email a: {contact_name}\n"
                        f"Email: {recipient_email}\n"
                        f"LinkedIn: {recipient_linkedin or 'non disponible'}\n"
                        f"Qualite contact: {contact_score}/100 - {contact_reason}\n\n"
                        f"Si tu reponds ok contact {app_id}, le bot enverra l'email et le CV PDF.\n"
                        f"Si tu reponds non {app_id}, rien ne sera envoye."
                    )
                    prepared.append(str(email_path))
                    continue

            if recipient_email:
                try:
                    send_result = send_email(recipient_email, subject, body, attachments=[tailored_cv_pdf])
                    if send_result.get("dry_run"):
                        conn.execute(
                            """
                            UPDATE applications
                            SET status='prepared_dry_run',
                                recipient_email=?,
                                cv_path=?,
                                email_subject=?,
                                email_body=?,
                                notes='Dry-run only: email was prepared but not sent.',
                                updated_at=CURRENT_TIMESTAMP
                            WHERE id=?
                            """,
                            (recipient_email, str(tailored_cv_pdf), subject, body, app_id),
                        )
                        send_telegram_message(
                            f"Simulation candidature prete.\n"
                            f"App {app_id}: {title} - {company}\n"
                            f"Destinataire: {recipient_email}\n"
                            f"CV PDF pret."
                        )
                        prepared.append(str(email_path))
                        continue
                    conn.execute(
                        """
                        UPDATE applications
                        SET status='sent',
                            recipient_email=?,
                            cv_path=?,
                            email_subject=?,
                            email_body=?,
                            sent_at=CURRENT_TIMESTAMP,
                            follow_up_due_at=DATETIME(CURRENT_TIMESTAMP, '+5 days'),
                            notes='Sent automatically after Telegram validation.',
                            updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                        """,
                            (recipient_email, str(tailored_cv_pdf), subject, body, app_id),
                    )
                    send_telegram_message(
                        f"C'est envoye par email.\n"
                        f"App {app_id}: {clean_job_title(title)} - {company}\n"
                        f"Le bot a envoye le message et le CV PDF. Tu n'as rien a faire maintenant.\n"
                        f"Une relance est prevue a J+5 si personne ne repond."
                    )
                    conn.execute(
                        "INSERT INTO events(event_type, detail) VALUES(?,?)",
                        ("application_sent", f"application_id={app_id}; recipient={recipient_email}"),
                    )
                    prepared.append(str(email_path))
                    continue
                except Exception as exc:
                    conn.execute(
                        """
                        UPDATE applications
                        SET status='send_failed',
                            recipient_email=?,
                            sent_error=?,
                            cv_path=?,
                            email_subject=?,
                            email_body=?,
                            updated_at=CURRENT_TIMESTAMP
                        WHERE id=?
                        """,
                        (recipient_email, str(exc), str(tailored_cv_pdf), subject, body, app_id),
                    )
                    send_telegram_message(
                        f"L'envoi automatique a echoue. Rien n'a ete envoye.\n\n"
                        f"App {app_id}: {clean_job_title(title)} - {company}\n"
                        f"Le CV PDF et la lettre sont prets. Il faut maintenant effectuer l'envoi manuellement."
                    )
                    send_telegram_document(tailored_cv_pdf, f"CV PDF - App {app_id} - {company}")
                    send_telegram_document(letter_pdf, f"Lettre de motivation - App {app_id} - {company}")
                    continue

            telegram_summary = (
                f"Action requise de ta part: candidature sur le site.\n\n"
                f"App {app_id}: {clean_job_title(title)} - {company}\n"
                f"Lieu: {location}\n"
                f"Le bot n'a pas postule et n'a rien envoye.\n\n"
                f"1. Ouvre ce lien: {url}\n"
                f"2. Depose le CV PDF et la lettre PDF envoyes ci-dessous.\n"
                f"3. Verifie les informations puis valide la candidature sur le site.\n\n"
                f"Si tu trouves un email recruteur, reponds: email recruiter@example.com"
            )
            portal_pack = create_portal_pack(
                app_id, title, company, location, url, subject, body, tailored_cv_pdf, letter_pdf
            )
            send_telegram_message(telegram_summary)
            send_telegram_document(tailored_cv_pdf, f"CV PDF - App {app_id} - {company}")
            send_telegram_document(letter_pdf, f"Lettre de motivation - App {app_id} - {company}")

            conn.execute(
                """
                UPDATE applications
                SET status='manual_action_required',
                    cv_path=?,
                    cover_letter_path=?,
                    email_subject=?,
                    email_body=?,
                    follow_up_due_at=DATETIME(CURRENT_TIMESTAMP, '+7 days'),
                    notes='Prepared after Telegram validation, but no recipient email was available.',
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (str(tailored_cv_pdf), str(letter_pdf), subject, body, app_id),
            )
            conn.execute(
                "INSERT INTO events(event_type, detail) VALUES(?,?)",
                ("application_prepared", f"application_id={app_id}; email_draft={email_path}"),
            )
            conn.commit()
            prepared.append(str(email_path))

    return prepared


def main():
    parser = argparse.ArgumentParser(description="Prepare validated Agent HR applications.")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    prepared = prepare_validated_applications(limit=args.limit)
    if prepared:
        print("\n".join(prepared))
    else:
        print("No validated application to prepare.")


if __name__ == "__main__":
    main()
