"""Idempotent fictional cohort for crm-agents live validation.

Run: bench --site crm.localhost execute crm.demo.seed_e2e.execute
"""
from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from crm.demo import seed_demo
from crm.fcrm.doctype.crm_student.enrollment_transition import record_transition

PREFIX = "E2E-FPT-2026"
LIVE_TEST_CLIENT = f"{PREFIX} Agent Client"
LIVE_TEST_USERS = {
    "sales": ("e2e.sales@example.test", "Sale"),
    "marketing": ("e2e.marketing@example.test", "Promoter-PR"),
    "lead_sales": ("e2e.lead-sales@example.test", "Team Leader"),
    "admissions_director": ("e2e.admissions-director@example.test", "Admissions Director"),
    # Deliberately unresolved by crm-agents; never make this test identity a
    # privileged System Manager account merely to prove fail-closed behavior.
    "admin": ("e2e.admin@example.test", "E2E Test Admin"),
}
_E2E_TOKEN_TTL_SECONDS = 60 * 60

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


def _ensure_staff(ctx):
    user = "crm.rep1@example.com"
    doc = frappe.get_doc("User", user)
    if not any(row.role == "Sale" for row in doc.roles):
        doc.append("roles", {"role": "Sale"})
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
    e2e_roles = {configured_role for _, configured_role in LIVE_TEST_USERS.values()}
    managed_roles = e2e_roles | ({"System Manager"} if email == LIVE_TEST_USERS["admin"][0] else set())
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
    kind = seed_demo._ensure_intent_type(intent_type, importance, f"{PREFIX} {intent_type}")
    intent = frappe.get_doc({"doctype": "CRM Intent", "interaction": interaction.name, "intent_type": kind, "intent_role": "Dominant", "polarity": "Positive", "confidence": 90, "notes": notes}).insert(ignore_permissions=True)
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
    phone = f"09862026{code}"
    existing = frappe.db.exists("CRM Student", {"email": email})
    if existing:
        frappe.db.set_value(
            "CRM Student", existing,
            {"assigned_to": assigned_to, "owner": LIVE_TEST_USERS["sales"][0], "branch": ctx["campus"], "phone": phone},
            update_modified=False,
        )
        _normalize_e2e_intent_timestamps(existing, interaction_days)
        return existing
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
    sales actions are deleted before their recommendation parent.
    """
    recommendations = frappe.get_all(
        "CRM Recommendation", filters={"student": ["in", students]}, pluck="name"
    )
    if not recommendations:
        return
    actions = frappe.get_all(
        "CRM Sales Action", filters={"recommendation": ["in", recommendations]}, pluck="name"
    )
    for action in actions:
        frappe.delete_doc("CRM Sales Action", action, ignore_permissions=True, force=True)
    for recommendation in recommendations:
        frappe.delete_doc("CRM Recommendation", recommendation, ignore_permissions=True, force=True)


@frappe.whitelist()
def execute():
    """Seed master score data and exactly ten isolated student records."""
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
    # predates CRM Enrollment Status.stage_order, while this E2E cohort uses
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
    _reset_e2e_recommendation_lifecycle(names)
    frappe.db.commit()
    print({"prefix": PREFIX, "student_count": len(names), "students": names})


def reset():
	"""Delete only the isolated E2E cohort and its dedicated identities.

	Run: bench --site crm.localhost execute crm.demo.seed_e2e.reset
	Shared master data and non-E2E CRM records are never removed.
	"""
	student_names = frappe.get_all(
		"CRM Student",
		filters={"email": ["like", "e2e-fpt-2026-%@example.test"]},
		pluck="name",
	)
	if student_names:
		recommendations = frappe.get_all(
			"CRM Recommendation", filters={"student": ["in", student_names]}, pluck="name"
		)
		if recommendations:
			actions = frappe.get_all(
				"CRM Sales Action", filters={"recommendation": ["in", recommendations]}, pluck="name"
			)
			for name in actions:
				frappe.delete_doc("CRM Sales Action", name, ignore_permissions=True, force=True)
			for name in recommendations:
				frappe.delete_doc("CRM Recommendation", name, ignore_permissions=True, force=True)

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
	print({"prefix": PREFIX, "deleted_students": len(student_names), "reset": True})


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
