"""
Internal master-data bootstrap used only by ``seed_showcase``.

The repository has one supported seed entrypoint:
``crm.demo.seed_showcase.execute``. This module must not be run directly.

What this creates (all idempotent):
  Master data
    CRM Intent Type         — 8 types
    CRM Score Signal        — 22 signals (Fit / Engagement / Intent / Negative)
    CRM Score Template      — "Default Scoring 2026" (active)

  Shared context
    Province, Ward, Campus, High School, Major, Aspiration,
    Lead Source, Campaign, Event, Education Program, Admission Year
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

import frappe


def _as_code(value: str) -> str:
    """Normalise a display label into an UPPER_SNAKE lookup code."""
    folded = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", "_", folded.upper()).strip("_")


# ---------------------------------------------------------------------------
# Shared context constants
# ---------------------------------------------------------------------------

PROVINCE_CODE = "79"
PROVINCE_NAME = "Ho Chi Minh City"
WARD_CODE = "760"
WARD_NAME = "Ben Nghe Ward"
CAMPUS = "FPTU Ho Chi Minh Campus"
HIGH_SCHOOL = "Tran Dai Nghia High School for the Gifted"
MAJOR = "Software Engineering"
MAJOR_CODE = "SE"
CAMPAIGN = "FPTU 2026 Admission Campaign - HCMC"
EVENT = "FPTU HCMC Campus Visit - June 2026"
TEMPLATE_NAME = "Default Scoring 2026"


# ---------------------------------------------------------------------------
# Master data definitions
# ---------------------------------------------------------------------------

INTENT_TYPES = [
    {"name": "MAJOR_INQUIRY",     "importance": "Medium",    "description_vi": "Hỏi về ngành học"},
    {"name": "ENVIRONMENT",       "importance": "Medium",    "description_vi": "Hỏi về môi trường học tập / ký túc xá"},
    {"name": "TUITION",           "importance": "High",      "description_vi": "Hỏi về học phí"},
    {"name": "SCHOLARSHIP",       "importance": "High",      "description_vi": "Hỏi về học bổng"},
    {"name": "DORMITORY",         "importance": "Medium",    "description_vi": "Hỏi về ký túc xá"},
    {"name": "ADMISSION_PROCESS", "importance": "High",      "description_vi": "Hỏi về quy trình xét tuyển"},
    {"name": "ENROLLMENT_INTENT", "importance": "Very High", "description_vi": "Có ý định đăng ký nhập học"},
    {"name": "DEPOSIT_INTENT",    "importance": "Very High", "description_vi": "Sẵn sàng đặt cọc / xác nhận nhập học"},
]

SIGNALS = [
    # Fit — property-based
    {
        "signal_key": "grade_12",       "label": "Grade 12 Student",
        "category": "Fit",              "signal_type": "property",
        "condition_field": "grade_level", "condition_operator": "=", "condition_value": "12",
        "description": "Student is currently in grade 12",
    },
    {
        "signal_key": "gpa_high",       "label": "High GPA (>= 8.0)",
        "category": "Fit",              "signal_type": "property",
        "condition_field": "transcript_score", "condition_operator": ">=", "condition_value": "8.0",
        "description": "Academic performance qualifies for merit scholarship",
    },
    {
        "signal_key": "ielts_6",        "label": "IELTS >= 6.0",
        "category": "Fit",              "signal_type": "property",
        "condition_field": "english_converted_score", "condition_operator": ">=", "condition_value": "6.0",
        "description": "English certificate meets international program entry requirement",
    },
    {
        "signal_key": "top_school",     "label": "Top High School",
        "category": "Fit",              "signal_type": "property",
        "condition_field": "high_school_tier", "condition_operator": "=", "condition_value": "Top",
        "description": "Attended a ranked or specialized high school",
    },
    # Engagement — interaction-based
    {
        "signal_key": "website_visit",  "label": "Website Visit",
        "category": "Engagement",       "signal_type": "interaction",
        "interaction_term": "Website Visit",
    },
    {
        "signal_key": "major_view",     "label": "Major Page View",
        "category": "Engagement",       "signal_type": "interaction",
        "interaction_term": "Major View",
    },
    {
        "signal_key": "zalo_chat",      "label": "Zalo Chat",
        "category": "Engagement",       "signal_type": "interaction",
        "interaction_term": "Zalo Chat",
    },
    {
        "signal_key": "consultation_register", "label": "Consultation Register",
        "category": "Engagement",              "signal_type": "interaction",
        "interaction_term": "Consultation Register",
    },
    {
        "signal_key": "webinar",        "label": "Webinar Attendance",
        "category": "Engagement",       "signal_type": "interaction",
        "interaction_term": "Webinar",
    },
    {
        "signal_key": "open_day",       "label": "Open Day Visit",
        "category": "Engagement",       "signal_type": "interaction",
        "interaction_term": "Open Day",
    },
    {
        "signal_key": "application_submit", "label": "Application Submitted",
        "category": "Engagement",           "signal_type": "interaction",
        "interaction_term": "Application Submit",
    },
    # Intent — intent-type-based
    {
        "signal_key": "intent_major",       "label": "Intent: Major Inquiry",
        "category": "Intent",               "signal_type": "intent",
        "intent_type": "MAJOR_INQUIRY",
    },
    {
        "signal_key": "intent_tuition",     "label": "Intent: Tuition Question",
        "category": "Intent",               "signal_type": "intent",
        "intent_type": "TUITION",
    },
    {
        "signal_key": "intent_scholarship", "label": "Intent: Scholarship Question",
        "category": "Intent",               "signal_type": "intent",
        "intent_type": "SCHOLARSHIP",
    },
    {
        "signal_key": "intent_admission",   "label": "Intent: Admission Process",
        "category": "Intent",               "signal_type": "intent",
        "intent_type": "ADMISSION_PROCESS",
    },
    {
        "signal_key": "intent_enroll",      "label": "Intent: Enrollment",
        "category": "Intent",               "signal_type": "intent",
        "intent_type": "ENROLLMENT_INTENT",
    },
    {
        "signal_key": "intent_deposit",     "label": "Intent: Deposit",
        "category": "Intent",               "signal_type": "intent",
        "intent_type": "DEPOSIT_INTENT",
    },
    # Negative — inactivity
    {
        "signal_key": "no_contact_30",  "label": "No Contact 30 Days",
        "category": "Negative",         "signal_type": "inactivity",
        "inactivity_days": 30,
    },
    {
        "signal_key": "no_contact_60",  "label": "No Contact 60 Days",
        "category": "Negative",         "signal_type": "inactivity",
        "inactivity_days": 60,
    },
    {
        "signal_key": "no_contact_90",  "label": "No Contact 90 Days",
        "category": "Negative",         "signal_type": "inactivity",
        "inactivity_days": 90,
    },
    # Negative — behavioral
    {
        "signal_key": "refuse_consultation", "label": "Refused Consultation",
        "category": "Negative",              "signal_type": "interaction",
        "interaction_term": "Refuse Consultation",
    },
    {
        "signal_key": "cancel_event",   "label": "Cancelled Event",
        "category": "Negative",         "signal_type": "interaction",
        "interaction_term": "Cancel Event",
    },
    {
        "signal_key": "transfer_school", "label": "Transferred to Another School",
        "category": "Negative",          "signal_type": "interaction",
        "interaction_term": "Transfer School",
    },
]

SCORE_RULES = [
    # Fit
    {"signal": "grade_12",             "base_points": 20,  "max_points": 20},
    {"signal": "gpa_high",             "base_points": 20,  "max_points": 20},
    {"signal": "ielts_6",              "base_points": 15,  "max_points": 15},
    {"signal": "top_school",           "base_points": 15,  "max_points": 15},
    # Engagement
    {"signal": "website_visit",        "base_points": 2,   "max_points": 10},
    {"signal": "major_view",           "base_points": 5,   "max_points": 25},
    {"signal": "zalo_chat",            "base_points": 10,  "max_points": 30},
    {"signal": "consultation_register","base_points": 20,  "max_points": 40},
    {"signal": "webinar",              "base_points": 25,  "max_points": 50},
    {"signal": "open_day",             "base_points": 30,  "max_points": 60},
    {"signal": "application_submit",   "base_points": 50,  "max_points": 50},
    # Intent
    {"signal": "intent_major",         "base_points": 10,  "max_points": 10},
    {"signal": "intent_tuition",       "base_points": 25,  "max_points": 25},
    {"signal": "intent_scholarship",   "base_points": 25,  "max_points": 25},
    {"signal": "intent_admission",     "base_points": 50,  "max_points": 50},
    {"signal": "intent_enroll",        "base_points": 70,  "max_points": 70},
    {"signal": "intent_deposit",       "base_points": 90,  "max_points": 90},
]

NEGATIVE_RULES = [
    {"signal": "no_contact_30",       "penalty_amount": 10, "cooldown_days": 30, "max_penalties": 1},
    {"signal": "no_contact_60",       "penalty_amount": 20, "cooldown_days": 30, "max_penalties": 1},
    {"signal": "no_contact_90",       "penalty_amount": 40, "cooldown_days": 30, "max_penalties": 1},
    {"signal": "refuse_consultation", "penalty_amount": 30, "cooldown_days": 0,  "max_penalties": 3},
    {"signal": "cancel_event",        "penalty_amount": 20, "cooldown_days": 0,  "max_penalties": 5},
    {"signal": "transfer_school",     "penalty_amount": 50, "cooldown_days": 0,  "max_penalties": 1},
]

TIME_DECAY_TIERS = [
    {"max_days": 30,  "multiplier": 1.0, "tier_label": "Hot"},
    {"max_days": 60,  "multiplier": 0.7, "tier_label": "Warm"},
    {"max_days": 90,  "multiplier": 0.4, "tier_label": "Cool"},
    {"max_days": 0,   "multiplier": 0.1, "tier_label": "Cold"},  # 0 = catch-all (> 90d)
]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _bootstrap():
    frappe.db.begin()

    print("\n=== Seeding master data ===")
    _seed_intent_types()
    _seed_signals()
    _seed_score_template()

    print("\n=== Seeding shared context ===")
    ctx = _ensure_shared_context()

    frappe.db.commit()
    print("\n=== Done ===")
    return ctx


# ---------------------------------------------------------------------------
# Master data seeders
# ---------------------------------------------------------------------------

def _seed_intent_types():
    created = 0
    for it in INTENT_TYPES:
        if not frappe.db.exists("CRM Intent Type", it["name"]):
            frappe.get_doc({
                "doctype": "CRM Intent Type",
                "code": it["name"],
                "display_name": it["description_vi"],
                "importance": it["importance"],
            }).insert(ignore_permissions=True)
            created += 1
    print(f"  Intent Types: {created} created, {len(INTENT_TYPES) - created} skipped")


def _seed_signals():
    created = 0
    repaired = 0
    for source in SIGNALS:
        s = dict(source)
        if s.get("interaction_term"):
            s["interaction_term"] = _ensure_interaction_type(s["interaction_term"])
        if s.get("intent_type"):
            intent = next(item for item in INTENT_TYPES if item["name"] == s["intent_type"])
            s["intent_type"] = _ensure_intent_type(
                intent["name"], intent["importance"], intent["description_vi"]
            )
        if not frappe.db.exists("CRM Score Signal", s["signal_key"]):
            frappe.get_doc({"doctype": "CRM Score Signal", **s}).insert(ignore_permissions=True)
            created += 1
            continue
        doc = frappe.get_doc("CRM Score Signal", s["signal_key"])
        changed = False
        for field in (
            "label", "category", "signal_type", "condition_field", "condition_operator",
            "condition_value", "interaction_term", "intent_type",
        ):
            if field in s and getattr(doc, field, None) != s[field]:
                setattr(doc, field, s[field])
                changed = True
        if changed:
            doc.save(ignore_permissions=True)
            repaired += 1
    print(f"  Score Signals: {created} created, {repaired} repaired, {len(SIGNALS) - created - repaired} skipped")


def _seed_score_template():
    rules = [
        {"rule_kind": "positive", "signal": r["signal"], "base_points": r["base_points"], "max_points": r["max_points"], "is_active": 1}
        for r in SCORE_RULES
    ]
    neg_rules = [
        {"rule_kind": "negative", "signal": r["signal"], "penalty_amount": r["penalty_amount"],
         "cooldown_days": r["cooldown_days"], "max_penalties": r["max_penalties"], "is_active": 1}
        for r in NEGATIVE_RULES
    ]

    name = frappe.db.get_value("CRM Score Template", {"template_name": TEMPLATE_NAME}, "name")
    if name:
        doc = frappe.get_doc("CRM Score Template", name)
        doc.update({"status": "Active", "fit_weight": 0.4, "intent_weight": 0.3, "engagement_weight": 0.3})
        doc.set("rules", rules + [{"rule_kind": "time_decay", **tier} for tier in TIME_DECAY_TIERS] + neg_rules)
        doc.save(ignore_permissions=True)
        print(f"  Score Template: '{TEMPLATE_NAME}' updated")
        return

    frappe.get_doc({
        "doctype": "CRM Score Template",
        "template_name": TEMPLATE_NAME,
        "status": "Active",
        "fit_weight": 0.4,
        "intent_weight": 0.3,
        "engagement_weight": 0.3,
        "rules": rules + [{"rule_kind": "time_decay", **tier} for tier in TIME_DECAY_TIERS] + neg_rules,
    }).insert(ignore_permissions=True)
    print(f"  Score Template: '{TEMPLATE_NAME}' created")


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------

def _ensure_shared_context():
    province = _ensure_province()
    campus = _ensure_campus(province)
    return {
        "province": province,
        "ward":     _ensure_ward(province),
        "campus":   campus,
        "high_school": _ensure_high_school(province),
        "major":    _ensure_major(),
        "aspiration": _ensure_aspiration(),
        "source":   _ensure_lead_source(),
        "campaign": _ensure_campaign(campus),
        "event":    _ensure_event(),
        "admission_year": _ensure_admission_year(),
        "education_program": _ensure_education_program(),
        "enrollment_status": _ensure_enrollment_status("NEW"),
    }


# ---------------------------------------------------------------------------
# _ensure_* helpers — shared context
# ---------------------------------------------------------------------------

def _ensure_province():
    existing = frappe.db.get_value("CRM Province", {"province_code": PROVINCE_CODE}, "name")
    if existing:
        return existing
    return frappe.get_doc({
        "doctype": "CRM Province",
        "province_code": PROVINCE_CODE,
        "province_name": PROVINCE_NAME,
        "city_type": "Centrally Controlled City",
    }).insert(ignore_permissions=True).name


def _ensure_ward(province):
    existing = frappe.db.get_value("CRM Ward", {"ward_code": WARD_CODE}, "name")
    if existing:
        return existing
    return frappe.get_doc({
        "doctype": "CRM Ward",
        "ward_code": WARD_CODE,
        "ward_name": WARD_NAME,
        "province": province,
        "province_name": PROVINCE_NAME,
        "ward_type": "Ward",
    }).insert(ignore_permissions=True).name


def _ensure_campus(province):
    if frappe.db.exists("CRM Campus", CAMPUS):
        return CAMPUS
    return _create_governed_additive_value(
        "CRM Campus",
        CAMPUS,
        reason="Local admissions fixture campus for the HCMC recruitment cohort.",
    )


def _ensure_high_school(province):
    existing = frappe.db.exists("CRM High School", {"school_name": HIGH_SCHOOL, "province": province})
    if existing:
        return existing
    return frappe.get_doc({
        "doctype": "CRM High School",
        "school_name": HIGH_SCHOOL,
        "school_code": "HCM-TDN",
        "province": province,
        "ward": _ensure_ward(province),
        "address": "20 Ly Tu Trong, District 1, Ho Chi Minh City",
    }).insert(ignore_permissions=True).name


def _ensure_major():
    if frappe.db.exists("CRM Major", MAJOR):
        return MAJOR
    return frappe.get_doc({
        "doctype": "CRM Major",
        "major_name": MAJOR,
        "major_code": MAJOR_CODE,
        "is_active": 1,
    }).insert(ignore_permissions=True).name


def _ensure_aspiration():
    name = "NV1"
    if frappe.db.exists("CRM Aspiration", name):
        return name
    return frappe.get_doc({
        "doctype": "CRM Aspiration",
        "code": name,
        "display_name": "Nguyện vọng 1",
        "description": "First choice admission aspiration.",
    }).insert(ignore_permissions=True).name


def _ensure_lead_source():
    name = "FPTU Open Day"
    if frappe.db.exists("CRM Lead Source", name):
        return name
    return _create_governed_additive_value(
        "CRM Lead Source",
        name,
        reason="Local admissions fixture source for the HCMC Open Day campaign.",
    )


def _ensure_admission_year():
    year = str(datetime.now().year)
    if frappe.db.exists("CRM Admission Year", year):
        return year
    return frappe.get_doc({
        "doctype": "CRM Admission Year",
        "year_name": year,
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
        "is_active": 1,
    }).insert(ignore_permissions=True).name


def _ensure_education_program():
    name = "FPTU Software Engineering 2026"
    if frappe.db.exists("CRM Education Program", name):
        return name
    return frappe.get_doc({
        "doctype": "CRM Education Program",
        "program_name": name,
        "program_type": "Chính quy",
    }).insert(ignore_permissions=True).name


def _ensure_campaign(campus=None):
    if frappe.db.exists("CRM Campaign", CAMPAIGN):
        return CAMPAIGN
    ctype = _ensure_campaign_type()
    return frappe.get_doc({
        "doctype": "CRM Campaign",
        "title": CAMPAIGN,
        "campaign_type": ctype,
        "campus": campus or _ensure_campus(_ensure_province()),
        "start_date": f"{datetime.now().year}-01-01",
        "end_date": f"{datetime.now().year}-12-31",
    }).insert(ignore_permissions=True).name


def _ensure_campaign_type():
    name = "OPEN_DAY"
    if frappe.db.exists("CRM Campaign Type", name):
        return name
    return frappe.get_doc({
        "doctype": "CRM Campaign Type",
        "code": name,
        "display_name": "Ngày hội tuyển sinh",
        "description": "Campus visit and admission counseling campaign for the local fixture.",
    }).insert(ignore_permissions=True).name


def _ensure_event():
    if frappe.db.exists("CRM Event", EVENT):
        return EVENT
    return frappe.get_doc({
        "doctype": "CRM Event",
        "title": EVENT,
        "crm_campaign": _ensure_campaign(_ensure_campus(_ensure_province())),
        "event_date": frappe.utils.add_days(frappe.utils.today(), -7),
        "location": CAMPUS,
    }).insert(ignore_permissions=True).name


def _ensure_enrollment_status(code):
    if frappe.db.exists("CRM Enrollment Status", code):
        return code
    defaults = {"NEW": (10, "open", "Lead", "Mới")}
    stage_order, stage_category, lifecycle_stage, display_name = defaults.get(
        code, (10, "open", "Lead", code.replace("_", " ").title())
    )
    doc = frappe.get_doc({
        "doctype": "CRM Enrollment Status",
        "code": code,
        "display_name": display_name,
        "stage_order": stage_order,
        "sort_order": stage_order,
        "stage_category": stage_category,
        "lifecycle_stage": lifecycle_stage,
    }).insert(ignore_permissions=True)
    return code


def _ensure_interaction_type(name):
    code = name if frappe.db.exists("CRM Interaction Type", name) else _as_code(name)
    if frappe.db.exists("CRM Interaction Type", code):
        return code
    return frappe.get_doc({
        "doctype": "CRM Interaction Type",
        "code": code,
        "display_name": name,
    }).insert(ignore_permissions=True).name


def _ensure_intent_type(name, importance, description_vi):
    code = name if frappe.db.exists("CRM Intent Type", name) else _as_code(name)
    if frappe.db.exists("CRM Intent Type", code):
        # Importance now lives on the lookup row; keep fixture reruns self-healing.
        if frappe.db.get_value("CRM Intent Type", code, "importance") != importance:
            frappe.db.set_value("CRM Intent Type", code, "importance", importance)
        return code
    return frappe.get_doc({
        "doctype": "CRM Intent Type",
        "code": code,
        "display_name": description_vi,
        "importance": importance,
    }).insert(ignore_permissions=True).name


def _create_governed_additive_value(doctype, value, *, reason, category=None):
    """Create an additive lookup through its required governance boundary."""
    from crm.fcrm.master_data_governance import create_additive_value

    result = create_additive_value(
        doctype,
        value,
        reason=reason,
        idempotency_key=f"local-admissions-fixture:{doctype}:{value}",
        correlation_id="local-admissions-fixture",
        category=category,
    )
    return result["name"]
