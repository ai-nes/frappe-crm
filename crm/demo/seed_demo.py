"""
Demo seed — shared master data for local admissions fixtures.

Run with:
  bench --site <site> execute crm.demo.seed_demo.execute

What this creates (all idempotent):
  Master data
    CRM Term         — 8 types
    CRM Score Signal        — 22 signals (Fit / Engagement / Intent / Negative)
    CRM Score Template      — "Default Scoring 2026" (active)

  Shared context
    Province, Ward, Campus, High School, Major, Aspiration,
    Lead Source, Campaign, Event, Education Program, Admission Year
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import frappe


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
    {"name": "Major Inquiry",     "importance": "Medium",    "description_vi": "Hỏi về ngành học"},
    {"name": "Environment",       "importance": "Medium",    "description_vi": "Hỏi về môi trường học tập / ký túc xá"},
    {"name": "Tuition",           "importance": "High",      "description_vi": "Hỏi về học phí"},
    {"name": "Scholarship",       "importance": "High",      "description_vi": "Hỏi về học bổng"},
    {"name": "Dormitory",         "importance": "Medium",    "description_vi": "Hỏi về ký túc xá"},
    {"name": "Admission Process", "importance": "High",      "description_vi": "Hỏi về quy trình xét tuyển"},
    {"name": "Enrollment Intent", "importance": "Very High", "description_vi": "Có ý định đăng ký nhập học"},
    {"name": "Deposit Intent",    "importance": "Very High", "description_vi": "Sẵn sàng đặt cọc / xác nhận nhập học"},
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
        "interaction_type": "Website Visit",
    },
    {
        "signal_key": "major_view",     "label": "Major Page View",
        "category": "Engagement",       "signal_type": "interaction",
        "interaction_type": "Major View",
    },
    {
        "signal_key": "zalo_chat",      "label": "Zalo Chat",
        "category": "Engagement",       "signal_type": "interaction",
        "interaction_type": "Zalo Chat",
    },
    {
        "signal_key": "consultation_register", "label": "Consultation Register",
        "category": "Engagement",              "signal_type": "interaction",
        "interaction_type": "Consultation Register",
    },
    {
        "signal_key": "webinar",        "label": "Webinar Attendance",
        "category": "Engagement",       "signal_type": "interaction",
        "interaction_type": "Webinar",
    },
    {
        "signal_key": "open_day",       "label": "Open Day Visit",
        "category": "Engagement",       "signal_type": "interaction",
        "interaction_type": "Open Day",
    },
    {
        "signal_key": "application_submit", "label": "Application Submitted",
        "category": "Engagement",           "signal_type": "interaction",
        "interaction_type": "Application Submit",
    },
    # Intent — intent-type-based
    {
        "signal_key": "intent_major",       "label": "Intent: Major Inquiry",
        "category": "Intent",               "signal_type": "intent",
        "intent_type": "Major Inquiry",
    },
    {
        "signal_key": "intent_tuition",     "label": "Intent: Tuition Question",
        "category": "Intent",               "signal_type": "intent",
        "intent_type": "Tuition",
    },
    {
        "signal_key": "intent_scholarship", "label": "Intent: Scholarship Question",
        "category": "Intent",               "signal_type": "intent",
        "intent_type": "Scholarship",
    },
    {
        "signal_key": "intent_admission",   "label": "Intent: Admission Process",
        "category": "Intent",               "signal_type": "intent",
        "intent_type": "Admission Process",
    },
    {
        "signal_key": "intent_enroll",      "label": "Intent: Enrollment",
        "category": "Intent",               "signal_type": "intent",
        "intent_type": "Enrollment Intent",
    },
    {
        "signal_key": "intent_deposit",     "label": "Intent: Deposit",
        "category": "Intent",               "signal_type": "intent",
        "intent_type": "Deposit Intent",
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
        "interaction_type": "Refuse Consultation",
    },
    {
        "signal_key": "cancel_event",   "label": "Cancelled Event",
        "category": "Negative",         "signal_type": "interaction",
        "interaction_type": "Cancel Event",
    },
    {
        "signal_key": "transfer_school", "label": "Transferred to Another School",
        "category": "Negative",          "signal_type": "interaction",
        "interaction_type": "Transfer School",
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
# Student profiles
# Intent spec dict keys: type, importance, desc_vi, confidence, role, polarity, notes
# ---------------------------------------------------------------------------

STUDENTS = [
    # -----------------------------------------------------------------------
    # Student A — Nguyen Thu Ha
    # Grade 12, GPA 8.5, IELTS 6.5, top high school — strong fit
    # Activity: Zalo → Consultation → Open Day (5 days ago)
    # -----------------------------------------------------------------------
    {
        "email": "nguyen.thu.ha.fptu2026@example.com",
        "phone": "0909111001",
        "student_name": "Nguyen Thu Ha",
        "transcript_score": 8.5,
        "english_converted_score": 7.0,
        "graduation_score": 8.3,
        "total_score": 26.3,
        "admission_method": "Combined",
        "cohort_start_year": datetime.now().year,
        "cohort_end_year": datetime.now().year + 4,
        "academic_results": [
            {"school_year": "2024-2025", "grade": "12", "academic_rank": "Giỏi", "gpa": 8.5},
        ],
        "language_certificates": [
            {
                "language": "Tiếng Anh", "certificate_name": "IELTS", "score_level": "6.5",
                "issue_date": frappe.utils.add_months(frappe.utils.today(), -3),
                "expiry_date": frappe.utils.add_months(frappe.utils.today(), 21),
            },
        ],
        "interactions": [
            {
                "type": "Zalo Chat",
                "summary": "Thu Ha: Initial Zalo inquiry about tuition and scholarships",
                "days_ago": 12,
                "outcome": "Captured",
                "notes": "Student asked about tuition installment options and whether IELTS 6.5 qualifies for scholarship.",
                "intents": [
                    {"type": "Tuition",    "importance": "High",   "desc_vi": "Hỏi về học phí",  "confidence": 88, "role": "Dominant", "polarity": "Positive", "notes": "Asked about tuition payment schedule."},
                    {"type": "Scholarship","importance": "High",   "desc_vi": "Hỏi về học bổng", "confidence": 82, "role": "Support",  "polarity": "Positive", "notes": "Asked if IELTS qualifies for scholarship."},
                ],
            },
            {
                "type": "Consultation Register",
                "summary": "Thu Ha: Registered for 1-on-1 consultation session",
                "days_ago": 8,
                "outcome": "Captured",
                "notes": "Booked a consultation slot to discuss Software Engineering curriculum.",
                "intents": [
                    {"type": "Major Inquiry", "importance": "Medium", "desc_vi": "Hỏi về ngành học", "confidence": 80, "role": "Dominant", "polarity": "Positive", "notes": "Wanted details on SE curriculum and career paths."},
                ],
            },
            {
                "type": "Open Day",
                "summary": "Thu Ha: Attended FPTU HCMC Open Day",
                "days_ago": 5,
                "outcome": "Follow Up Needed",
                "notes": "Attended campus visit, confirmed SE as first choice, expressed enrollment intent.",
                "intents": [
                    {"type": "Enrollment Intent", "importance": "Very High", "desc_vi": "Ý định nhập học", "confidence": 94, "role": "Dominant", "polarity": "Positive", "notes": "Confirmed intent to enroll after Open Day."},
                ],
            },
        ],
    },

    # -----------------------------------------------------------------------
    # Student B — Tran Quoc Bao
    # Grade 12, GPA 7.2, no certificates — weak fit, inactive 50 days
    # -----------------------------------------------------------------------
    {
        "email": "tran.quoc.bao.fptu2026@example.com",
        "phone": "0909222002",
        "student_name": "Tran Quoc Bao",
        "transcript_score": 7.2,
        "english_converted_score": 0.0,
        "graduation_score": 7.0,
        "total_score": 21.2,
        "admission_method": "Transcript Review",
        "cohort_start_year": datetime.now().year,
        "cohort_end_year": datetime.now().year + 4,
        "academic_results": [
            {"school_year": "2024-2025", "grade": "12", "academic_rank": "Khá", "gpa": 7.2},
        ],
        "language_certificates": [],
        "interactions": [
            {
                "type": "Website Visit",
                "summary": "Bao: Viewed university website and major page",
                "days_ago": 50,
                "outcome": "Captured",
                "notes": "Student browsed the Software Engineering major page. No follow-up action taken.",
                "intents": [
                    {"type": "Major Inquiry", "importance": "Medium", "desc_vi": "Hỏi về ngành học", "confidence": 65, "role": "Dominant", "polarity": "Positive", "notes": "Browsed SE major page — passive interest."},
                ],
            },
        ],
    },

    # -----------------------------------------------------------------------
    # Student C — Le Phuong Linh
    # Grade 11, GPA 7.8, no certificates — zero fit score
    # Activity: Zalo → Webinar → Cancel Event → Application Submit (3 days ago)
    # -----------------------------------------------------------------------
    {
        "email": "le.phuong.linh.fptu2026@example.com",
        "phone": "0909333003",
        "student_name": "Le Phuong Linh",
        "transcript_score": 7.8,
        "english_converted_score": 0.0,
        "graduation_score": 7.5,
        "total_score": 22.8,
        "admission_method": "Transcript Review",
        "cohort_start_year": datetime.now().year + 1,
        "cohort_end_year": datetime.now().year + 5,
        "academic_results": [
            {"school_year": "2024-2025", "grade": "11", "academic_rank": "Khá", "gpa": 7.8},
        ],
        "language_certificates": [],
        "interactions": [
            {
                "type": "Zalo Chat",
                "summary": "Linh: Zalo chat about admission requirements",
                "days_ago": 14,
                "outcome": "Captured",
                "notes": "Student asked about admission requirements and whether grade 11 students can apply early.",
                "intents": [
                    {"type": "Admission Process", "importance": "High",   "desc_vi": "Hỏi quy trình xét tuyển", "confidence": 85, "role": "Dominant", "polarity": "Positive", "notes": "Asked if grade 11 students can register for early admission."},
                    {"type": "Major Inquiry",     "importance": "Medium", "desc_vi": "Hỏi về ngành học",        "confidence": 70, "role": "Support",  "polarity": "Positive", "notes": "Also asked about SE vs IT differences."},
                ],
            },
            {
                "type": "Webinar",
                "summary": "Linh: Attended online admission information session",
                "days_ago": 7,
                "outcome": "Captured",
                "notes": "Attended webinar, asked about deposit timeline and reservation policy.",
                "intents": [
                    {"type": "Deposit Intent", "importance": "Very High", "desc_vi": "Ý định đặt cọc", "confidence": 91, "role": "Dominant", "polarity": "Positive", "notes": "Asked about deposit amount and deadline — strong purchase signal."},
                ],
            },
            {
                "type": "Cancel Event",
                "summary": "Linh: Cancelled registered Open Day slot",
                "days_ago": 5,
                "outcome": "Captured",
                "notes": "Student cancelled Open Day registration. Reason: family travel conflict.",
                "intents": [],
            },
            {
                "type": "Application Submit",
                "summary": "Linh: Submitted early admission application",
                "days_ago": 3,
                "outcome": "Follow Up Needed",
                "notes": "Submitted application despite being grade 11 — counselor must verify eligibility.",
                "intents": [
                    {"type": "Enrollment Intent", "importance": "Very High", "desc_vi": "Ý định nhập học", "confidence": 88, "role": "Dominant", "polarity": "Positive", "notes": "Submitted formal application — highest conversion signal."},
                ],
            },
        ],
    },
]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def execute():
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
        if not frappe.db.exists("CRM Term", it["name"]):
            _create_governed_additive_value(
                "CRM Term",
                it["name"],
                reason=f"Local scoring fixture: {it['description_vi']}",
                category="intent_type",
            )
            created += 1
    print(f"  Intent Types: {created} created, {len(INTENT_TYPES) - created} skipped")


def _seed_signals():
    created = 0
    for s in SIGNALS:
        if not frappe.db.exists("CRM Score Signal", s["signal_key"]):
            frappe.get_doc({"doctype": "CRM Score Signal", **s}).insert(ignore_permissions=True)
            created += 1
    print(f"  Score Signals: {created} created, {len(SIGNALS) - created} skipped")


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
        "enrollment_status": _ensure_enrollment_status("Mới"),
    }


# ---------------------------------------------------------------------------
# Student seeder
# ---------------------------------------------------------------------------

def _seed_student(profile, ctx):
    email = profile["email"]

    existing = frappe.db.exists("CRM Student", {"email": email})
    if existing:
        student = frappe.get_doc("CRM Student", existing)
    else:
        student = frappe.get_doc({"doctype": "CRM Student"})

    student.update({
        "student_name":            profile["student_name"],
        "phone":                   profile["phone"],
        "email":                   email,
        "enrollment_status":       ctx["enrollment_status"],
        "high_school":             ctx["high_school"],
        "province":                ctx["province"],
        "ward":                    ctx["ward"],
        "branch":                  ctx["campus"],
        "major":                   ctx["major"],
        "aspiration":              ctx["aspiration"],
        "source":                  ctx["source"],
        "admission_year":          ctx["admission_year"],
        "education_program":       ctx["education_program"],
        "cohort_start_year":       profile["cohort_start_year"],
        "cohort_end_year":         profile["cohort_end_year"],
        "transcript_score":        profile["transcript_score"],
        "graduation_score":        profile["graduation_score"],
        "english_converted_score": profile["english_converted_score"],
        "total_score":             profile["total_score"],
        "admission_method":        profile["admission_method"],
    })
    student.set("academic_results",      profile["academic_results"])
    student.set("language_certificates", profile["language_certificates"])

    if existing:
        student.save(ignore_permissions=True)
    else:
        student.insert(ignore_permissions=True)

    print(f"  Student '{profile['student_name']}': {student.name}")
    _seed_interactions(student, profile["interactions"])


def _seed_interactions(student, interaction_specs):
    for spec in interaction_specs:
        itype = _ensure_interaction_type(spec["type"])
        existing = frappe.db.exists("CRM Interaction", {
            "student": student.name,
            "summary": spec["summary"],
        })
        if existing:
            interaction_name = existing
        else:
            interaction = frappe.get_doc({
                "doctype": "CRM Interaction",
                "student": student.name,
                "interaction_type": itype,
                "interaction_datetime": datetime.now() - timedelta(days=spec["days_ago"]),
                "outcome": spec["outcome"],
                "summary": spec["summary"],
                "notes": spec["notes"],
            })
            interaction.insert(ignore_permissions=True)
            interaction_name = interaction.name

        _seed_intents(interaction_name, spec.get("intents", []))


def _seed_intents(interaction_name, intent_specs):
    for s in intent_specs:
        itype_name = _ensure_intent_type(s["type"], s["importance"], s["desc_vi"])
        if frappe.db.exists("CRM Intent", {"interaction": interaction_name, "intent_type": itype_name}):
            continue
        frappe.get_doc({
            "doctype": "CRM Intent",
            "interaction": interaction_name,
            "intent_type": itype_name,
            "confidence": s["confidence"],
            "intent_role": s["role"],
            "polarity": s["polarity"],
            "notes": s["notes"],
        }).insert(ignore_permissions=True)


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
    if frappe.db.exists("CRM Term", name):
        return name
    return frappe.get_doc({
        "doctype": "CRM Term",
        "term_name": name,
        "category": "aspiration",
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
    name = "Open Day"
    if frappe.db.exists("CRM Term", name):
        return name
    return _create_governed_additive_value(
        "CRM Term",
        name,
        reason="Campus visit and admission counseling campaign for the local fixture.",
        category="campaign_type",
    )


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


def _ensure_enrollment_status(status_name):
    if frappe.db.exists("CRM Term", status_name):
        return status_name
    defaults = {"Mới": (10, "open", "Lead")}
    stage_order, stage_category, lifecycle_stage = defaults.get(status_name, (10, "open", "Lead"))
    doc = frappe.get_doc({
        "doctype": "CRM Term",
        "term_name": status_name,
        "category": "enrollment_status",
        "sort_order": stage_order,
        "metadata": {"stage_category": stage_category, "lifecycle_stage": lifecycle_stage},
    }).insert(ignore_permissions=True)
    return doc.name


def _ensure_interaction_type(name):
    if frappe.db.exists("CRM Term", name):
        return name
    return frappe.get_doc({
        "doctype": "CRM Term",
        "term_name": name,
        "category": "interaction_type",
    }).insert(ignore_permissions=True).name


def _ensure_intent_type(name, importance, description_vi):
    term = frappe.db.exists("CRM Term", name)
    if not term:
        term = _create_governed_additive_value(
            "CRM Term",
            name,
            reason=f"Local scoring fixture: {description_vi}",
            category="intent_type",
        )
    # CRM Intent.importance is read-only and always derived from its
    # intent_type term's metadata (crm_intent.py before_validate), so the
    # term must carry the importance level, not the individual intent.
    # Backfill on every call (not just creation) so terms left over from
    # earlier fixture runs, seeded before this metadata existed, self-heal.
    current_metadata = frappe.db.get_value("CRM Term", term, "metadata")
    if not current_metadata or json.loads(current_metadata).get("importance") != importance:
        frappe.db.set_value("CRM Term", term, "metadata", frappe.as_json({"importance": importance}))
    return term


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
