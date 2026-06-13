"""
Full demo seed — master data + 3 test students with scored histories.

Run with:
  bench --site <site> execute crm.demo.seed_demo.execute

What this creates (all idempotent):
  Master data
    CRM Intent Type         — 8 types
    CRM Score Signal        — 22 signals (Fit / Engagement / Intent / Negative)
    CRM Score Template      — "Default Scoring 2026" (active)

  Test students
    Student A  Nguyen Thu Ha   — high-potential lead          expected final ≈  75
    Student B  Tran Quoc Bao   — cold / disengaged lead       expected final ≈   2
    Student C  Le Phuong Linh  — intent-driven, low fit       expected final ≈  48

  Shared context
    Province, Ward, Campus, High School, Major, Aspiration,
    Lead Source, Campaign, Event, Education Program, Admission Year

Expected score derivation (formula):
  non_decay = 0.4 * Fit_score
  decayable = 0.3 * Engagement_score + 0.3 * Intent_score
  final     = non_decay + decayable * time_decay_factor + min(0, Negative_score)
  LeadHealthScore = max(0, min(100, final))
"""

from __future__ import annotations

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
# ---------------------------------------------------------------------------
#
# Score formula:
#   raw = (fit_total * 0.34) + (intent_total * 0.33) + (engagement_total * 0.33)
#   decayed = raw * decay_multiplier
#   final = decayed + sum(penalties)

STUDENTS = [
    # -----------------------------------------------------------------------
    # Student A — Nguyen Thu Ha
    # Profile:  Grade 12, GPA 8.5, IELTS 6.5, top high school → strong fit
    # Activity: zalo_chat + consultation + open_day, 5 days ago → tier 1 (1.0)
    # Intents:  Tuition (Dominant) + Enrollment (Dominant in later interaction)
    #
    # Fit         = 20 + 20 + 15 + 15 = 70
    # Engagement  = 10 + 20 + 30      = 60
    # Intent      = 25 + 70           = 95
    # Negative    = 0
    # TimeDecay   = 1.0  (last activity 5d ago → tier Hot ≤ 30d)
    # non_decay   = 0.4 × 70                   = 28.0
    # decayable   = (0.3×60 + 0.3×95) × 1.0   = (18 + 28.5) × 1.0 = 46.5
    # EXPECTED    = max(0, min(100, 28.0 + 46.5 + 0)) = 74.5 ≈ 75
    # -----------------------------------------------------------------------
    {
        "email": "nguyen.thu.ha.fptu2026@example.com",
        "phone": "+84 909 111 001",
        "student_name": "Nguyen Thu Ha",
        "transcript_score": 8.5,
        "english_converted_score": 7.0,   # IELTS 6.5 → converted 7.0
        "graduation_score": 8.3,
        "total_score": 26.3,
        "admission_method": "Combined",
        "cohort_start_year": datetime.now().year,
        "cohort_end_year": datetime.now().year + 4,
        "academic_results": [
            {"school_year": "2024-2025", "grade": "12", "academic_rank": "Giỏi", "gpa": 8.5},
        ],
        "language_certificates": [
            {"language": "Tiếng Anh", "certificate_name": "IELTS", "score_level": "6.5",
             "issue_date": frappe.utils.add_months(frappe.utils.today(), -3),
             "expiry_date": frappe.utils.add_months(frappe.utils.today(), 21)},
        ],
        "interactions": [
            {
                "type": "Zalo Chat",
                "summary": "Thu Ha: Initial Zalo inquiry about tuition and scholarships",
                "days_ago": 12,
                "outcome": "Captured",
                "notes": "Student asked about tuition installment options and whether IELTS 6.5 qualifies for scholarship.",
                "intents": [
                    ("Tuition",    "High",      "Hỏi về học phí", 88, "Dominant", "Asked about tuition payment schedule."),
                    ("Scholarship","High",      "Hỏi về học bổng", 82, "Support",  "Asked if IELTS qualifies for scholarship."),
                ],
            },
            {
                "type": "Consultation Register",
                "summary": "Thu Ha: Registered for 1-on-1 consultation session",
                "days_ago": 8,
                "outcome": "Captured",
                "notes": "Booked a consultation slot to discuss Software Engineering curriculum.",
                "intents": [
                    ("Major Inquiry", "Medium", "Hỏi về ngành học", 80, "Dominant", "Wanted details on SE curriculum and career paths."),
                ],
            },
            {
                "type": "Open Day",
                "summary": "Thu Ha: Attended FPTU HCMC Open Day",
                "days_ago": 5,
                "outcome": "Follow Up Needed",
                "notes": "Attended campus visit, confirmed SE as first choice, expressed enrollment intent.",
                "intents": [
                    ("Enrollment Intent", "Very High", "Ý định nhập học", 94, "Dominant", "Confirmed intent to enroll after Open Day."),
                ],
            },
        ],
        # Score snapshot — single history row representing current state
        "score_history": {
            "fit_score": 70.0,
            "engagement_score": 60.0,
            "intent_score": 95.0,
            "time_decay_score": 74.95,   # raw before negative
            "negative_score": 0.0,
            "final_score": 74.95,
            "score_change": 0.0,
            "days_ago": 5,
            "details": [
                ("Fit",        "grade_12",             "Grade 12 Student",         20.0, "Verified grade 12 from academic results."),
                ("Fit",        "gpa_high",             "High GPA (>= 8.0)",        20.0, "Transcript score 8.5 >= 8.0."),
                ("Fit",        "ielts_6",              "IELTS >= 6.0",             15.0, "IELTS 6.5 on record."),
                ("Fit",        "top_school",           "Top High School",          15.0, "Tran Dai Nghia is a gifted school."),
                ("Engagement", "zalo_chat",            "Zalo Chat",                10.0, "Initiated Zalo inquiry."),
                ("Engagement", "consultation_register","Consultation Register",    20.0, "Booked consultation slot."),
                ("Engagement", "open_day",             "Open Day Visit",           30.0, "Attended campus open day."),
                ("Intent",     "intent_tuition",       "Intent: Tuition Question", 25.0, "Dominant intent: tuition inquiry."),
                ("Intent",     "intent_enroll",        "Intent: Enrollment",       70.0, "Dominant intent: enrollment confirmed."),
            ],
        },
        # Expected output annotation (printed at end of seed)
        "expected": {
            "fit": 70, "engagement": 60, "intent": 95,
            "decay_multiplier": 1.0, "decay_tier": "Tier 1 (≤30 days)",
            "negative": 0, "final": 74.95,
            "note": "Hot lead — strong across all 3 dimensions, recent activity.",
        },
    },

    # -----------------------------------------------------------------------
    # Student B — Tran Quoc Bao
    # Profile:  Grade 12, GPA 7.2, no certificates → weak fit
    # Activity: website_visit + major_view only, last activity 50 days ago → tier 2 (0.7)
    # Intents:  Major Inquiry only (low signal)
    # Negative: no_contact_30 fires → −10
    #
    # Fit         = 20
    # Engagement  = 2 + 5      =  7
    # Intent      = 10         = 10
    # Negative    = −10  (no_contact_30)
    # TimeDecay   = 0.7  (last activity 50d ago → tier Warm 31–60d)
    # non_decay   = 0.4 × 20                   =  8.0
    # decayable   = (0.3×7 + 0.3×10) × 0.7    = (2.1 + 3.0) × 0.7 = 3.57
    # EXPECTED    = max(0, min(100, 8.0 + 3.57 − 10)) = max(0, 1.57) ≈ 2
    # (cold lead — low fit, almost no engagement, decayed)
    # -----------------------------------------------------------------------
    {
        "email": "tran.quoc.bao.fptu2026@example.com",
        "phone": "+84 909 222 002",
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
                    ("Major Inquiry", "Medium", "Hỏi về ngành học", 65, "Dominant", "Browsed SE major page — passive interest."),
                ],
            },
        ],
        "score_history": {
            "fit_score": 20.0,
            "engagement_score": 7.0,
            "intent_score": 10.0,
            "time_decay_score": 8.69,
            "negative_score": -10.0,
            "final_score": -1.31,
            "score_change": 0.0,
            "days_ago": 50,
            "details": [
                ("Fit",        "grade_12",    "Grade 12 Student",         20.0,  "Verified grade 12."),
                ("Engagement", "website_visit","Website Visit",            2.0,  "One tracked website visit."),
                ("Engagement", "major_view",  "Major Page View",           5.0,  "Viewed SE major detail page."),
                ("Intent",     "intent_major","Intent: Major Inquiry",    10.0,  "Passive browse — no direct question asked."),
                ("Time Decay", "tier_2",      "Tier 2 decay applied",     -3.72, "50 days since last activity → 0.7x multiplier."),
                ("Negative",   "no_contact_30","No Contact 30 Days",     -10.0,  "No interaction in over 30 days."),
            ],
        },
        "expected": {
            "fit": 20, "engagement": 7, "intent": 10,
            "decay_multiplier": 0.7, "decay_tier": "Tier 2 (31–60 days)",
            "negative": -10, "final": -1.31,
            "note": "Cold lead — minimal engagement, no certificates, inactive 50 days. Negative final score signals deprioritisation.",
        },
    },

    # -----------------------------------------------------------------------
    # Student C — Le Phuong Linh
    # Profile:  Grade 11 (not 12), GPA 7.8, no IELTS → zero fit score
    # Activity: zalo_chat + webinar + application_submit, 3 days ago → tier 1 (1.0)
    # Intents:  Admission Process (Dominant) + Deposit Intent (Dominant later)
    # Negative: cancel_event fires → −20
    #
    # Fit         = 0
    # Engagement  = 10 + 25 + 50 =  85
    # Intent      = 50 + 90      = 140
    # Negative    = −20  (cancel_event fires once)
    # TimeDecay   = 1.0  (last activity 3d ago → tier Hot ≤ 30d)
    # non_decay   = 0.4 × 0                    =  0.0
    # decayable   = (0.3×85 + 0.3×140) × 1.0  = (25.5 + 42) × 1.0 = 67.5
    # EXPECTED    = max(0, min(100, 0 + 67.5 − 20)) = 47.5 ≈ 48
    # (high intent/engagement, but fit is 0 — counselor must verify eligibility)
    # Edge case: strong intent/engagement but counselor must verify eligibility
    # -----------------------------------------------------------------------
    {
        "email": "le.phuong.linh.fptu2026@example.com",
        "phone": "+84 909 333 003",
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
                    ("Admission Process", "High", "Hỏi quy trình xét tuyển", 85, "Dominant", "Asked if grade 11 students can register for early admission."),
                    ("Major Inquiry",     "Medium","Hỏi về ngành học",       70, "Support",  "Also asked about SE vs IT differences."),
                ],
            },
            {
                "type": "Webinar",
                "summary": "Linh: Attended online admission information session",
                "days_ago": 7,
                "outcome": "Captured",
                "notes": "Attended webinar, asked about deposit timeline and reservation policy.",
                "intents": [
                    ("Deposit Intent", "Very High", "Ý định đặt cọc", 91, "Dominant", "Asked about deposit amount and deadline — strong purchase signal."),
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
                    ("Enrollment Intent", "Very High", "Ý định nhập học", 88, "Dominant", "Submitted formal application — highest conversion signal."),
                ],
            },
        ],
        "score_history": {
            "fit_score": 0.0,
            "engagement_score": 85.0,
            "intent_score": 140.0,
            "time_decay_score": 74.25,
            "negative_score": -20.0,
            "final_score": 54.25,
            "score_change": 0.0,
            "days_ago": 3,
            "details": [
                ("Engagement", "zalo_chat",         "Zalo Chat",                10.0,  "Initiated Zalo inquiry."),
                ("Engagement", "webinar",           "Webinar Attendance",       25.0,  "Attended online info session."),
                ("Engagement", "application_submit","Application Submitted",    50.0,  "Submitted formal application."),
                ("Intent",     "intent_admission",  "Intent: Admission Process",50.0,  "Dominant: asked about admission steps."),
                ("Intent",     "intent_deposit",    "Intent: Deposit",          90.0,  "Dominant: asked about deposit — strong signal."),
                ("Negative",   "cancel_event",      "Cancelled Event",         -20.0,  "Cancelled Open Day registration."),
            ],
        },
        "expected": {
            "fit": 0, "engagement": 85, "intent": 140,
            "decay_multiplier": 1.0, "decay_tier": "Tier 1 (≤30 days)",
            "negative": -20, "final": 54.25,
            "note": "Edge case — zero fit (grade 11, no certs) but strong intent/engagement. "
                    "AI flags high intent; counselor must verify eligibility before converting.",
        },
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
    template_name = _seed_score_template()

    print("\n=== Seeding shared context ===")
    ctx = _ensure_shared_context()

    print("\n=== Seeding test students ===")
    results = []
    for profile in STUDENTS:
        r = _seed_student(profile, ctx, template_name)
        results.append(r)

    frappe.db.commit()

    print("\n=== Expected Score Summary ===")
    print(f"{'Student':<25} {'Fit':>6} {'Eng':>6} {'Int':>6} {'Decay':>7} {'Neg':>6} {'Final':>7}  Note")
    print("-" * 100)
    for r in results:
        e = r["expected"]
        print(
            f"{r['student_name']:<25} "
            f"{e['fit']:>6} {e['engagement']:>6} {e['intent']:>6} "
            f"{e['decay_multiplier']:>7.1f} {e['negative']:>6} {e['final']:>7.2f}  "
            f"{e['note']}"
        )

    return {"students": [r["student"] for r in results], "template": template_name}


# ---------------------------------------------------------------------------
# Master data seeders
# ---------------------------------------------------------------------------

def _seed_intent_types():
    created = 0
    for it in INTENT_TYPES:
        if not frappe.db.exists("CRM Intent Type", it["name"]):
            frappe.get_doc({
                "doctype": "CRM Intent Type",
                "intent_type_name": it["name"],
                "importance": it["importance"],
                "description_vi": it["description_vi"],
            }).insert(ignore_permissions=True)
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
    if frappe.db.exists("CRM Score Template", {"template_name": TEMPLATE_NAME}):
        name = frappe.db.get_value("CRM Score Template", {"template_name": TEMPLATE_NAME}, "name")
        print(f"  Score Template: '{TEMPLATE_NAME}' already exists — skipped")
        return name

    doc = frappe.get_doc({
        "doctype": "CRM Score Template",
        "template_name": TEMPLATE_NAME,
        "status": "Active",
        "fit_weight": 0.34,
        "intent_weight": 0.33,
        "engagement_weight": 0.33,
        "rules": [
            {"signal": r["signal"], "base_points": r["base_points"], "max_points": r["max_points"], "is_active": 1}
            for r in SCORE_RULES
        ],
        "time_decay_config": TIME_DECAY_TIERS,
        "negative_rules": [
            {"signal": r["signal"], "penalty_amount": r["penalty_amount"],
             "cooldown_days": r["cooldown_days"], "max_penalties": r["max_penalties"], "is_active": 1}
            for r in NEGATIVE_RULES
        ],
    })
    doc.insert(ignore_permissions=True)
    print(f"  Score Template: '{TEMPLATE_NAME}' created")
    return doc.name


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
        "enrollment_status": _ensure_enrollment_status("Chưa xác nhận"),
    }


# ---------------------------------------------------------------------------
# Student seeder
# ---------------------------------------------------------------------------

def _seed_student(profile, ctx, template_name):
    email = profile["email"]

    # Student
    existing = frappe.db.exists("CRM Student", {"email": email})
    if existing:
        student = frappe.get_doc("CRM Student", existing)
    else:
        student = frappe.get_doc({"doctype": "CRM Student"})

    student.update({
        "student_name":          profile["student_name"],
        "phone":                 profile["phone"],
        "email":                 email,
        "enrollment_status":     ctx["enrollment_status"],
        "high_school":           ctx["high_school"],
        "province":              ctx["province"],
        "ward":                  ctx["ward"],
        "branch":                ctx["campus"],
        "major":                 ctx["major"],
        "aspiration":            ctx["aspiration"],
        "source":                ctx["source"],
        "admission_year":        ctx["admission_year"],
        "education_program":     ctx["education_program"],
        "cohort_start_year":     profile["cohort_start_year"],
        "cohort_end_year":       profile["cohort_end_year"],
        "transcript_score":      profile["transcript_score"],
        "graduation_score":      profile["graduation_score"],
        "english_converted_score": profile["english_converted_score"],
        "total_score":           profile["total_score"],
        "admission_method":      profile["admission_method"],
    })
    student.set("academic_results",    profile["academic_results"])
    student.set("language_certificates", profile["language_certificates"])

    if existing:
        student.save(ignore_permissions=True)
    else:
        student.insert(ignore_permissions=True)

    print(f"  Student '{profile['student_name']}': {student.name}")

    # Interactions + Intents
    interaction_names = _seed_interactions(student, profile["interactions"])

    # Score History
    _seed_score_history(student, template_name, profile["score_history"])

    return {
        "student": student.name,
        "student_name": profile["student_name"],
        "interactions": interaction_names,
        "expected": profile["expected"],
    }


def _seed_interactions(student, interaction_specs):
    names = []
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

        names.append(interaction_name)
        _seed_intents(interaction_name, spec.get("intents", []))

    return names


def _seed_intents(interaction_name, intent_specs):
    # Validate: at most one Dominant per interaction
    has_dominant = False
    for intent_type, importance, desc_vi, confidence, role, notes in intent_specs:
        if role == "Dominant":
            if has_dominant:
                role = "Support"   # downgrade extras to Support to avoid validation error
            else:
                has_dominant = True

        itype_name = _ensure_intent_type(intent_type, importance, desc_vi)
        if frappe.db.exists("CRM Intent", {"interaction": interaction_name, "intent_type": itype_name}):
            continue

        frappe.get_doc({
            "doctype": "CRM Intent",
            "interaction": interaction_name,
            "intent_type": itype_name,
            "confidence": confidence,
            "intent_role": role,
            "notes": notes,
        }).insert(ignore_permissions=True)


def _seed_score_history(student, template_name, spec):
    existing = frappe.db.exists("CRM Score History", {
        "student": student.name,
        "score_template": template_name,
    })
    if existing:
        return existing

    scoring_time = datetime.now() - timedelta(days=spec["days_ago"])
    doc = frappe.get_doc({
        "doctype": "CRM Score History",
        "student": student.name,
        "score_template": template_name,
        "scoring_time": scoring_time,
        "scoring_date": scoring_time.date(),
        "fit_score":        spec["fit_score"],
        "engagement_score": spec["engagement_score"],
        "intent_score":     spec["intent_score"],
        "time_decay_score": spec["time_decay_score"],
        "negative_score":   spec["negative_score"],
        "final_score":      spec["final_score"],
        "score_change":     spec["score_change"],
        "details": [
            {"category": cat, "rule_id": rid, "signal": sig, "score": score, "reason": reason}
            for cat, rid, sig, score, reason in spec["details"]
        ],
    })
    doc.insert(ignore_permissions=True)
    return doc.name


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
    return frappe.get_doc({
        "doctype": "CRM Campus",
        "campus_name": CAMPUS,
        "campus_code": "FPTU-HCM",
        "is_default": 1,
        "province": province,
        "address": "Saigon Hi-Tech Park, Thu Duc City, Ho Chi Minh City",
        "phone": "+84 28 7300 5588",
    }).insert(ignore_permissions=True).name


def _ensure_high_school(province):
    existing = frappe.db.exists("CRM High School", {"school_name": HIGH_SCHOOL, "province_code": PROVINCE_CODE})
    if existing:
        return existing
    return frappe.get_doc({
        "doctype": "CRM High School",
        "school_name": HIGH_SCHOOL,
        "school_code": "HCM-TDN",
        "ward_code": WARD_CODE,
        "ward_name": WARD_NAME,
        "province_code": PROVINCE_CODE,
        "province_name": PROVINCE_NAME,
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
        "aspiration_name": name,
        "description": "First choice admission aspiration.",
    }).insert(ignore_permissions=True).name


def _ensure_lead_source():
    name = "FPTU Open Day"
    if frappe.db.exists("CRM Lead Source", name):
        return name
    return frappe.get_doc({
        "doctype": "CRM Lead Source",
        "source_name": name,
    }).insert(ignore_permissions=True).name


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
    if frappe.db.exists("CRM Campaign Type", name):
        return name
    return frappe.get_doc({
        "doctype": "CRM Campaign Type",
        "campaign_type_name": name,
        "description": "Campus visit and admission counseling campaign.",
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


def _ensure_enrollment_status(status_name):
    if frappe.db.exists("CRM Enrollment Status", status_name):
        return status_name
    return frappe.get_doc({
        "doctype": "CRM Enrollment Status",
        "status_name": status_name,
    }).insert(ignore_permissions=True).name


def _ensure_interaction_type(name):
    if frappe.db.exists("CRM Interaction Type", name):
        return name
    return frappe.get_doc({
        "doctype": "CRM Interaction Type",
        "interaction_type_name": name,
    }).insert(ignore_permissions=True).name


def _ensure_intent_type(name, importance, description_vi):
    if frappe.db.exists("CRM Intent Type", name):
        return name
    return frappe.get_doc({
        "doctype": "CRM Intent Type",
        "intent_type_name": name,
        "importance": importance,
        "description_vi": description_vi,
    }).insert(ignore_permissions=True).name
