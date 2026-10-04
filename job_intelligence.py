import re


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def clean_job_title(title):
    value = normalize(title)
    value = re.sub(r"\s+Job Details(?:\s*\|.*)?$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*[-|]\s*career\s+[A-Z]?\d+\s*$", "", value, flags=re.IGNORECASE)
    value = re.sub(
        r"\s*\((?:m|f|d|h|x|t)(?:\s*[/|]\s*(?:m|f|d|h|x|t)){1,4}\)\s*",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\s+", " ", value).strip(" -|")
    letters = [char for char in value if char.isalpha()]
    if letters and sum(char.isupper() for char in letters) / len(letters) > 0.65:
        value = value.title()
    acronyms = ["AML", "KYC", "ORM", "DORA", "ICT", "PMO", "ESG", "CFT"]
    for acronym in acronyms:
        value = re.sub(rf"\b{acronym.title()}\b", acronym, value)
    return value


KEYWORD_GROUPS = {
    "AML/KYC": ["aml", "kyc", "anti-money laundering", "financial crime", "due diligence", "client onboarding"],
    "Compliance": ["compliance", "regulatory", "regulation", "controls", "governance", "audit"],
    "Risk": ["risk", "operational risk", "risk assessment", "internal control"],
    "Operational resilience": ["operational resilience", "dora", "business continuity", "ict risk", "nis2"],
    "Languages": ["english", "french", "spanish", "anglais", "francais", "français", "espagnol"],
    "Transformation": ["change management", "digital transformation", "project management", "pmo", "process improvement"],
}

SPECIFIC_JOB_TERMS = [
    ("AML/CFT", ["aml/cft", "aml-ctf", "anti-money laundering", "counter-terrorist financing"]),
    ("KYC", ["kyc", "know your customer"]),
    ("Enhanced Due Diligence", ["enhanced due diligence", "edd"]),
    ("Financial Crime", ["financial crime"]),
    ("Client Onboarding", ["client onboarding", "customer onboarding"]),
    ("Transaction Monitoring", ["transaction monitoring"]),
    ("Suspicious Activity Investigations", ["suspicious activity", "investigations", "str", "sar"]),
    ("Regulatory Monitoring", ["regulatory monitoring", "regulatory watch"]),
    ("Internal Controls", ["internal controls", "control framework"]),
    ("Operational Risk", ["operational risk"]),
    ("Operational Resilience", ["operational resilience", "business continuity"]),
    ("DORA", ["dora"]),
    ("Risk Assessment", ["risk assessment"]),
    ("Governance", ["governance"]),
    ("Stakeholder Management", ["stakeholder management", "stakeholder coordination"]),
    ("Process Improvement", ["process improvement"]),
    ("Change Management", ["change management"]),
]


def is_senior_title(title):
    return bool(re.search(r"\b(senior|sr\.?|lead|principal)\b", (title or "").lower()))


def extract_minimum_experience_years(text):
    haystack = (text or "").lower()
    year_token = r"year(?:s|\(s\))?"
    patterns = [
        rf"(?:minimum|at least|min\.?|minimum of)\s+(\d{{1,2}})\s*\+?\s*{year_token}",
        rf"(\d{{1,2}})\s*\+?\s*{year_token}\s+(?:of\s+)?(?:relevant|professional|work|similar)",
        rf"(?:experience|experienced)\s*(?:of|:)??\s*(\d{{1,2}})\s*\+?\s*{year_token}",
    ]
    values = []
    for pattern in patterns:
        values.extend(int(value) for value in re.findall(pattern, haystack))
    return max(values) if values else None


def language_requirement(text, language):
    haystack = (text or "").lower()
    variants = {
        "german": ["german", "deutsch"],
        "luxembourgish": ["luxembourgish", "luxembourgeois", "lëtzebuergesch"],
    }.get(language, [language])
    desired_cues = [
        "ideally", "preferred", "desirable", "nice to have", "asset", "advantage",
        "additional language", "would be a plus", "is a plus", "considered a plus",
    ]
    mandatory_cues = [
        "required", "mandatory", "must have", "must be", "fluent in",
        "fluency in", "proficient in", "proficiency in", "command of",
    ]
    result = None
    for variant in variants:
        for match in re.finditer(re.escape(variant), haystack):
            before = haystack[max(0, match.start() - 220):match.start()]
            around = haystack[max(0, match.start() - 140):match.end() + 140]
            if any(cue in before[-180:] or cue in around for cue in desired_cues):
                result = result or "desirable"
                continue
            french_alternative = bool(
                re.search(r"french\s+(?:and/or|or)\s+german|german\s+(?:and/or|or)\s+french", around)
            )
            if language == "german" and french_alternative:
                result = result or "desirable"
                continue
            if any(cue in around for cue in mandatory_cues):
                return "mandatory"
    return result


def normalize(text):
    return re.sub(r"\s+", " ", text or "").strip()


def extract_first_email(text):
    for email in EMAIL_RE.findall(text or ""):
        lower = email.lower()
        if lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            continue
        if "example." in lower:
            continue
        return email
    return ""


def infer_channel(url, contact_email):
    if contact_email:
        return "email"
    lower = (url or "").lower()
    if "linkedin.com/jobs" in lower:
        return "linkedin_manual"
    if any(domain in lower for domain in ["indeed.", "moovijob.com", "welcometothejungle.com", "jobs.lu", "adem."]):
        return "portal_manual"
    return "unknown"


def extract_keywords(text):
    haystack = (text or "").lower()
    matches = []
    for group, terms in KEYWORD_GROUPS.items():
        if any(term in haystack for term in terms):
            matches.append(group)
    return matches


def extract_specific_keywords(text, limit=5):
    haystack = (text or "").lower()
    found = []
    for label, terms in SPECIFIC_JOB_TERMS:
        if any(term in haystack for term in terms):
            found.append(label)
    return found[:limit]


def build_alignment_sentences(keywords, groups):
    sentences = []
    if any(keyword in keywords for keyword in ["AML/CFT", "KYC", "Enhanced Due Diligence", "Financial Crime", "Client Onboarding", "Transaction Monitoring", "Suspicious Activity Investigations"]):
        sentences.append(
            "Her regulatory monitoring and internal-control work provides a structured foundation for documenting requirements, assessing controls and coordinating remediation, reinforced by AML/KYC training in progress."
        )
    if any(keyword in keywords for keyword in ["DORA", "Operational Resilience", "Operational Risk", "Risk Assessment"]):
        sentences.append(
            "She has contributed to DORA maturity assessments and risk-governance work for banking and insurance environments, translating regulatory expectations into practical actions."
        )
    if any(keyword in keywords for keyword in ["Regulatory Monitoring", "Internal Controls", "Governance"]):
        sentences.append(
            "Her consulting experience includes regulatory monitoring, internal-control review and concise synthesis for stakeholders in regulated environments."
        )
    if any(keyword in keywords for keyword in ["Stakeholder Management", "Process Improvement", "Change Management"]):
        sentences.append(
            "Her delivery background combines stakeholder coordination, process documentation and change support across complex multi-party projects."
        )
    if not sentences and "Compliance" in groups:
        sentences.append(
            "Her compliance consulting background combines regulatory analysis, internal controls and stakeholder coordination in regulated environments."
        )
    if not sentences:
        sentences.append(
            "Her risk, resilience and transformation experience brings structured analysis, clear documentation and strong stakeholder coordination."
        )
    if len(sentences) == 1:
        sentences.append(
            "Her multilingual profile and immediate availability support work in international teams across Luxembourg and Paris."
        )
    return sentences[:2]


def risk_notes(text):
    haystack = (text or "").lower()
    risks = []
    mandatory_languages = [
        language.title()
        for language in ("german", "luxembourgish")
        if language_requirement(text, language) == "mandatory"
    ]
    if mandatory_languages:
        risks.append(f"Mandatory unsupported language: {'/'.join(mandatory_languages)}")
    years = extract_minimum_experience_years(text)
    if years:
        risks.append(f"Minimum {years} years of relevant experience requested")
    if is_senior_title(text):
        risks.append("Role explicitly positioned at senior level")
    if "python" in haystack or "sql" in haystack:
        risks.append("Technical skill requirement to verify")
    return risks


def build_job_fit(title, company, location, description):
    text = " ".join([title or "", company or "", location or "", description or ""])
    keywords = extract_keywords(text)
    specific_keywords = extract_specific_keywords(text)
    risks = risk_notes(text)
    strengths = []
    if "Operational resilience" in keywords:
        strengths.append("DORA and operational resilience consulting experience")
    if "Compliance" in keywords:
        strengths.append("regulatory compliance and internal controls exposure")
    if "AML/KYC" in keywords:
        strengths.append("AML/KYC training in progress plus transferable compliance work")
    if "Risk" in keywords:
        strengths.append("risk assessment and governance work")
    if "Transformation" in keywords:
        strengths.append("change management and digital transformation delivery")
    if not strengths:
        strengths.append("risk, resilience and compliance consulting background")
    return {
        "keywords": keywords,
        "specific_keywords": specific_keywords,
        "strengths": strengths,
        "risks": risks,
        "alignment_sentences": build_alignment_sentences(specific_keywords, keywords),
    }
