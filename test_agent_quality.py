import gc
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document

import agent_hr
import application_preparer
import follow_up_worker
import gmail_inbox_monitor
import init_agent_db
import reporting
import workflow
from agent_hr import JobInput, score_job
from application_preparer import build_cover_letter, build_email
from cv_generator import generate_tailored_cv
from document_quality import validate_application_documents
from job_intelligence import build_job_fit, clean_job_title
from job_search import is_search_or_listing_result
from job_status_checker import check_job_is_open
from recruiter_contacts import email_is_named, score_contact_candidate
from gmail_inbox_monitor import classify_reply


class AgentQualityTests(unittest.TestCase):
    def isolated_database(self, folder):
        database = Path(folder) / "test_agent.sqlite3"
        original = (
            agent_hr.DB, init_agent_db.DB, workflow.DB, application_preparer.DB,
            follow_up_worker.DB, reporting.DB, gmail_inbox_monitor.DB,
        )
        agent_hr.DB = database
        init_agent_db.DB = database
        workflow.DB = database
        application_preparer.DB = database
        follow_up_worker.DB = database
        reporting.DB = database
        gmail_inbox_monitor.DB = database
        init_agent_db.initialize_database()
        return database, original

    def restore_databases(self, original):
        (
            agent_hr.DB, init_agent_db.DB, workflow.DB, application_preparer.DB,
            follow_up_worker.DB, reporting.DB, gmail_inbox_monitor.DB,
        ) = original

    def test_scheduled_message_is_persistently_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            _, original = self.isolated_database(folder)
            try:
                self.assertFalse(reporting.scheduled_notification_sent("morning_message_sent"))
                reporting.record_scheduled_notification("morning_message_sent")
                self.assertTrue(reporting.scheduled_notification_sent("morning_message_sent"))
            finally:
                self.restore_databases(original)

    def test_gmail_reply_classification_separates_acknowledgement(self):
        acknowledgement = classify_reply(
            "sender1@example.test", "Application received", "Thank you for applying."
        )
        positive = classify_reply(
            "sender2@example.test", "Re: Application", "Could you share your availability for a call?"
        )
        negative = classify_reply(
            "sender3@example.test", "Re: Application", "Unfortunately, we will not be moving forward."
        )
        self.assertEqual(acknowledgement, "acknowledgement")
        self.assertEqual(positive, "positive")
        self.assertEqual(negative, "negative")

    def test_contact_ranking_matches_policy(self):
        local_recruiter = score_contact_candidate(
            title="Talent Acquisition Partner",
            email="casey.sample@example.test",
            linkedin="https://linkedin.com/in/casey-sample",
            location="Luxembourg",
            target_location="Luxembourg",
            stored_priority=90,
        )
        emea_recruiter = score_contact_candidate(
            title="Senior Recruiter",
            email="alex.sample@example.test",
            linkedin="https://linkedin.com/in/alex",
            location="EMEA",
            target_location="Luxembourg",
            stored_priority=90,
        )
        local_manager = score_contact_candidate(
            title="AML Compliance Manager",
            email="taylor.sample@example.test",
            linkedin="https://linkedin.com/in/taylor-sample",
            location="Luxembourg",
            target_location="Luxembourg",
            stored_priority=90,
        )
        generic = score_contact_candidate(
            title="Careers",
            email="careers@example.com",
            location="Luxembourg",
            target_location="Luxembourg",
            stored_priority=30,
        )
        self.assertGreater(local_recruiter["score"], emea_recruiter["score"])
        self.assertGreater(emea_recruiter["score"], local_manager["score"])
        self.assertGreater(local_manager["score"], generic["score"])
        self.assertFalse(email_is_named("careers@example.com"))
        self.assertTrue(email_is_named("casey.sample@example.test"))

    def test_senior_five_year_role_is_penalized_without_false_language_risk(self):
        rules = init_agent_db.load_json(Path(__file__).parent / "config" / "scoring_rules.json")
        job = JobInput(
            source="EY",
            source_url="https://careers.ey.com/example",
            title="AML Analyst - Senior",
            company="EY Luxembourg",
            location="Luxembourg",
            description=(
                "To qualify you must have minimum 5 year(s) of relevant work experience. "
                "A fluent English level. Ideally, you will also have fluent French and/or German. "
                "Additional languages such as French or German are considered an asset. AML KYC compliance."
            ),
        )
        score, reasons, risks = score_job(job, rules)
        self.assertLess(score, 45)
        self.assertTrue(any("5 years" in risk for risk in risks))
        self.assertTrue(any("senior level" in risk for risk in risks))
        self.assertFalse(any("language" in risk.lower() for risk in risks))
        self.assertFalse(any("junior" in reason.lower() for reason in reasons))

    def test_optional_german_and_luxembourgish_do_not_create_risk(self):
        rules = init_agent_db.load_json(Path(__file__).parent / "config" / "scoring_rules.json")
        job = JobInput(
            source="jobs.lu",
            source_url="https://jobs.lu/example",
            title="Operational Risk Management Specialist",
            company="Banque centrale du Luxembourg",
            location="Luxembourg",
            description=(
                "Operational risk, internal controls and compliance. French and English are required; "
                "knowledge of Luxembourgish and German is considered an asset. Two-year fixed contract."
            ),
        )
        score, _, risks = score_job(job, rules)
        self.assertLessEqual(score, 95)
        self.assertGreaterEqual(score, 60)
        self.assertFalse(any("language" in risk.lower() for risk in risks))

    def test_mandatory_german_still_creates_a_real_risk(self):
        rules = init_agent_db.load_json(Path(__file__).parent / "config" / "scoring_rules.json")
        job = JobInput(
            source="test",
            source_url="https://example.invalid/mandatory-german",
            title="Compliance Analyst",
            company="Example Bank",
            location="Luxembourg",
            description="AML KYC compliance role. Fluent English and German are required.",
        )
        _, _, risks = score_job(job, rules)
        self.assertTrue(any("Mandatory unsupported language: German" in risk for risk in risks))

    def test_linkedin_french_result_page_is_not_treated_as_a_job(self):
        self.assertTrue(
            is_search_or_listing_result(
                "https://lu.linkedin.com/jobs/risk-analyst-luxembourg-emplois",
                "Postes de Risk Analyst Luxembourg : 1 000+ postes",
            )
        )

    def test_french_word_vie_is_not_the_vie_program(self):
        from agent_hr import contains_any

        self.assertFalse(contains_any("Votre perspective de vie change.", ["vie"]))
        self.assertTrue(contains_any("Offre VIE Compliance Luxembourg", ["vie"]))

    def test_exact_keywords_and_two_alignment_sentences(self):
        description = (
            "The role covers AML/CFT, enhanced due diligence, transaction monitoring, "
            "internal controls and regulatory monitoring in Luxembourg."
        )
        fit = build_job_fit("AML Compliance Analyst", "Example Bank", "Luxembourg", description)
        self.assertEqual(fit["specific_keywords"][:3], ["AML/CFT", "Enhanced Due Diligence", "Transaction Monitoring"])
        self.assertEqual(len(fit["alignment_sentences"]), 2)

        _, body = build_email(
            "AML Compliance Analyst",
            "Example Bank",
            "Luxembourg",
            "https://example.com/job",
            description,
            recipient_name="Casey Sample",
            recipient_email="casey.sample@example.test",
        )
        self.assertIn("Hello Julie,", body)
        self.assertIn("regulatory monitoring, internal controls and risk assessment", body)
        self.assertNotIn("Dear Hiring Team", body)
        self.assertNotIn("Role-relevant themes", body)

    def test_job_title_is_cleaned_for_candidate_documents(self):
        raw = "OPERATIONAL RISK MANAGEMENT (ORM) SPECIALIST (m/f/d) - career A1"
        self.assertEqual(clean_job_title(raw), "Operational Risk Management (ORM) Specialist")
        self.assertEqual(clean_job_title("AML Analyst (m/t/d) - career A1"), "AML Analyst")

    def test_cover_letter_uses_clean_title_and_natural_structure(self):
        raw = "OPERATIONAL RISK MANAGEMENT (ORM) SPECIALIST (m/f/d) - career A1"
        letter = build_cover_letter(
            raw,
            "Banque centrale du Luxembourg",
            "Luxembourg",
            "Operational risk, internal controls, DORA and second line of defence.",
        )
        self.assertIn("Application for Operational Risk Management (ORM) Specialist", letter)
        self.assertIn("Dear Recruitment Team,", letter)
        self.assertNotIn("m/f/d", letter)
        self.assertNotIn("career A1", letter)
        self.assertNotIn("Application message", letter)

    def test_verified_closed_offer_is_rejected_without_network(self):
        result = check_job_is_open(
            "https://example.invalid/job",
            "This job is no longer available.",
            page_verified=True,
        )
        self.assertEqual(result["status"], "closed")

    def test_cv_keeps_full_experience_and_target_location(self):
        app_id = 9901
        path = generate_tailored_cv(
            app_id,
            "AML Compliance Analyst",
            "Example Bank",
            "Luxembourg",
            "AML/CFT, KYC, enhanced due diligence and internal controls.",
        )
        try:
            text = "\n".join(p.text for p in Document(path).paragraphs)
            self.assertIn("Luxembourg | +33", text)
            self.assertIn("Professional Experience", text)
            self.assertNotIn("Selected Experience", text)
            self.assertIn("Qualitel", text)
            self.assertIn("Delivered DORA maturity assessments", text)
            self.assertNotIn("targeting the", text)
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)

    def test_uncertain_offer_goes_to_human_review(self):
        with tempfile.TemporaryDirectory() as folder:
            database, original = self.isolated_database(folder)
            try:
                job = JobInput(
                    source="test",
                    source_url="https://example.invalid/uncertain-job",
                    title="Compliance Analyst",
                    company="A verifier",
                    location="Luxembourg",
                    description="Apply for a compliance analyst role covering regulatory controls.",
                    page_verified=True,
                )
                with patch.object(workflow, "send_telegram_message", return_value={"ok": True, "dry_run": True}):
                    result = workflow.propose_job(job)
                with sqlite3.connect(database) as conn:
                    status = conn.execute("SELECT status FROM applications ORDER BY id DESC LIMIT 1").fetchone()[0]
                conn.close()
                self.assertTrue(result["proposed"])
                self.assertEqual(result["reason"], "human_review")
                self.assertEqual(status, "review_required")
            finally:
                self.restore_databases(original)
                gc.collect()

    def test_direct_job_email_requires_second_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            database, original = self.isolated_database(folder)
            original_application_dir = application_preparer.APPLICATION_DIR
            application_preparer.APPLICATION_DIR = Path(folder) / "applications"
            try:
                with sqlite3.connect(database) as conn:
                    conn.execute(
                        """
                        INSERT INTO jobs(
                            source, source_url, title, company, location, description,
                            score, status, contact_email, application_channel
                        ) VALUES(?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            "test", "https://example.invalid/direct-email", "AML Analyst",
                            "Example Bank", "Luxembourg", "AML/CFT and KYC role.",
                            90, "proposed", "casey.sample@example.test", "email",
                        ),
                    )
                    job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.execute(
                        """
                        INSERT INTO applications(job_id, channel, status, score, approved_at)
                        VALUES(?,?,?,?,CURRENT_TIMESTAMP)
                        """,
                        (job_id, "telegram_validation", "validated", 90),
                    )
                conn.close()
                dummy_docx = Path(folder) / "cv.docx"
                dummy_pdf = Path(folder) / "cv.pdf"
                with (
                    patch.object(application_preparer, "generate_tailored_cv", return_value=dummy_docx),
                    patch.object(application_preparer, "docx_to_pdf", return_value=dummy_pdf),
                    patch.object(application_preparer, "text_to_pdf", return_value=Path(folder) / "letter.pdf"),
                    patch.object(application_preparer, "build_quality_report", return_value={
                        "passed": True,
                        "errors": [],
                        "warnings": [],
                        "fingerprint": "test-fingerprint",
                    }),
                    patch.object(application_preparer, "send_telegram_message", return_value={"ok": True}),
                    patch.object(application_preparer, "send_email") as send_email,
                ):
                    application_preparer.prepare_validated_applications(limit=1)
                with sqlite3.connect(database) as conn:
                    row = conn.execute(
                        "SELECT status, recipient_email, recipient_is_named FROM applications"
                    ).fetchone()
                conn.close()
                self.assertEqual(row, ("contact_review", "casey.sample@example.test", 1))
                send_email.assert_not_called()
            finally:
                application_preparer.APPLICATION_DIR = original_application_dir
                self.restore_databases(original)
                gc.collect()

    def test_generic_email_never_receives_second_followup(self):
        with tempfile.TemporaryDirectory() as folder:
            database, original = self.isolated_database(folder)
            try:
                with sqlite3.connect(database) as conn:
                    conn.execute(
                        """
                        INSERT INTO jobs(source, source_url, title, company, location, description, score, status)
                        VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (
                            "test", "https://example.invalid/generic-followup", "Compliance Analyst",
                            "Example Bank", "Luxembourg", "Compliance role", 80, "proposed",
                        ),
                    )
                    job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    conn.execute(
                        """
                        INSERT INTO applications(
                            job_id, channel, status, score, recipient_email,
                            recipient_is_named, follow_up_due_at
                        ) VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)
                        """,
                        (job_id, "email", "follow_up_1_sent", 80, "careers@example.com", 0),
                    )
                conn.close()
                with patch.object(follow_up_worker, "send_email") as send_email:
                    result = follow_up_worker.process_due_followups()
                with sqlite3.connect(database) as conn:
                    due = conn.execute("SELECT follow_up_due_at FROM applications").fetchone()[0]
                conn.close()
                self.assertIsNone(due)
                self.assertEqual(result[0]["status"], "second_followup_skipped_generic")
                send_email.assert_not_called()
            finally:
                self.restore_databases(original)
                gc.collect()


if __name__ == "__main__":
    unittest.main()
