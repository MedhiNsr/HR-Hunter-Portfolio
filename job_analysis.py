import json
import re
from pathlib import Path

from job_intelligence import clean_job_title, extract_minimum_experience_years, is_senior_title
from source_truth import verify_source_truth


ROOT = Path(__file__).resolve().parent
PROFILE_PATH = ROOT / "profile" / "candidate_cv_content.json"

DIMENSION_WEIGHTS = {
    "skills": 25,
    "domain_experience": 20,
    "seniority": 20,
    "sector": 10,
    "languages": 10,
    "education_certifications": 5,
    "responsibilities": 5,
    "location_constraints": 5,
}

REQUIREMENTS = {
    "DORA": {
        "aliases": ["dora", "digital operational resilience act"],
        "support": "direct",
        "evidence": "DORA maturity assessments for banking and insurance clients",
        "group": "skills",
    },
    "Operational resilience": {
        "aliases": ["operational resilience", "business continuity"],
        "support": "direct",
        "evidence": "operational-resilience gap analysis and remediation roadmaps",
        "group": "skills",
    },
    "Operational risk": {
        "aliases": ["operational risk", "risk matrix", "risk assessment"],
        "support": "direct",
        "evidence": "risk-based assessments, risk matrices and operational-risk mitigation",
        "group": "skills",
    },
    "Internal controls": {
        "aliases": ["internal control", "control framework", "control testing"],
        "support": "direct",
        "evidence": "compliance frameworks, internal controls and control-effectiveness materials",
        "group": "skills",
    },
    "Regulatory monitoring": {
        "aliases": ["regulatory monitoring", "regulatory watch", "regulatory developments"],
        "support": "direct",
        "evidence": "regulatory monitoring across DORA, NIS2 and ISO 27001",
        "group": "skills",
    },
    "Governance": {
        "aliases": ["governance", "risk governance"],
        "support": "direct",
        "evidence": "risk-governance and project-governance support",
        "group": "skills",
    },
    "Change management": {
        "aliases": ["change management", "change enablement", "user adoption"],
        "support": "direct",
        "evidence": "change delivery, user adoption, procedures and post-deployment support",
        "group": "responsibilities",
    },
    "Digital transformation": {
        "aliases": ["digital transformation", "transformation programme", "operating model"],
        "support": "direct",
        "evidence": "digital-transformation delivery and operating-model redesign",
        "group": "responsibilities",
    },
    "Project coordination": {
        "aliases": ["project management", "pmo", "project coordination", "project monitoring"],
        "support": "direct",
        "evidence": "PMO monitoring, project documentation and stakeholder coordination",
        "group": "responsibilities",
    },
    "Training and workshops": {
        "aliases": ["deliver training", "training materials", "facilitate workshops", "workshop facilitation", "user guide", "operational procedure"],
        "support": "direct",
        "evidence": "client workshops, staff training, user guides and operational procedures",
        "group": "responsibilities",
    },
    "AML/KYC": {
        "aliases": ["aml", "kyc", "anti-money laundering", "financial crime"],
        "support": "transferable",
        "evidence": "AML/KYC training in progress, supported by transferable regulatory and control work",
        "group": "skills",
    },
    "Customer due diligence": {
        "aliases": ["customer due diligence", "client due diligence", "enhanced due diligence", "edd", "cdd"],
        "support": "gap",
        "evidence": "no direct case ownership evidenced in the source CV",
        "group": "domain_experience",
    },
    "Transaction monitoring": {
        "aliases": ["transaction monitoring", "suspicious activity", "sar", "str filing"],
        "support": "gap",
        "evidence": "no direct transaction-monitoring production experience evidenced",
        "group": "domain_experience",
    },
    "Sanctions screening": {
        "aliases": ["sanctions screening", "pep screening", "adverse media"],
        "support": "gap",
        "evidence": "no direct sanctions-screening experience evidenced",
        "group": "domain_experience",
    },
    "Stakeholder management": {
        "aliases": ["stakeholder management", "stakeholder coordination", "cross-functional"],
        "support": "direct",
        "evidence": "coordination across client, operational, technical, clinical and institutional stakeholders",
        "group": "responsibilities",
    },
    "Python": {
        "aliases": ["python"], "support": "gap", "evidence": "not evidenced", "group": "skills"
    },
    "SQL": {
        "aliases": ["sql"], "support": "gap", "evidence": "not evidenced", "group": "skills"
    },
}

LANGUAGES = {
    "English": {"aliases": ["english", "anglais"], "supported": True, "level": "fluent (C2)"},
    "French": {"aliases": ["french", "francais", "français"], "supported": True, "level": "native"},
    "Spanish": {"aliases": ["spanish", "espagnol"], "supported": True, "level": "fluent (C2)"},
    "German": {"aliases": ["german", "deutsch"], "supported": False, "level": "not evidenced"},
    "Luxembourgish": {"aliases": ["luxembourgish", "luxembourgeois", "letzebuergesch", "lëtzebuergesch"], "supported": False, "level": "not evidenced"},
}

MUST_CUES = (
    "required", "mandatory", "must", "essential", "minimum", "at least", "you have",
    "proven experience", "fluency", "fluent", "strong command", "shall",
)
NICE_CUES = (
    "preferred", "nice to have", "asset", "advantage", "ideally", "desirable", "plus",
    "would be beneficial", "considered an asset",
)


def load_profile():
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def _normalise(text):
    return re.sub(r"\s+", " ", (text or "").replace("�", "e")).strip()


def _criterion_priority(text, start, end):
    lower = text.lower()
    left = max(lower.rfind(".", 0, start), lower.rfind(";", 0, start), lower.rfind("\n", 0, start))
    right_candidates = [position for position in (lower.find(".", end), lower.find(";", end), lower.find("\n", end)) if position >= 0]
    right = min(right_candidates) if right_candidates else len(lower)
    context = lower[left + 1:right]
    if any(cue in context for cue in NICE_CUES):
        return "NICE TO HAVE"
    if any(cue in context for cue in MUST_CUES):
        return "MUST HAVE"
    return "IMPORTANT"


def _find_requirement(text, label, definition):
    lower = text.lower()
    matches = []
    for alias in definition["aliases"]:
        for match in re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", lower):
            matches.append(match)
    if not matches:
        return None
    priorities = [_criterion_priority(text, match.start(), match.end()) for match in matches]
    priority = "MUST HAVE" if "MUST HAVE" in priorities else "NICE TO HAVE" if set(priorities) == {"NICE TO HAVE"} else "IMPORTANT"
    return {
        "criterion": label,
        "priority": priority,
        "support": definition["support"],
        "evidence": definition["evidence"],
        "group": definition["group"],
    }


def _analyse_languages(text):
    lower = text.lower()
    criteria = []
    for language, definition in LANGUAGES.items():
        occurrences = []
        for alias in definition["aliases"]:
            occurrences.extend(re.finditer(rf"(?<!\w){re.escape(alias)}(?!\w)", lower))
        if not occurrences:
            continue
        priorities = [_criterion_priority(text, match.start(), match.end()) for match in occurrences]
        priority = "MUST HAVE" if "MUST HAVE" in priorities else "NICE TO HAVE" if set(priorities) == {"NICE TO HAVE"} else "IMPORTANT"
        criteria.append({
            "criterion": language,
            "priority": priority,
            "support": "direct" if definition["supported"] else "gap",
            "evidence": definition["level"],
            "group": "languages",
        })
    return criteria


def infer_role_family(title, description):
    title_lower = (title or "").lower()
    text = f"{title} {description}".lower()
    if any(term in title_lower for term in ["change", "transformation", "project", "pmo"]):
        return "change_transformation"
    if any(term in title_lower for term in ["operational risk", "operational resilience", "dora", "ict risk"]):
        return "operational_risk"
    if any(term in title_lower for term in ["aml", "kyc", "financial crime", "due diligence"]):
        return "aml_kyc"
    if any(term in title_lower for term in ["compliance", "regulatory", "risk"]):
        return "compliance_risk"
    if any(term in text for term in ["change management", "digital transformation", "user adoption"]):
        return "change_transformation"
    if any(term in text for term in ["dora", "operational resilience", "operational risk"]):
        return "operational_risk"
    if any(term in text for term in ["aml", "kyc", "financial crime"]):
        return "aml_kyc"
    return "compliance_risk"


def _seniority_analysis(title, description, family):
    years = extract_minimum_experience_years(description)
    senior_title = is_senior_title(title)
    direct_years = {
        "aml_kyc": 0.0,
        "operational_risk": 1.75,
        "compliance_risk": 1.75,
        "change_transformation": 2.75,
    }[family]
    if years is None:
        score = 45 if senior_title else 90
    elif years <= direct_years + 0.5:
        score = 95
    elif years <= 3:
        score = 68 if family != "aml_kyc" else 38
    elif years == 4:
        score = 42 if family != "aml_kyc" else 15
    else:
        score = 20 if family != "aml_kyc" else 5
    if senior_title:
        score = min(score, 40)
    return {
        "score": score,
        "required_years": years,
        "senior_title": senior_title,
        "candidate_direct_years": direct_years,
    }


def _sector(text, company):
    lower = f"{company} {text}".lower()
    if any(term in lower for term in ["bank", "banque", "financial", "fund", "asset management", "insurance", "fintech"]):
        return "financial_services", 82
    if any(term in lower for term in ["public", "government", "central bank", "institution", "europa"]):
        return "public_institutional", 85
    if any(term in lower for term in ["consulting", "consultancy", "advisory", "deloitte", "kpmg", "pwc"] ) or re.search(r"\bey\b", lower):
        return "consulting", 88
    return "other", 65


def _education_criteria(text):
    lower = text.lower()
    criteria = []
    if any(term in lower for term in ["bachelor", "master", "university degree", "higher education"]):
        priority = "MUST HAVE" if any(cue in lower for cue in ["degree required", "must hold", "minimum bachelor"]) else "IMPORTANT"
        criteria.append({
            "criterion": "University degree",
            "priority": priority,
            "support": "direct",
            "evidence": "Master in Political Science and double degree in Law and Political Science",
            "group": "education_certifications",
        })
    if any(term in lower for term in ["acams", "cisa", "crisc", "cfa", "professional certification"]):
        criteria.append({
            "criterion": "Requested professional certification",
            "priority": "NICE TO HAVE" if any(cue in lower for cue in NICE_CUES) else "MUST HAVE",
            "support": "gap",
            "evidence": "not evidenced in the source CV",
            "group": "education_certifications",
        })
    return criteria


def _dimension_score(criteria, group, fallback=70):
    selected = [item for item in criteria if item["group"] == group]
    if not selected:
        return fallback
    priority_weight = {"MUST HAVE": 3, "IMPORTANT": 2, "NICE TO HAVE": 1}
    support_value = {"direct": 100, "transferable": 55, "gap": 0}
    total = sum(priority_weight[item["priority"]] for item in selected)
    return round(sum(priority_weight[item["priority"]] * support_value[item["support"]] for item in selected) / total)


def _extract_named_terms(text, mapping):
    lower = text.lower()
    return [label for label, aliases in mapping.items() if any(alias in lower for alias in aliases)]


def analyse_job(title, company, location, description):
    verify_source_truth()
    clean_title = clean_job_title(title)
    description = _normalise(description)
    full_text = f"{clean_title}. {description}"
    family = infer_role_family(clean_title, description)
    criteria = []
    for label, definition in REQUIREMENTS.items():
        found = _find_requirement(full_text, label, definition)
        if found:
            criteria.append(found)
    criteria.extend(_analyse_languages(full_text))
    criteria.extend(_education_criteria(full_text))

    seniority = _seniority_analysis(clean_title, description, family)
    if seniority["required_years"] is not None:
        criteria.append({
            "criterion": f"{seniority['required_years']} years of relevant experience",
            "priority": "MUST HAVE",
            "support": "direct" if seniority["score"] >= 80 else "gap",
            "evidence": f"approximately {seniority['candidate_direct_years']:g} years of directly relevant experience for this role family",
            "group": "seniority",
        })
    if seniority["senior_title"]:
        criteria.append({
            "criterion": "Senior-level positioning",
            "priority": "MUST HAVE",
            "support": "gap",
            "evidence": "candidate profile is early-career and must not be represented as senior",
            "group": "seniority",
        })

    sector_name, sector_score = _sector(description, company)
    location_lower = (location or "").lower()
    location_score = 100 if "luxembourg" in location_lower or "paris" in location_lower else 20
    language_score = _dimension_score(criteria, "languages", 92)
    education_score = _dimension_score(criteria, "education_certifications", 90)
    dimensions = {
        "skills": _dimension_score(criteria, "skills", 65),
        "domain_experience": _dimension_score(criteria, "domain_experience", {
            "aml_kyc": 35, "operational_risk": 82, "compliance_risk": 78, "change_transformation": 88,
        }[family]),
        "seniority": seniority["score"],
        "sector": sector_score,
        "languages": language_score,
        "education_certifications": education_score,
        "responsibilities": _dimension_score(criteria, "responsibilities", 75),
        "location_constraints": location_score,
    }
    raw_score = round(sum(dimensions[key] * DIMENSION_WEIGHTS[key] for key in DIMENSION_WEIGHTS) / 100)

    must_gaps = [item for item in criteria if item["priority"] == "MUST HAVE" and item["support"] == "gap"]
    score_cap = 96
    if seniority["senior_title"] and (seniority["required_years"] or 0) >= 5:
        score_cap = 42
    elif seniority["senior_title"]:
        score_cap = 58
    elif (seniority["required_years"] or 0) >= 5:
        score_cap = 52
    if must_gaps:
        score_cap = min(score_cap, 62 if len(must_gaps) == 1 else 52)
    score = min(raw_score, score_cap)

    direct = [item for item in criteria if item["support"] == "direct"]
    transferable = [item for item in criteria if item["support"] == "transferable"]
    reasons = [f"{item['criterion']}: {item['evidence']}" for item in direct[:4]]
    if not reasons:
        reasons = ["Transferable risk, compliance and transformation experience"]
    risks = []
    for item in must_gaps:
        if item["criterion"] in {"German", "Luxembourgish"}:
            risks.append(f"Mandatory unsupported language: {item['criterion']}")
        else:
            risks.append(f"{item['criterion']}: {item['evidence']}")
    if seniority["senior_title"]:
        risks.append("Role explicitly positioned at senior level; candidate profile is early-career")
    if transferable:
        risks.extend(f"Transferable rather than direct: {item['criterion']}" for item in transferable[:2])

    supported_keywords = [item["criterion"] for item in criteria if item["support"] == "direct"]
    transferable_keywords = [item["criterion"] for item in criteria if item["support"] == "transferable"]
    regulations = _extract_named_terms(full_text, {
        "DORA": ["dora", "digital operational resilience act"],
        "NIS2": ["nis2"],
        "ISO 27001": ["iso 27001"],
        "AML/CFT": ["aml/cft", "anti-money laundering", "counter-terrorist financing"],
        "MiFID II": ["mifid ii", "mifid 2"],
        "GDPR": ["gdpr", "general data protection regulation"],
    })
    tools = _extract_named_terms(full_text, {
        "Python": ["python"], "SQL": ["sql"], "Microsoft Excel": ["excel"],
        "Power BI": ["power bi"], "ServiceNow": ["servicenow"], "SAP": ["sap"],
    })
    soft_skills = _extract_named_terms(full_text, {
        "Analytical skills": ["analytical", "analysis skills"],
        "Communication": ["communication", "communicate"],
        "Attention to detail": ["attention to detail", "detail-oriented"],
        "Teamwork": ["team player", "teamwork", "collaborative"],
        "Organisation": ["organised", "organized", "organisation skills", "organizational skills"],
        "Stakeholder management": ["stakeholder management", "stakeholder coordination"],
    })
    criteria_by_priority = {
        level: [item for item in criteria if item["priority"] == level]
        for level in ("MUST HAVE", "IMPORTANT", "NICE TO HAVE")
    }
    return {
        "raw_job_title": title,
        "job_title": clean_title,
        "company": company,
        "location": location,
        "role_family": family,
        "sector": sector_name,
        "seniority": seniority,
        "criteria": criteria_by_priority,
        "requirements_summary": {
            "must_have": [item["criterion"] for item in criteria_by_priority["MUST HAVE"]],
            "important": [item["criterion"] for item in criteria_by_priority["IMPORTANT"]],
            "nice_to_have": [item["criterion"] for item in criteria_by_priority["NICE TO HAVE"]],
            "responsibilities": [item["criterion"] for item in criteria if item["group"] in {"responsibilities", "domain_experience"}],
            "regulations": regulations,
            "tools": tools,
            "languages": [item["criterion"] for item in criteria if item["group"] == "languages"],
            "education_certifications": [item["criterion"] for item in criteria if item["group"] == "education_certifications"],
            "soft_skills": soft_skills,
            "ats_keywords": list(dict.fromkeys([item["criterion"] for item in criteria] + regulations + tools + soft_skills)),
        },
        "dimensions": dimensions,
        "dimension_weights": DIMENSION_WEIGHTS,
        "raw_score": raw_score,
        "score_cap": score_cap,
        "score": score,
        "reasons": reasons,
        "risks": risks,
        "must_have_gaps": must_gaps,
        "supported_keywords": supported_keywords,
        "transferable_keywords": transferable_keywords,
        "eligible_for_proposal": score >= 60 and not (seniority["senior_title"] and (seniority["required_years"] or 0) >= 5),
    }


def compact_analysis(analysis):
    return json.dumps(analysis, ensure_ascii=False, sort_keys=True)
