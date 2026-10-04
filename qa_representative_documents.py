import json

from application_preparer import build_cover_letter
from cv_generator import generate_tailored_cv
from document_outputs import docx_to_pdf, text_to_pdf
from document_quality import build_quality_report
from job_analysis import analyse_job


CASES = [
    {
        "id": 9811,
        "title": "Operational Risk Management (ORM) Specialist (m/f/d) - career A1",
        "company": "Banque centrale du Luxembourg",
        "location": "Luxembourg",
        "description": "Operational risk assessments, risk matrices, internal controls, DORA, governance and remediation plans. Fluent English required; French or German is an asset.",
    },
    {
        "id": 9812,
        "title": "Junior AML/KYC Analyst",
        "company": "Example Private Bank",
        "location": "Luxembourg",
        "description": "Junior role supporting AML/KYC reviews, customer due diligence and transaction monitoring. English and French required. Training provided.",
    },
    {
        "id": 9813,
        "title": "Change Management Consultant",
        "company": "Transformation Partners",
        "location": "Paris",
        "description": "Change management role covering stakeholder workshops, user adoption, training, operating model, PMO, project monitoring and digital transformation. English and French required.",
    },
]


def run():
    results = []
    for case in CASES:
        analysis = analyse_job(case["title"], case["company"], case["location"], case["description"])
        docx_path = generate_tailored_cv(case["id"], case["title"], case["company"], case["location"], case["description"], analysis=analysis)
        cv_pdf = docx_to_pdf(docx_path)
        safe_company = "".join(ch if ch.isalnum() else "_" for ch in case["company"]).strip("_")
        letter_pdf = text_to_pdf(
            build_cover_letter(case["title"], case["company"], case["location"], case["description"]),
            docx_path.parent / f"Demo_Candidate_Cover_Letter_{safe_company}.pdf",
        )
        quality = build_quality_report(cv_pdf, letter_pdf, analysis=analysis, docx_path=docx_path)
        results.append({
            "case": case["company"],
            "score": analysis["score"],
            "dimensions": analysis["dimensions"],
            "cv": str(cv_pdf),
            "letter": str(letter_pdf),
            "quality": quality,
        })
    output = "\n".join(json.dumps(item, ensure_ascii=False) for item in results)
    report_path = docx_path.parents[2] / "tmp" / "representative_document_qa.jsonl"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(output, encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    run()
