import argparse
import json

from agent_hr import JobInput
from workflow import propose_job


def import_jobs(path):
    data = json.loads(open(path, encoding="utf-8").read())
    results = []
    for item in data:
        job = JobInput(
            source=item["source"],
            source_url=item["source_url"],
            title=item["title"],
            company=item["company"],
            location=item["location"],
            description=item["description"],
            contact_email=item.get("contact_email", ""),
            application_channel=item.get("application_channel", "unknown"),
        )
        results.append({"title": job.title, "company": job.company, **propose_job(job)})
    return results


def main():
    parser = argparse.ArgumentParser(description="Import curated jobs into Agent HR.")
    parser.add_argument("path")
    args = parser.parse_args()
    print(json.dumps(import_jobs(args.path), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
