import json
import sqlite3

from agent_hr import JobInput, ROOT
from job_search import is_search_or_listing_result
from job_analysis import analyse_job


DB = ROOT / "agent_hr.sqlite3"


def recalculate_pending_scores():
    rules = json.loads((ROOT / "config" / "scoring_rules.json").read_text(encoding="utf-8"))
    changes = []
    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute(
            """
            SELECT applications.id, applications.status, jobs.id, jobs.source, jobs.source_url,
                   jobs.title, jobs.company, jobs.location, jobs.description
            FROM applications JOIN jobs ON jobs.id=applications.job_id
            WHERE applications.status IN ('proposed', 'review_required')
            ORDER BY applications.id
            """
        ).fetchall()
        for app_id, old_status, job_id, source, url, title, company, location, description in rows:
            job = JobInput(source, url, title, company, location, description)
            analysis = analyse_job(title, company, location, description)
            score, risks = analysis["score"], analysis["risks"]
            if is_search_or_listing_result(url, title):
                score = 0
                new_status = "rejected_by_quality"
            elif score < rules.get("minimum_score_to_review", 35):
                new_status = "rejected_by_score"
            elif score < rules["minimum_score_to_propose"] or not analysis["eligible_for_proposal"]:
                new_status = "review_required"
            else:
                new_status = "proposed"
            conn.execute(
                "UPDATE jobs SET score=?, status=?, analysis_json=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    score, "needs_review" if new_status == "review_required" else new_status,
                    json.dumps(analysis, ensure_ascii=False, sort_keys=True), job_id,
                ),
            )
            conn.execute(
                "UPDATE applications SET score=?, status=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (score, new_status, "; ".join(risks), app_id),
            )
            changes.append(
                {"application_id": app_id, "old_status": old_status, "new_status": new_status, "score": score}
            )
        conn.commit()
    finally:
        conn.close()
    return changes


if __name__ == "__main__":
    print(json.dumps(recalculate_pending_scores(), indent=2, ensure_ascii=False))
