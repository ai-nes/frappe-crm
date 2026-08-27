"""Idempotent fictional cohort for crm-agents live validation.

Run: bench --site crm.localhost execute crm.demo.seed_e2e.execute
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta

import frappe
import requests
from frappe.utils import now_datetime

from crm.api.user import set_canonical_crm_profile
from crm.demo import seed_demo
from crm.fcrm.doctype.crm_student.enrollment_transition import record_transition

PREFIX = "E2E-FPT-2026"
FIXTURE_VERSION = "capture-v1"
FIXTURE_RUN_ID = f"{PREFIX}-{FIXTURE_VERSION}"
FIXTURE_CREATED_AT = datetime(2026, 8, 23, 9, 0, 0)
LIVE_TEST_CLIENT = f"{PREFIX} Agent Client"
LIVE_TEST_USERS = {
    "sales": ("e2e.sales@example.test", "Sale"),
    "marketing": ("e2e.marketing@example.test", "Marketing"),
    "lead_sales": ("e2e.lead-sales@example.test", "Lead Sales"),
    "admissions_director": ("e2e.admissions-director@example.test", "Admissions Director"),
    # Deliberately unresolved by crm-agents; never make this test identity a
    # privileged System Manager account merely to prove fail-closed behavior.
    "admin": ("e2e.admin@example.test", "E2E Test Admin"),
}
_E2E_TOKEN_TTL_SECONDS = 60 * 60
_MANAGED_ROLE_ALIASES = {
	"System Manager", "CRM Manager", "Sales Manager", "Sales User", "Sales", "Sale",
	"CTV-Sale", "Marketing", "Promoter-PR", "Team Leader",
    "Lead Sales", "Admissions Director", "Giám đốc Tuyển sinh",
}

CASES = [
    ("01", "Nguyen Minh An", "Có triển vọng", 18, "Deposit Intent", "Very High", "Zalo Chat", 3, "Captured", "Hỏi học phí, học bổng và xác nhận muốn gọi lại hôm nay."),
    ("02", "Tran Gia Han", "Mới", 4, "Enrollment Intent", "Very High", "Consultation Register", 4, "Captured", "Phụ huynh hỏi hồ sơ nhập học nhưng chưa được xử lý."),
    ("03", "Le Quang Huy", "Có triển vọng", 2, "Major Inquiry", "Medium", "Zalo Chat", 0, "Captured", "Vừa tư vấn ngành AI, chưa cần liên hệ lại ngay."),
    ("04", "Pham Thu Vy", "Đã xác nhận", 8, "Tuition", "High", "Phone Call", 1, "Resolved", "Đã giải đáp học phí và xác nhận tài chính."),
    ("05", "Do Khanh Linh", "Đã nhập học", 1, "Enrollment Intent", "Very High", "Application Submit", 2, "Converted", "Đã hoàn tất nhập học."),
    ("06", "Bui Hoang Nam", "Có triển vọng", 12, "Major Inquiry", "Medium", "Zalo Chat", 5, "No Response", "Đã nói chưa quan tâm trong giai đoạn này."),
    ("07", "Vo Mai Phuong", "Có triển vọng", 9, "Major Inquiry", "High", "Zalo Chat", 1, "Captured", "Ban đầu hỏi Digital Marketing, nay chuyển sang Thiết kế đồ họa."),
    ("08", "Dang Tuan Kiet", "Mới", 3, "Major Inquiry", "Medium", "Open Day", 7, "Captured", "Đã tham gia Open Day, quan tâm môi trường học tập."),
    ("09", "Ngo Bao Chau", "Có triển vọng", 1, "Admission Process", "Very High", "Consultation Register", 16, "Captured", "Hồ sơ cần bổ sung, vừa được chuyển sang giai đoạn mới."),
    ("10", "Huynh Gia Bao", "Từ chối", 6, "Tuition", "High", "Phone Call", 10, "No Response", "Đã chọn trường khác."),
]

# Capture starts with two deterministic, active recommendations.  Their input
# intent IDs are Frappe-owned fixture data, so the normal Recommendation
# controller still supplies its deterministic fingerprint/name.  The later
# accept transition exercises the real action/outbox lifecycle.
CAPTURE_CASES = (
	("01", "CALL", "high"),
	("02", "FOLLOW_UP", "medium"),
)


@contextmanager
def _fixture_lock():
    lock = frappe.cache().lock(f"{PREFIX}:fixture-lock", timeout=120)
    with lock:
        yield


def _ensure_staff(ctx):
    user = "crm.rep1@example.com"
    doc = frappe.get_doc("User", user)
    set_canonical_crm_profile(doc, "Sale")
    doc.save(ignore_permissions=True)
    department = frappe.db.get_value("CRM Department", {}, "name")
    if not department:
        department = frappe.get_doc({
            "doctype": "CRM Department", "department_name": f"{PREFIX} Admissions", "campus": ctx["campus"],
        }).insert(ignore_permissions=True).name
    staff = frappe.db.get_value("CRM Staff", {"user": user}, "name")
    if staff:
        return staff
    return frappe.get_doc({"doctype": "CRM Staff", "full_name": f"{PREFIX} Sales", "user": user, "department": department, "campus": ctx["campus"], "target": 10}).insert(ignore_permissions=True).name


def _ensure_role(role_name):
    if not frappe.db.exists("Role", role_name):
        frappe.get_doc({"doctype": "Role", "role_name": role_name, "is_custom": 1}).insert(ignore_permissions=True)


def _ensure_live_test_user(email, role):
    """Create a dedicated non-human system user with exactly its E2E role."""
    _ensure_role(role)
    if not frappe.db.exists("User", email):
        frappe.get_doc({
            "doctype": "User", "email": email, "first_name": f"{PREFIX} {role}",
            "user_type": "System User", "enabled": 1,
            "roles": [{"role": role}],
        }).insert(ignore_permissions=True)
    user = frappe.get_doc("User", email)
    managed_roles = _MANAGED_ROLE_ALIASES
    user.roles = [row for row in user.roles if row.role not in managed_roles or row.role == role]
    if not any(row.role == role for row in user.roles):
        user.append("roles", {"role": role})
    user.save(ignore_permissions=True)
    return email


def _ensure_live_test_sales_staff(ctx):
    """Give the fictional Sales identity ownership of the fictional cohort only.

    Sale has owner-scoped write access.  The live chat test therefore needs a
    matching CRM Staff record and E2E-only ownership; otherwise its bearer
    sees an empty worklist and cannot exercise the intended Sales flow.
    """
    email, role = LIVE_TEST_USERS["sales"]
    _ensure_live_test_user(email, role)
    staff = frappe.db.get_value("CRM Staff", {"user": email}, "name")
    if staff:
        frappe.db.set_value("CRM Staff", staff, "campus", ctx["campus"], update_modified=False)
        return staff
    department = frappe.db.get_value("CRM Department", {}, "name")
    if not department:
        department = frappe.get_doc({
            "doctype": "CRM Department", "department_name": f"{PREFIX} Live Test Sales", "campus": ctx["campus"],
        }).insert(ignore_permissions=True).name
    return frappe.get_doc({
        "doctype": "CRM Staff", "full_name": f"{PREFIX} Live Test Sales", "user": email,
        "department": department, "campus": ctx["campus"], "target": 10,
    }).insert(ignore_permissions=True).name


def _ensure_live_test_aggregate_staff(ctx):
	"""Create campus mappings for aggregate-only copilot identities."""
	department = frappe.db.get_value("CRM Department", {}, "name")
	if not department:
		department = frappe.get_doc({
			"doctype": "CRM Department", "department_name": f"{PREFIX} Live Test Aggregate", "campus": ctx["campus"],
		}).insert(ignore_permissions=True).name
	for role_key, label in (("marketing", "Marketing"), ("lead_sales", "Lead Sales"), ("admissions_director", "Admissions Director")):
		email, role = LIVE_TEST_USERS[role_key]
		_ensure_live_test_user(email, role)
		staff = frappe.db.get_value("CRM Staff", {"user": email}, "name")
		if staff:
			frappe.db.set_value("CRM Staff", staff, "campus", ctx["campus"], update_modified=False)
			continue
		frappe.get_doc({
			"doctype": "CRM Staff", "full_name": f"{PREFIX} Live Test {label}", "user": email,
			"department": department, "campus": ctx["campus"], "target": 10,
		}).insert(ignore_permissions=True)


def _ensure_cross_campus_staff(ctx):
	"""Create a real CRM Staff row in the negative case's campus."""
	email = "e2e.other-campus@example.test"
	role = "Sale"
	_ensure_live_test_user(email, role)
	department = frappe.db.get_value(
		"CRM Department", {"campus": ctx["campus"]}, "name"
	)
	if not department:
		department = frappe.get_doc({
			"doctype": "CRM Department",
			"department_name": f"{PREFIX} Other Campus Sales",
			"campus": ctx["campus"],
		}).insert(ignore_permissions=True).name
	staff = frappe.db.get_value("CRM Staff", {"user": email}, "name")
	if staff:
		frappe.db.set_value(
			"CRM Staff", staff,
			{"department": department, "campus": ctx["campus"]},
			update_modified=False,
		)
		return staff, email
	staff = frappe.get_doc({
		"doctype": "CRM Staff",
		"full_name": f"{PREFIX} Other Campus Sales",
		"user": email,
		"department": department,
		"campus": ctx["campus"],
		"target": 10,
	}).insert(ignore_permissions=True).name
	return staff, email


def _ensure_live_test_client():
    client_name = frappe.db.exists("OAuth Client", {"app_name": LIVE_TEST_CLIENT})
    if client_name:
        return client_name
    return frappe.get_doc({
        "doctype": "OAuth Client", "app_name": LIVE_TEST_CLIENT,
        "scopes": "all", "default_redirect_uri": "http://localhost/e2e-callback",
        "redirect_uris": "http://localhost/e2e-callback", "grant_type": "Authorization Code",
        "response_type": "Code", "skip_authorization": 1,
    }).insert(ignore_permissions=True).name


def _ensure_live_test_token(client, role_key, user):
    token_name = frappe.db.get_value(
        "OAuth Bearer Token", {"client": client, "user": user, "status": "Active"}, "name"
    )
    if token_name:
        token = frappe.get_doc("OAuth Bearer Token", token_name)
        max_expiry = now_datetime() + timedelta(seconds=_E2E_TOKEN_TTL_SECONDS + 60)
        if token.expiration_time and now_datetime() < token.expiration_time <= max_expiry:
            return token.access_token
        token.status = "Revoked"
        token.save(ignore_permissions=True)
    access_token = frappe.generate_hash(length=48)
    frappe.get_doc({
        "doctype": "OAuth Bearer Token", "client": client, "user": user, "scopes": "all",
        "access_token": access_token, "refresh_token": frappe.generate_hash(length=48),
        "expires_in": _E2E_TOKEN_TTL_SECONDS,
        "expiration_time": now_datetime() + timedelta(seconds=_E2E_TOKEN_TTL_SECONDS), "status": "Active",
    }).insert(ignore_permissions=True)
    return access_token


def _put_interaction(student, code, intent_type, importance, channel, days_ago, outcome, notes):
    summary = f"{PREFIX}-{code}: {notes[:80]}"
    interaction = frappe.get_doc({
        "doctype": "CRM Interaction", "student": student, "interaction_type": seed_demo._ensure_interaction_type(channel),
        "interaction_datetime": now_datetime() - timedelta(days=days_ago), "outcome": outcome, "summary": summary, "notes": notes,
    }).insert(ignore_permissions=True)
    # CRM Intent.importance is read-only and derived server-side from the
    # intent_type term's metadata (crm_intent.py before_validate), so it is
    # not set directly here -- _ensure_intent_type persists it on the term.
    kind = seed_demo._ensure_intent_type(intent_type, importance, f"{PREFIX} {intent_type}")
    intent = frappe.get_doc({
        "doctype": "CRM Intent", "interaction": interaction.name, "intent_type": kind,
        "intent_role": "Dominant", "polarity": "Positive", "confidence": 90, "notes": notes,
    }).insert(ignore_permissions=True)
    # The live RCM rule measures intent-record age, not interaction age.
    # Backdate only fictional E2E records so the real SLA rule is testable.
    frappe.db.set_value("CRM Intent", intent.name, "creation", now_datetime() - timedelta(days=days_ago), update_modified=False)
    return interaction.name


def _normalize_e2e_intent_timestamps(student, days_ago):
    """Keep the fictional event age stable across idempotent seed runs."""
    for intent in frappe.get_all("CRM Intent", filters={"student": student}, fields=["name", "notes"]):
        frappe.db.set_value(
            "CRM Intent", intent.name, "creation", now_datetime() - timedelta(days=days_ago), update_modified=False,
        )


def _put_student(ctx, assigned_to, item):
    code, name, status, stage_days, intent, importance, channel, interaction_days, outcome, notes = item
    email = f"e2e-fpt-2026-{code}@example.test"
    phone = f"09862026{code}" if str(code).isdigit() else "0986202699"
    existing = frappe.db.exists("CRM Student", {"email": email})
    if existing:
        frappe.db.set_value(
            "CRM Student", existing,
            {"assigned_to": assigned_to, "owner": LIVE_TEST_USERS["sales"][0], "branch": ctx["campus"], "phone": phone},
            update_modified=False,
        )
        _normalize_e2e_intent_timestamps(existing, interaction_days)
        return existing
    # CRM Student.before_insert requires the trusted student-intake service
    # boundary (crm.fcrm.student_intake) outside of a pytest run. This
    # fixture module is local-only demo data, not an external-facing intake
    # path, so it opts into that same boundary directly rather than routing
    # through the full case-key/pool resolution flow real intake requires.
    previous_intake_flag = getattr(frappe.flags, "student_intake_service", None)
    frappe.flags.student_intake_service = True
    try:
        student = frappe.get_doc({
            "doctype": "CRM Student", "student_name": f"{PREFIX}-{code} {name}", "email": email,
            "phone": phone, "enrollment_status": "Mới", "assigned_to": assigned_to,
            "owner": LIVE_TEST_USERS["sales"][0],
            "high_school": ctx["high_school"], "province": ctx["province"], "ward": ctx["ward"], "branch": ctx["campus"],
            "major": ctx["major"], "aspiration": ctx["aspiration"], "source": ctx["source"], "admission_year": ctx["admission_year"],
            "education_program": ctx["education_program"], "cohort_start_year": 2026, "cohort_end_year": 2030,
            "transcript_score": 8.2 if code in {"01", "02", "05"} else 7.1, "english_converted_score": 6.5 if code == "01" else 5.5,
            "admission_method": "Transcript Review", "notes": notes,
        }).insert(ignore_permissions=True)
    finally:
        frappe.flags.student_intake_service = previous_intake_flag
    if status != "Mới":
        student.db_set("enrollment_status", status, update_modified=False)
        record_transition(student.name, "Mới", status, occurred_at=now_datetime() - timedelta(days=stage_days), source=PREFIX)
    _put_interaction(student.name, code, intent, importance, channel, interaction_days, outcome, notes)
    if code == "07":
        _put_interaction(student.name, code, "Major Inquiry", "High", "Major View", 0, "Captured", "Đổi quan tâm sang Thiết kế đồ họa.")
    return student.name


def _reset_e2e_recommendation_lifecycle(students):
    """Remove only derived lifecycle records for this fictional cohort.

    The live acceptance suite must begin at ``new`` so it can exercise the
    genuine recommendation -> action -> outcome -> re-evaluation path on
    every rerun.  Student, intent, and interaction seed data remain stable;
    canonical actions are deleted before their recommendation parent.
    """
    recommendations = frappe.get_all(
        "CRM Recommendation",
        filters={
            "student": ["in", students],
            # Only the two recommendations owned by this fixture have the
            # REC-E2E-* aggregate namespace accepted by the agent reset API.
            # Keep system-generated recommendations for other lifecycle rules.
            "rule_key": ["in", ["e2e_capture_readiness", "e2e_capture_cross_campus"]],
        },
        pluck="name",
    )
    if not recommendations:
        return {"deleted": 0, "agent_state": _clear_agent_fixture_state([])}
    actions = frappe.get_all(
        "CRM Action", filters={"recommendation": ["in", recommendations]}, pluck="name"
    )
    aggregate_names = [*recommendations, *actions]
    event_names = frappe.get_all(
        "CRM Agent Event", filters={"aggregate_name": ["in", aggregate_names]}, pluck="name"
    )
    agent_state = _clear_agent_fixture_state(aggregate_names)
    if event_names:
        frappe.db.delete("CRM Agent Event", {"name": ["in", event_names]})
    for action in actions:
        frappe.delete_doc("CRM Action", action, ignore_permissions=True, force=True)
    for recommendation in recommendations:
        frappe.delete_doc("CRM Recommendation", recommendation, ignore_permissions=True, force=True)
    return {"deleted": len(recommendations), "agent_state": agent_state}


def _ensure_cross_campus_negative_case(ctx):
    """Create one non-worklist recommendation in a second campus.

    It is included in the synthetic reset namespace but deliberately uses a
    different rule key, so readiness still expects exactly the two positive
    capture rows. The role rehearsal proves Frappe filters this row out.
    """
    other_campus = frappe.db.exists("CRM Campus", {"campus_name": f"{PREFIX} Other Campus"})
    if not other_campus:
        other_campus = frappe.get_doc({
            "doctype": "CRM Campus", "campus_name": f"{PREFIX} Other Campus",
            "campus_code": "E2E26-OTHER", "province": ctx["province"],
        }).insert(ignore_permissions=True).name
    other_ctx = {**ctx, "campus": other_campus}
    other_staff, other_user = _ensure_cross_campus_staff(other_ctx)
    student = _put_student(
        other_ctx,
        other_staff,
        ("X", "Cross Campus", "Mới", 0, "Major Inquiry", "Medium", "Zalo Chat", 0, "Captured", f"{FIXTURE_RUN_ID}: cross-campus negative"),
    )
    # Keep the negative row assigned to a valid staff record in the other
    # campus. This makes the denial prove campus isolation rather than an
    # unmapped-owner fallback.
    frappe.db.set_value(
        "CRM Student", student, {"owner": other_user, "assigned_to": other_staff}, update_modified=False
    )
    intent = frappe.db.get_value("CRM Intent", {"student": student}, "name", order_by="creation asc")
    recommendation = frappe.db.exists(
        "CRM Recommendation", {"student": student, "rule_key": "e2e_capture_cross_campus"}
    )
    if recommendation:
        return student, recommendation
    candidate = frappe.get_doc({
        "doctype": "CRM Recommendation",
        "student": student,
        "rule_key": "e2e_capture_cross_campus",
        "source_intent_id": intent,
        "condition_version": 1,
        "priority": "low",
        "status": "new",
        "context_hash": f"{FIXTURE_RUN_ID}:cross-campus",
        "created_at": FIXTURE_CREATED_AT,
        "recommended_action": "FOLLOW_UP",
        "reason": f"{FIXTURE_RUN_ID}: cross-campus negative",
        "evidence": {"fixture_run_id": FIXTURE_RUN_ID, "negative_case": True},
    })
    candidate.run_method("autoname")
    candidate.flags.from_phase6_command = True
    candidate.insert(ignore_permissions=True)
    return student, candidate.name


def generate_capture_lifecycle() -> dict:
    """Create the fixed, idempotent recommendation set used by UTA rehearsal."""
    created: list[str] = []
    existing: list[str] = []
    for code, action, priority in CAPTURE_CASES:
        student = frappe.db.get_value("CRM Student", {"email": f"e2e-fpt-2026-{code}@example.test"}, "name")
        if not student:
            raise RuntimeError(f"{FIXTURE_RUN_ID}: missing fixture student {code}")
        intent = frappe.db.get_value("CRM Intent", {"student": student, "importance": "Very High"}, "name", order_by="creation asc")
        if not intent:
            raise RuntimeError(f"{FIXTURE_RUN_ID}: missing high-priority intent for {student}")
        candidate = frappe.get_doc({
            "doctype": "CRM Recommendation", "student": student,
            "rule_key": "e2e_capture_readiness", "source_intent_id": intent,
            "condition_version": 1, "priority": priority, "status": "new",
            "context_hash": f"{FIXTURE_RUN_ID}:{code}",
            "created_at": FIXTURE_CREATED_AT, "recommended_action": action,
            "reason": f"{FIXTURE_RUN_ID}: deterministic capture recommendation",
            "evidence": {"fixture_run_id": FIXTURE_RUN_ID, "student_code": code},
        })
        candidate.run_method("autoname")
        if frappe.db.exists("CRM Recommendation", candidate.name):
            existing.append(candidate.name)
            continue
        candidate.flags.from_phase6_command = True
        candidate.insert(ignore_permissions=True)
        created.append(candidate.name)
    return {"fixture_run_id": FIXTURE_RUN_ID, "created": created, "existing": existing}


def wait_for_capture_readiness(max_attempts: int = 10) -> dict:
    """Bounded readiness assertion with stable IDs; never capture an empty list."""
    if not isinstance(max_attempts, int) or max_attempts < 1 or max_attempts > 30:
        raise ValueError("max_attempts must be between 1 and 30")
    for _ in range(max_attempts):
        rows = frappe.get_all(
            "CRM Recommendation",
            filters={
                "rule_key": "e2e_capture_readiness",
                "context_hash": ["like", f"{FIXTURE_RUN_ID}:%"],
                "status": "new",
            },
            fields=["name", "student", "recommended_action"],
            order_by="name asc",
        )
        if len(rows) != len(CAPTURE_CASES):
            continue
        expected = {
            f"{FIXTURE_RUN_ID}:{code}": (action, priority)
            for code, action, priority in CAPTURE_CASES
        }
        actual = {
            frappe.db.get_value("CRM Recommendation", row["name"], "context_hash"): (
                row["recommended_action"],
                frappe.db.get_value("CRM Recommendation", row["name"], "priority"),
            )
            for row in rows
        }
        if actual != expected:
            continue

        original_user = frappe.session.user
        try:
            frappe.set_user(LIVE_TEST_USERS["sales"][0])
            worklist = _visible_fixture_recommendations(LIVE_TEST_USERS["sales"][0])
            worklist_ids = set(worklist)
            if worklist_ids != {row["name"] for row in rows}:
                continue

            cross_campus = frappe.get_all(
                "CRM Recommendation",
                filters={
                    "rule_key": "e2e_capture_cross_campus",
                    "context_hash": f"{FIXTURE_RUN_ID}:cross-campus",
                    "status": "new",
                },
                pluck="name",
            )
            if len(cross_campus) != 1:
                continue
            cross_campus_id = cross_campus[0]
            cross_campus_is_hidden = True
            for role_user in (
                LIVE_TEST_USERS["marketing"][0],
                LIVE_TEST_USERS["lead_sales"][0],
            ):
                frappe.set_user(role_user)
                role_worklist = {
                    "items": [
                        {"recommendation": name}
                        for name in _visible_fixture_recommendations(role_user)
                    ]
                }
                if cross_campus_id in {
                    item["recommendation"] for item in role_worklist["items"]
                }:
                    cross_campus_is_hidden = False
                    break
                cross_doc = frappe.get_doc("CRM Recommendation", cross_campus_id)
                if cross_doc.has_permission("read"):
                    cross_campus_is_hidden = False
                    break
            if not cross_campus_is_hidden:
                continue
        finally:
            frappe.set_user(original_user)
        return {
            "fixture_run_id": FIXTURE_RUN_ID,
            "ready": True,
            "recommendations": rows,
            "worklist": worklist,
        }
    raise RuntimeError(f"{FIXTURE_RUN_ID}: capture recommendations did not become ready")


def _clear_agent_fixture_state(aggregate_names: list[str]) -> dict:
    """Clear only run-correlated agent state before deleting Frappe rows.

    A configured agent endpoint is mandatory when the fixture produced outbox
    events: deleting CRM rows first would leave a retry able to re-contaminate
    the next run. A fresh namespace can proceed without agent configuration.
    """
    base_url = frappe.conf.get("crm_agents_url")
    api_key = frappe.conf.get("crm_agents_e2e_reset_api_key")
    if not base_url or not api_key:
        if not aggregate_names:
            return {"deleted_inbox": 0, "deleted_sessions": 0, "skipped": "empty_namespace"}
        raise RuntimeError("E2E reset requires crm_agents_url and crm_agents_e2e_reset_api_key")
    from crm.api.agent_events import quiesce_agent_events

    quiesce_agent_events(aggregate_names)
    # Make the producer-side quiesce visible before the agent-side reset; a
    # scheduler worker must not observe the old pending state and re-enqueue
    # an event after the distributed cleanup starts.
    frappe.db.commit()
    response = requests.post(
        f"{base_url.rstrip('/')}/api/v1/maintenance/e2e-reset",
        json={
            "aggregate_names": aggregate_names,
            "fixture_run_id": FIXTURE_RUN_ID,
            # The capture runner may add exact session/thread IDs here. Do
            # not broaden reset to every conversation owned by a fixture user.
            "session_ids": [],
            "thread_ids": [],
        },
        headers={"X-API-Key": api_key},
        timeout=10,
    )
    response.raise_for_status()
    result = response.json()
    residual = {
        key: result.get(key, 0)
        for key in (
            "inbox_remaining",
            "sessions_remaining",
            "checkpoint_remaining",
            "checkpoint_writes_remaining",
        )
        if result.get(key, 0)
    }
    if residual:
        raise RuntimeError(f"{FIXTURE_RUN_ID}: agent reset left residual state: {residual}")
    return result


def _visible_fixture_recommendations(user: str) -> list[str]:
    """Read the pre-cutover recommendation cohort under Frappe row scope.

    The public worklist now serves Task V2 rows, while this rehearsal intentionally
    validates the legacy Recommendation CAS lifecycle. Keep the permission
    assertion on Frappe's own query rather than treating the worklist DTO as an
    authorization oracle for a different record type.
    """
    original_user = frappe.session.user
    try:
        frappe.set_user(user)
        return frappe.get_all(
            "CRM Recommendation",
            filters={
                "rule_key": "e2e_capture_readiness",
                "context_hash": ["like", f"{FIXTURE_RUN_ID}:%"],
                "status": "new",
            },
            pluck="name",
            order_by="name asc",
        )
    finally:
        frappe.set_user(original_user)


def rehearse_permissioned_lifecycle() -> dict:
    """Exercise the real CAS APIs as fixture roles, never direct DB writes."""
    frappe.only_for("System Manager")
    readiness = wait_for_capture_readiness()
    rows = readiness["recommendations"]
    sales_email = LIVE_TEST_USERS["sales"][0]
    marketing_email = LIVE_TEST_USERS["marketing"][0]
    lead_sales_email = LIVE_TEST_USERS["lead_sales"][0]
    original_user = frappe.session.user
    positive_ids = {row["name"] for row in rows}
    cross_campus = frappe.get_all(
        "CRM Recommendation",
        filters={"rule_key": "e2e_capture_cross_campus", "context_hash": f"{FIXTURE_RUN_ID}:cross-campus", "status": "new"},
        pluck="name",
    )
    if len(cross_campus) != 1:
        raise RuntimeError("cross-campus negative recommendation is missing")
    cross_campus_id = cross_campus[0]

    def visible_worklist(user: str) -> dict:
        return {"items": [{"recommendation": name} for name in _visible_fixture_recommendations(user)]}

    try:
        marketing_worklist = visible_worklist(marketing_email)
        lead_sales_worklist = visible_worklist(lead_sales_email)
        expected_ids = positive_ids
        if {item["recommendation"] for item in marketing_worklist["items"]} != expected_ids:
            raise RuntimeError("Marketing could not read the campus-scoped recommendation worklist")
        if {item["recommendation"] for item in lead_sales_worklist["items"]} != expected_ids:
            raise RuntimeError("Lead Sales could not read the campus-scoped recommendation worklist")
        if cross_campus_id in {
            item["recommendation"]
            for item in (*marketing_worklist["items"], *lead_sales_worklist["items"])
        }:
            raise RuntimeError("a cross-campus recommendation leaked into an aggregate worklist")

        for user in (sales_email, marketing_email, lead_sales_email):
            frappe.set_user(user)
            cross_doc = frappe.get_doc("CRM Recommendation", cross_campus_id)
            if cross_doc.has_permission("read"):
                raise RuntimeError(
                    f"cross-campus recommendation direct-read leaked to {user}"
                )

        campus = frappe.db.get_value("CRM Staff", {"user": marketing_email}, "campus")
        for item in marketing_worklist["items"]:
            student_campus = frappe.db.get_value("CRM Student", {"name": frappe.db.get_value("CRM Recommendation", item["recommendation"], "student")}, "branch")
            if student_campus != campus:
                raise RuntimeError("Worklist returned a cross-campus recommendation")

        # Accept the ACT fixture explicitly. The worklist is ordered by the
        # recommendation name, not by action disposition, so rows[0] may be the
        # MONITOR/FOLLOW_UP case.
        accepted_row = next((row for row in rows if row.get("recommended_action") == "CALL"), None)
        if not accepted_row:
            raise RuntimeError("ACT rehearsal recommendation is missing")
        sales_recommendation = frappe.get_doc("CRM Recommendation", accepted_row["name"])
        frappe.set_user(sales_email)
        from crm.api.student_decision import transition_recommendation
        accepted = transition_recommendation(
            sales_recommendation.name,
            str(sales_recommendation.modified),
            "accepted",
        )
        if not accepted.get("action"):
            raise RuntimeError("Sales acceptance did not create CRM Action")
        action = frappe.get_doc("CRM Action", accepted["action"])
        from crm.api.student_decision import transition_action
        transition_action(
            name=action.name,
            expected_revision=action.action_revision or 1,
            status="in_progress",
            idempotency_key=f"{FIXTURE_RUN_ID}:start:{action.name}",
            correlation_id=f"{FIXTURE_RUN_ID}:start:{action.name}",
        )
        action.reload()
        outcome = transition_action(
            name=action.name,
            expected_revision=action.action_revision or 1,
            status="completed",
            idempotency_key=f"{FIXTURE_RUN_ID}:complete:{action.name}",
            correlation_id=f"{FIXTURE_RUN_ID}:complete:{action.name}",
            outcome_code="INTEREST_INCREASED",
            evidence={"fixture_run_id": FIXTURE_RUN_ID, "note": "fixture permissioned outcome"},
        )

        denied_row = next(row for row in rows if row["name"] != accepted_row["name"])
        denied_recommendation = frappe.get_doc("CRM Recommendation", denied_row["name"])
        before_status = denied_recommendation.status
        frappe.set_user(marketing_email)
        try:
            transition_recommendation(
                denied_recommendation.name,
                str(denied_recommendation.modified),
                "rejected",
                decision_reason="fixture observer denial",
            )
        except frappe.PermissionError:
            pass
        else:
            raise RuntimeError("Marketing observer unexpectedly changed a recommendation")
        denied_recommendation.reload()
        if denied_recommendation.status != before_status:
            raise RuntimeError("Denied Marketing write changed the recommendation")
        return {
            "fixture_run_id": FIXTURE_RUN_ID,
            "action_accepted": accepted["action"],
            "action": accepted["action"],
            "sales_outcome": outcome["action"],
            "marketing_denied": denied_recommendation.name,
            "cross_campus_denied": cross_campus_id,
        }
    finally:
        frappe.set_user(original_user)


def _execute(*, rehearse: bool = True):
    """Seed the cohort and, by default, run the complete permissioned rehearsal."""
    if not {"System Manager", "CRM Manager"}.intersection(frappe.get_roles()):
        frappe.throw("Only CRM managers may seed the isolated E2E cohort.", frappe.PermissionError)
    seed_demo._seed_intent_types()
    seed_demo._seed_signals()
    # Frappe enforces one active template. Reuse an already-provisioned live
    # template instead of mutating or deactivating non-E2E configuration.
    if not frappe.db.exists("CRM Score Template", {"status": "Active"}):
        seed_demo._seed_score_template()
    province = seed_demo._ensure_province()
    campus = frappe.db.exists("CRM Campus", {"campus_name": f"{PREFIX} Campus"})
    if not campus:
        campus = frappe.get_doc({
            "doctype": "CRM Campus", "campus_name": f"{PREFIX} Campus", "campus_code": "E2E26", "province": province,
        }).insert(ignore_permissions=True).name
    # Do not call seed_demo._ensure_shared_context(): its legacy status helper
    # predates CRM Term.stage_order, while this E2E cohort uses
    # the already-installed Mới/Có triển vọng/enrolled/lost stages.
    ctx = {
        "province": province,
        "ward": seed_demo._ensure_ward(province),
        "campus": campus,
        "high_school": seed_demo._ensure_high_school(province),
        "major": seed_demo._ensure_major(),
        "aspiration": seed_demo._ensure_aspiration(),
        "source": seed_demo._ensure_lead_source(),
        "admission_year": seed_demo._ensure_admission_year(),
        "education_program": seed_demo._ensure_education_program(),
    }
    staff = _ensure_live_test_sales_staff(ctx)
    _ensure_live_test_aggregate_staff(ctx)
    names = [_put_student(ctx, staff, item) for item in CASES]
    cross_campus_student, _ = _ensure_cross_campus_negative_case(ctx)
    names.append(cross_campus_student)
    _reset_e2e_recommendation_lifecycle(names)
    generator = generate_capture_lifecycle()
    _, cross_campus_recommendation = _ensure_cross_campus_negative_case(ctx)
    frappe.db.commit()
    readiness = wait_for_capture_readiness()
    rehearsal = rehearse_permissioned_lifecycle() if rehearse else None
    result = {
        "prefix": PREFIX,
        "student_count": len(names),
        "students": names,
        "cross_campus_recommendation": cross_campus_recommendation,
        **generator,
        "readiness": readiness,
        "rehearsal": rehearsal,
    }
    print(result)
    return result


@frappe.whitelist()
def execute(rehearse: bool = True):
    with _fixture_lock():
        return _execute(rehearse=rehearse)


def _reset():
    """Delete only the isolated E2E cohort and its dedicated identities.

    Run: bench --site crm.localhost execute crm.demo.seed_e2e.reset
    Shared master data and non-E2E CRM records are never removed.
    """
    student_names = frappe.get_all(
        "CRM Student",
        filters={"email": ["like", "e2e-fpt-2026-%@example.test"]},
        pluck="name",
    )
    recommendations = frappe.get_all(
        "CRM Recommendation", filters={"student": ["in", student_names]}, pluck="name"
    ) if student_names else []
    actions = frappe.get_all(
        "CRM Action", filters={"recommendation": ["in", recommendations]}, pluck="name"
    ) if recommendations else []
    aggregate_names = [*recommendations, *actions]
    event_names = frappe.get_all(
        "CRM Agent Event", filters={"aggregate_name": ["in", aggregate_names]}, pluck="name"
    ) if aggregate_names else []
    agent_state = _clear_agent_fixture_state(aggregate_names)

    if event_names:
        frappe.db.delete("CRM Agent Event", {"name": ["in", event_names]})
    for name in actions:
        frappe.delete_doc("CRM Action", name, ignore_permissions=True, force=True)
    for name in recommendations:
        frappe.delete_doc("CRM Recommendation", name, ignore_permissions=True, force=True)

    if student_names:
        interaction_names = frappe.get_all(
            "CRM Interaction", filters={"student": ["in", student_names]}, pluck="name"
        )
        if interaction_names:
            for name in frappe.get_all(
                "CRM Intent", filters={"interaction": ["in", interaction_names]}, pluck="name"
            ):
                frappe.delete_doc("CRM Intent", name, ignore_permissions=True, force=True)
            for name in interaction_names:
                frappe.delete_doc("CRM Interaction", name, ignore_permissions=True, force=True)
        for name in student_names:
            frappe.delete_doc("CRM Student", name, ignore_permissions=True, force=True)

    fixture_users = [email for email, _ in LIVE_TEST_USERS.values()]
    for name in frappe.get_all(
        "OAuth Bearer Token", filters={"user": ["in", fixture_users]}, pluck="name"
    ):
        frappe.delete_doc("OAuth Bearer Token", name, ignore_permissions=True, force=True)
    for name in frappe.get_all("CRM Staff", filters={"user": ["in", fixture_users]}, pluck="name"):
        frappe.delete_doc("CRM Staff", name, ignore_permissions=True, force=True)
    for email in fixture_users:
        if frappe.db.exists("User", email):
            frappe.delete_doc("User", email, ignore_permissions=True, force=True)
    if frappe.db.exists("OAuth Client", {"app_name": LIVE_TEST_CLIENT}):
        frappe.delete_doc(
            "OAuth Client",
            frappe.db.get_value("OAuth Client", {"app_name": LIVE_TEST_CLIENT}, "name"),
            ignore_permissions=True,
            force=True,
        )
    frappe.db.commit()
    print({"prefix": PREFIX, "deleted_students": len(student_names), "reset": True, "agent_state": agent_state})


def reset():
    with _fixture_lock():
        return _reset()


@frappe.whitelist()
def issue_live_test_tokens():
    """Return short-lived test bearer credentials only on an explicitly enabled dev site.

    It is intentionally protected by the System Manager service account and a
    site config switch; it must never be enabled in a deployed environment.
    """
    frappe.only_for("System Manager")
    if not frappe.conf.get("e2e_live_test_enabled"):
        frappe.throw("E2E live-test token issuance is disabled.", frappe.PermissionError)
    client = _ensure_live_test_client()
    tokens = {
        role_key: _ensure_live_test_token(client, role_key, _ensure_live_test_user(email, role))
        for role_key, (email, role) in LIVE_TEST_USERS.items()
    }
    frappe.db.commit()
    return tokens
