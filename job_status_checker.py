from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


CLOSED_SIGNALS = [
    "les candidatures ne sont plus acceptees",
    "les candidatures ne sont plus acceptées",
    "no longer accepting applications",
    "job is no longer available",
    "this job is no longer available",
    "this position is no longer available",
    "expired job",
    "poste expiré",
    "offre expirée",
    "candidatures fermees",
    "candidatures fermées",
]

OPEN_SIGNALS = [
    "apply",
    "postuler",
    "submit application",
    "apply now",
    "candidature",
]


def fetch_public_page(url):
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 AgentHR/0.1",
            "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
        },
    )
    with urlopen(request, timeout=8) as response:
        return response.read().decode("utf-8", errors="ignore")


def check_job_is_open(url, description="", page_verified=False):
    text = (description or "").lower()
    for signal in CLOSED_SIGNALS:
        if signal in text:
            return {"status": "closed", "reason": signal}

    if page_verified:
        if any(signal in text for signal in OPEN_SIGNALS):
            return {"status": "open", "reason": "open_signal_found_on_verified_page"}
        return {"status": "unknown", "reason": "verified_page_has_no_clear_signal"}

    try:
        text += " " + fetch_public_page(url).lower()
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return {
            "status": "unknown",
            "reason": f"could_not_verify: {exc}",
        }

    for signal in CLOSED_SIGNALS:
        if signal in text:
            return {"status": "closed", "reason": signal}

    if any(signal in text for signal in OPEN_SIGNALS):
        return {"status": "open", "reason": "open_signal_found"}

    return {"status": "unknown", "reason": "no_clear_signal"}
