import argparse
import html
import json
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote_plus, urljoin
from urllib.request import Request, urlopen

from agent_hr import JobInput, ROOT
from job_intelligence import extract_first_email, infer_channel
from workflow import propose_job


CONFIG = ROOT / "config" / "job_sources.json"
TARGET_COMPANIES = ROOT / "config" / "target_companies.json"


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current_href = None
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attrs = dict(attrs)
        href = attrs.get("href")
        if href:
            self.current_href = href
            self.current_text = []

    def handle_data(self, data):
        if self.current_href:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current_href:
            text = " ".join(self.current_text).strip()
            if text:
                self.links.append((self.current_href, html.unescape(text)))
            self.current_href = None
            self.current_text = []


def load_config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def load_target_companies():
    if not TARGET_COMPANIES.exists():
        return []
    return json.loads(TARGET_COMPANIES.read_text(encoding="utf-8"))


def fetch_html_details(url, timeout=25):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 AgentHR/0.1",
            "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore"), response.geturl()


def fetch_html(url, timeout=25):
    page, _ = fetch_html_details(url, timeout=timeout)
    return page


def relevant(text, terms):
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def clean_title(text):
    text = re.sub(r"\s+", " ", text).strip()
    return text[:160]


def discover_from_search_page(source, url, term):
    page = fetch_html(url)
    contact_email = extract_first_email(page)
    parser = LinkParser()
    parser.feed(page)
    jobs = []
    seen = set()
    terms = [term, "compliance", "aml", "kyc", "risk", "dora", "regulatory"]
    for href, text in parser.links:
        title = clean_title(text)
        if len(title) < 8 or not relevant(title, terms):
            continue
        absolute_url = urljoin(url, href)
        if absolute_url in seen:
            continue
        seen.add(absolute_url)
        location = "Luxembourg" if "luxembourg" in url.lower() else "Paris"
        jobs.append(
            JobInput(
                source=source["name"],
                source_url=absolute_url,
                title=title,
                company="A verifier",
                location=location,
                description=f"{title}. Source: {source['name']}. Search term: {term}.",
                contact_email=contact_email,
                application_channel=infer_channel(absolute_url, contact_email),
            )
        )
    return jobs


def strip_markup(value):
    return clean_title(re.sub(r"<[^>]+>", " ", html.unescape(value or "")))


def page_text(value, limit=18000):
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", value or "", flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()[:limit]


def company_from_job_page(url, title, page):
    organization = re.search(
        r'"hiringOrganization"\s*:\s*\{.*?"name"\s*:\s*"([^"]+)"',
        page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if organization:
        return html.unescape(organization.group(1)).strip()[:120]

    title_match = re.search(r"<title[^>]*>(.*?)</title>", page, flags=re.IGNORECASE | re.DOTALL)
    if title_match:
        page_title = strip_markup(title_match.group(1))
        prefix = title.strip() + " - "
        if page_title.lower().startswith(prefix.lower()):
            remainder = page_title[len(prefix):]
            for suffix in [" - jobs.lu", " | LinkedIn", " - Careers", " | Careers"]:
                remainder = remainder.split(suffix, 1)[0]
            if remainder.strip():
                return remainder.strip()[:120]
    return "A verifier"


def infer_company(url, title, target_companies):
    lower_url = url.lower()
    for company in target_companies:
        domain = company.get("domain", "").lower().removeprefix("www.")
        if domain and domain in lower_url:
            return company["name"]

    hiring_match = re.search(r"^(.+?)\s+hiring\s+.+?\s+in\s+", title, flags=re.IGNORECASE)
    if hiring_match:
        return hiring_match.group(1).strip()

    normalized_title = title.replace("�", " - ")
    chez_match = re.search(
        r"\bchez\s+(.+?)(?=\s+[^A-Za-z0-9]*\s*(?:luxembourg|paris)\b|\s+\.\.\.|$)",
        normalized_title,
        flags=re.IGNORECASE,
    )
    if chez_match:
        return chez_match.group(1).strip()[:120]

    parts = [part.strip() for part in re.split(r"\s+[|\-–]\s+", title) if part.strip()]
    if len(parts) >= 2:
        candidate = parts[-1]
        if not relevant(candidate, ["Luxembourg", "Paris", "France", "job", "career"]):
            return candidate[:120]
    return "A verifier"


def web_search_results(page, url):
    if "format=rss" in url.lower():
        root = ET.fromstring(page)
        return [
            (
                item.findtext("link", default="").strip(),
                strip_markup(item.findtext("title", default="")),
                strip_markup(item.findtext("description", default="")),
            )
            for item in root.findall(".//item")
        ]

    parser = LinkParser()
    parser.feed(page)
    return [(urljoin(url, href), clean_title(text), "") for href, text in parser.links]


def is_search_or_listing_result(url, title):
    text = f"{title} {url}".lower()
    title_signals = [
        "jobs and vacancies",
        "jobs in luxembourg",
        "jobs in luxemburg",
        "jobs in paris",
        "offres d'emploi",
        "emplois aml",
        "emplois kyc",
        "emplois compliance",
        "postes de ",
        "offres de ",
        "job search",
    ]
    if any(signal in text for signal in title_signals):
        return True
    return bool(
        re.search(r"\b\d[\d\s,.]*\+?\s+(jobs|vacancies|offres|emplois|postes)\b", text)
        or re.search(r"linkedin\.com/jobs/[^/?]+-emplois(?:[/?]|$)", text)
    )


def discover_from_web_search(source, url, query, target_companies, limit=None):
    page = fetch_html(url)
    contact_email = extract_first_email(page)
    jobs = []
    seen = set()
    allowed_domains = [
        "jobs.lu",
        "moovijob.com",
        "welcometothejungle.com",
        "linkedin.com/jobs",
        "indeed.com",
        "indeed.lu",
        "efinancialcareers",
        "mon-vie-via.businessfrance.fr",
        "careers",
        "jobs",
    ]
    allowed_domains.extend(
        company.get("domain", "").lower().removeprefix("www.")
        for company in target_companies
        if company.get("domain")
    )
    job_terms = ["compliance", "aml", "kyc", "risk", "dora", "regulatory", "financial crime", "onboarding"]
    for absolute_url, title, snippet in web_search_results(page, url):
        lower_url = absolute_url.lower()
        if absolute_url in seen:
            continue
        if is_search_or_listing_result(absolute_url, title):
            continue
        if not any(domain in lower_url for domain in allowed_domains):
            continue
        if not relevant(title + " " + absolute_url, job_terms):
            continue
        if "bing.com" in lower_url and "ck/a" not in lower_url:
            continue
        seen.add(absolute_url)
        location = "Paris"
        combined = query + " " + absolute_url + " " + title + " " + snippet
        if "luxembourg" in combined.lower():
            location = "Luxembourg"
        company = infer_company(absolute_url, title, target_companies)
        description = f"{title}. {snippet}. Source: web search. Query: {query}."
        page_verified = False
        try:
            page, final_url = fetch_html_details(absolute_url, timeout=8)
            if "/offres-emploi/" in absolute_url.lower() and "/entreprise/" in final_url.lower():
                continue
            if company == "A verifier":
                company = company_from_job_page(absolute_url, title, page)
            description = page_text(page)
            page_verified = True
        except Exception:
            pass
        jobs.append(
            JobInput(
                source=source["name"],
                source_url=absolute_url,
                title=title,
                company=company,
                location=location,
                description=description,
                contact_email=contact_email,
                application_channel=infer_channel(absolute_url, contact_email),
                page_verified=page_verified,
            )
        )
        if limit and len(jobs) >= limit:
            break
    return jobs


def run_search(limit_per_term=5, dry_run=False):
    config = load_config()
    target_companies = load_target_companies()
    total = {"found": 0, "proposed": 0, "deferred_by_limit": 0, "errors": []}
    max_queries_per_source = config.get("max_queries_per_source", 10)
    max_per_cycle = config.get("max_proposals_per_cycle", 3)
    max_per_day = config.get("max_new_proposals_per_day", 12)
    with sqlite3.connect(ROOT / "agent_hr.sqlite3") as conn:
        proposed_today = conn.execute(
            """
            SELECT COUNT(*) FROM applications
            WHERE status IN ('proposed', 'review_required', 'validated', 'contact_review', 'contact_confirmed', 'sent')
              AND DATE(created_at)=DATE('now')
            """
        ).fetchone()[0]
    for source in config["sources"]:
        if not source.get("enabled", False):
            continue
        source_query_count = 0
        for template in source["url_templates"]:
            terms = config["search_terms"] if "{query}" in template else [""]
            expanded_queries = []
            if source["type"] == "web_search":
                query_budget = min(max_queries_per_source, source.get("queries_per_cycle", max_queries_per_source))
                company_limit = min(source.get("company_queries_per_cycle", 4), query_budget)
                term_budget = max(1, query_budget - company_limit)
                term_queries = [
                    query_template.replace("{term}", term)
                    for query_template in source.get("query_templates", ["{term}"])
                    for term in config["search_terms"]
                ]
                rotation_minutes = source.get("rotation_interval_minutes", 30)
                slot = int(time.time() // (rotation_minutes * 60))
                term_rotation = (slot * term_budget) % len(term_queries)
                ordered_terms = term_queries[term_rotation:] + term_queries[:term_rotation]
                expanded_queries.extend(ordered_terms[:term_budget])
                if target_companies:
                    rotation = (slot * company_limit) % len(target_companies)
                    ordered = target_companies[rotation:] + target_companies[:rotation]
                    for company in ordered[:company_limit]:
                        expanded_queries.append(
                            f"site:{company['domain']} (compliance OR AML OR KYC OR risk OR resilience) "
                            f"(Luxembourg OR Paris) (job OR careers)"
                        )
            elif source["type"] == "search_page":
                query_budget = min(max_queries_per_source, source.get("queries_per_cycle", max_queries_per_source))
                rotation_minutes = source.get("rotation_interval_minutes", 30)
                slot = int(time.time() // (rotation_minutes * 60))
                rotation = (slot * query_budget) % len(terms)
                ordered_terms = terms[rotation:] + terms[:rotation]
                expanded_queries = ordered_terms[:query_budget]
            else:
                expanded_queries = terms

            for term in expanded_queries:
                if source_query_count >= max_queries_per_source:
                    break
                url = template.replace("{query}", quote_plus(term))
                source_query_count += 1
                try:
                    if source["type"] == "web_search":
                        jobs = discover_from_web_search(
                            source, url, term, target_companies, limit=limit_per_term
                        )
                    elif source["type"] == "search_page":
                        jobs = discover_from_search_page(source, url, term)[:limit_per_term]
                    else:
                        continue
                    total["found"] += len(jobs)
                    for job in jobs:
                        if dry_run:
                            print(f"[DRY RUN] {job.company} | {job.title} | {job.source_url}")
                            continue
                        if total["proposed"] >= max_per_cycle or proposed_today + total["proposed"] >= max_per_day:
                            total["deferred_by_limit"] += 1
                            continue
                        result = propose_job(job)
                        if result.get("proposed"):
                            total["proposed"] += 1
                except Exception as exc:
                    total["errors"].append({"source": source["name"], "url": url, "error": str(exc)})
    return total


def main():
    parser = argparse.ArgumentParser(description="Search job sources and propose relevant offers.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit-per-term", type=int, default=5)
    args = parser.parse_args()
    print(json.dumps(run_search(limit_per_term=args.limit_per_term, dry_run=args.dry_run), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
