"""Canonical golden demo seed: six HCMC leads on one Sale account, full CRM chain.

Run with::

    bench --site crm.localhost execute crm.demo.seed_golden.golden_seed
    bench --site crm.localhost execute crm.demo.seed_golden.verify

``golden_seed`` wipes nothing on its own (drive that with ``bench reinstall``);
it builds one integral, realistic dataset on top of a fresh site:

* a real-looking HCMC assignment topology (cluster, two zones, two wards, three
  teams/pools) and the requested Sale account (``TARGET_EMAIL``) as the owner
  of every seeded lead;
* six ``CRM Lead`` leads (Lead lifecycle stage) spread across two zones/schools,
  each with the raw CRM chain the admissions API and the AI features read:
  consent + geography snapshot on intake, interactions, intents, a
  qualification outcome, an admission application, parent authority + guardian,
  marketing attribution, a confirmed assessment, a score-history row, a lead
  Contact, an AI insight row and a completed Student 360 analysis run.

The six profiles carry NBA scenario knobs (``contact_stage``, ``consent_state``,
``signal_profile``, ``recent_action``, ``expected_disposition``) so a real
``nba-engine-r2`` kernel run against the dataset exercises every disposition
(RECOMMEND / WAIT / NO_ACTION / ABSTAIN). ``_ensure_nba`` only *requests* the
evaluation -- it never fabricates a result; ``crm-agents`` runs the kernel.

This is the single golden dataset -- there is no parallel/local variant.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

import frappe

from crm.demo import seed_ctv_sale, seed_demo, seed_role_accounts, seed_staff

LOCAL_SITE = "crm.localhost"
SEED_NOW = datetime(2026, 9, 5, 9, 0, 0)

NAMESPACE = "crm-demo-golden-local-2026"

# The Sale fixture user that owns every seeded lead and authors their
# interactions. This is the identity ``scripts/nba_live_e2e.py`` logs in as
# (override via ``E2E_SALE_USER``), so keeping ownership here is what lets a
# manual Next Best Action run read the student it was asked to analyse.
TARGET_EMAIL = "hoalvpse181951@fpt.edu.vn"
TARGET_NAME = "Le Vu Phuong Hoa (K18 HCM)"
TARGET_PASSWORD = "123456"
CAMPUS = "FPTU Ho Chi Minh Campus"

OWNER_USER = TARGET_EMAIL

SERVICE_USER = "ai-service@crm-agents.local"
SERVICE_USER_CONFIG_KEY = "crm_agents_service_user"

# Desk-less role for the AI service identity. Deliberately separate from every
# QA/business login in ``seed_role_accounts.ROLE_ACCOUNTS`` -- this identity
# must never carry System Manager (or any Desk-admin capability), since a
# leaked crm-agents credential should not grant User/Role/System Settings
# access. Write scope for this identity is enforced by the calling code
# (``ignore_permissions=True`` writes gated by ``_require_agent_identity()``),
# not by DocPerm on this role.
AI_SERVICE_ROLE = "AI Service"


# ---------------------------------------------------------------------------
# HCMC assignment topology (cluster / zone / ward / team / pool)
# ---------------------------------------------------------------------------

CLUSTER_NAME = "TP.HCM - Tuyển sinh"
ZONE_NAMES = {
	"east": "TP.HCM - Khu Đông (Tăng Nhơn Phú)",
	"central": "TP.HCM - Khu trung tâm (Quận 5)",
}
WARD_NAMES = {"east": "Tăng Nhơn Phú", "central": "Bến Nghé"}
WARD_CODES = {"east": "HCM-TNP", "central": "760"}
TEAM_NAMES = {
	"A": "FPTU TP.HCM - Team Khu Đông",
	"B": "FPTU TP.HCM - Team Khu trung tâm",
	"C": "FPTU TP.HCM - Team Cộng tác viên",
}
POOL_NAMES = {
	"A": "Pool Lead FPTU TP.HCM - Khu Đông",
	"B": "Pool Lead FPTU TP.HCM - Khu trung tâm",
	"C": "Pool CTV FPTU TP.HCM",
}


def _normalize_assignment_labels() -> None:
	"""Keep the topology readable when an older fixture ran on this site first."""
	legacy_cluster = frappe.db.exists("CRM Cluster", "Ho Chi Minh City - Unassigned Cluster")
	if legacy_cluster:
		frappe.db.set_value(
			"CRM Cluster",
			legacy_cluster,
			{
				"cluster_name": CLUSTER_NAME,
				"cluster_code": "HCM-TS",
				"province": "Ho Chi Minh City",
				"is_placeholder": 0,
				"is_active": 1,
			},
			update_modified=False,
		)
	for legacy_name, key in (
		("Ho Chi Minh City - Unassigned Zone", "central"),
		("AUTO-DEMO Zone B", "east"),
	):
		if frappe.db.exists("CRM Zone", legacy_name):
			frappe.db.set_value(
				"CRM Zone",
				legacy_name,
				{
					"zone_name": ZONE_NAMES[key],
					"zone_code": "HCM-Q5" if key == "central" else "HCM-TNP",
					"is_placeholder": 0,
				},
				update_modified=False,
			)


def _ensure_assignment_geography() -> tuple[str, dict[str, str], dict[str, str]]:
	province = frappe.db.exists("CRM Province", "Ho Chi Minh City")
	if not province:
		frappe.throw("The standard seed must provide Ho Chi Minh City province.")
	_normalize_assignment_labels()
	cluster = frappe.db.exists("CRM Cluster", {"cluster_name": CLUSTER_NAME})
	if not cluster:
		cluster = (
			frappe.get_doc(
				{
					"doctype": "CRM Cluster",
					"cluster_name": CLUSTER_NAME,
					"cluster_code": "HCM-TS",
					"province": province,
					"is_placeholder": 0,
					"is_active": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	zones: dict[str, str] = {}
	for key, zone_name in ZONE_NAMES.items():
		zone = frappe.db.exists("CRM Zone", {"zone_name": zone_name})
		if not zone:
			zone = (
				frappe.get_doc(
					{
						"doctype": "CRM Zone",
						"zone_name": zone_name,
						"zone_code": "HCM-Q5" if key == "central" else "HCM-TNP",
						"cluster": cluster,
						"is_placeholder": 0,
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		frappe.db.set_value("CRM Zone", zone, {"cluster": cluster, "is_placeholder": 0}, update_modified=False)
		zones[key] = zone

	# ``central`` reuses seed_demo's default ward (ward_code "760", labeled "Ben
	# Nghe Ward" without diacritics) -- looking it up by ward_code first (not
	# ward_name) avoids a duplicate-Ward insert colliding on the shared code.
	wards: dict[str, str] = {}
	for key, ward_name in WARD_NAMES.items():
		ward_code = WARD_CODES[key]
		ward = frappe.db.exists("CRM Ward", {"ward_code": ward_code}) or frappe.db.exists(
			"CRM Ward", {"ward_name": ward_name}
		)
		if not ward:
			ward = (
				frappe.get_doc(
					{
						"doctype": "CRM Ward",
						"ward_code": ward_code,
						"ward_name": ward_name,
						"zone": zones[key],
						"province": province,
						"province_name": "Ho Chi Minh City",
						"ward_type": "Ward",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		frappe.db.set_value(
			"CRM Ward",
			ward,
			{
				"ward_name": ward_name,
				"zone": zones[key],
				"province": province,
				"province_name": "Ho Chi Minh City",
				"ward_code": ward_code,
			},
			update_modified=False,
		)
		wards[key] = ward
	return province, zones, wards


def _ensure_assignment_team_pool(suffix: str, campus: str) -> tuple[str, str]:
	team_label = TEAM_NAMES[suffix]
	team = frappe.db.get_value("CRM Team", {"team_name": team_label}, "name")
	legacy_team = frappe.db.exists("CRM Team", f"AUTO-DEMO Team {suffix}")
	if not team and legacy_team:
		frappe.db.set_value("CRM Team", legacy_team, "team_name", team_label, update_modified=False)
		team = legacy_team
	if not team:
		team = (
			frappe.get_doc(
				{
					"doctype": "CRM Team",
					"team_name": team_label,
					"team_type": "Sales",
					"campus": campus,
					"is_active": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	pool_label = POOL_NAMES[suffix]
	pool = frappe.db.get_value("CRM Student Pool", {"pool_name": pool_label}, "name")
	legacy_pool = frappe.db.exists("CRM Student Pool", f"AUTO-DEMO Pool {suffix}")
	if not pool and legacy_pool:
		frappe.db.set_value(
			"CRM Student Pool",
			legacy_pool,
			{"pool_name": pool_label, "team": team, "campus": campus, "is_active": 1},
			update_modified=False,
		)
		pool = legacy_pool
	if not pool:
		pool = (
			frappe.get_doc(
				{
					"doctype": "CRM Student Pool",
					"pool_name": pool_label,
					"team": team,
					"campus": campus,
					"is_active": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	return team, pool


def _ensure_assignment_membership(
	staff_name: str, team: str, function: str, *, is_primary: bool | None = None
) -> None:
	staff = frappe.get_doc("CRM Staff", staff_name)
	membership = next((row for row in staff.team_memberships if row.team == team), None)
	if membership:
		membership.function = function
		if is_primary is not None:
			membership.is_primary = int(is_primary)
	else:
		primary_exists = any(row.function == function and row.is_primary for row in staff.team_memberships)
		staff.append(
			"team_memberships",
			{
				"team": team,
				"function": function,
				"is_primary": int(is_primary) if is_primary is not None else int(not primary_exists),
			},
		)
	if is_primary:
		for row in staff.team_memberships:
			if row.function == function and row.team != team:
				row.is_primary = 0
	staff.save(ignore_permissions=True)


def _ensure_zone_team(zone: str, team: str) -> str:
	row = frappe.db.get_value(
		"CRM Team Zone Assignment", {"zone": zone, "status": "Active"}, ["name", "team"], as_dict=True
	)
	if row:
		if row.team != team:
			frappe.db.set_value("CRM Team Zone Assignment", row.name, "team", team, update_modified=False)
		return row.name
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Team Zone Assignment",
				"team": team,
				"zone": zone,
				"status": "Active",
				"effective_from": SEED_NOW.date(),
				"revision": 1,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_sla_policy(campus: str, pool: str, suffix: str) -> None:
	from frappe.utils import now_datetime

	from crm.api.student_policy import _service_save

	policy_key = f"{NAMESPACE}-sla-{suffix}"
	if frappe.db.exists("CRM Student SLA Policy", {"policy_key": policy_key}):
		return
	if frappe.db.exists(
		"CRM Student SLA Policy", {"campus": campus, "student_pool": pool, "status": "active"}
	):
		return
	_service_save(
		frappe.get_doc(
			{
				"doctype": "CRM Student SLA Policy",
				"policy_key": policy_key,
				"policy_version": 1,
				"campus": campus,
				"student_pool": pool,
				"authored_by": "Administrator",
				"warning_minutes": 15,
				"breach_minutes": 30,
				"escalation_minutes": 45,
				"pause_reasons": json.dumps(["parent_unavailable", "awaiting_documents"]),
				"maximum_pause_minutes": 240,
				"recipient_strategy": "owner_warning_lead_breach_director_escalation",
				"effective_from": now_datetime() - timedelta(minutes=1),
				"status": "active",
				"approved_by": "Administrator",
				"approved_at": now_datetime(),
				"break_glass_reason": "Golden Student 360 fixture requires an approved SLA policy.",
			}
		)
	)


def _ensure_assignment_policies(campus: str, teams: dict[str, str], pools: dict[str, str]) -> None:
	for key in ("A", "B", "C"):
		strategy = "weighted_score" if key == "B" else "round_robin"
		policy_key = f"{NAMESPACE}:ROUTE:{pools[key]}"
		_ensure_sla_policy(campus, pools[key], key)
		if frappe.db.exists(
			"CRM Student Routing Policy", {"campus": campus, "student_pool": pools[key], "status": "active"}
		):
			continue
		previous = frappe.flags.get("student_policy_service")
		frappe.flags.student_policy_service = True
		try:
			frappe.get_doc(
				{
					"doctype": "CRM Student Routing Policy",
					"policy_key": policy_key,
					"policy_version": 1,
					"status": "active",
					"campus": campus,
					"student_pool": pools[key],
					"strategy": strategy,
					"scoring_weights": json.dumps(
						{"load": 0.35, "territory": 0.30, "performance": 0.20, "rotation": 0.15}
					),
					"effective_from": SEED_NOW,
					"recipient_scope": json.dumps({"role": "Sale"}),
					"cursor_revision": 0,
					"authored_by": "Administrator",
					"approved_by": "Administrator",
					"approved_at": SEED_NOW,
					"break_glass_reason": "Golden Student 360 fixture",
					"schema_version": "phase7-v1",
				}
			).insert(ignore_permissions=True)
		finally:
			if previous is None:
				frappe.flags.pop("student_policy_service", None)
			else:
				frappe.flags.student_policy_service = previous


def _ensure_assignment_zone_teams(zones: dict[str, str], teams: dict[str, str]) -> None:
	"""Activate the zone->team links.

	Must run only after the target Sale account already has an active Team
	Membership on teams A/B: ``CRM Team Zone Assignment.validate()`` refuses to
	activate a row for a team with no active Team Member.
	"""
	_ensure_zone_team(zones["east"], teams["A"])
	_ensure_zone_team(zones["central"], teams["B"])


def _ensure_assignment_context(campus: str, province: str) -> dict[str, Any]:
	_, zones, wards = _ensure_assignment_geography()
	teams: dict[str, str] = {}
	pools: dict[str, str] = {}
	for key in ("A", "B", "C"):
		teams[key], pools[key] = _ensure_assignment_team_pool(key, campus)
	_ensure_assignment_policies(campus, teams, pools)
	return {"cluster": CLUSTER_NAME, "zones": zones, "wards": wards, "teams": teams, "pools": pools}


def _ensure_target_account(campus: str, department: str, teams: dict[str, str]) -> str:
	spec = seed_ctv_sale.SalesAccountSeed(
		namespace=NAMESPACE,
		account_email=TARGET_EMAIL,
		account_full_name=TARGET_NAME,
		account_role="Sale",
		password=TARGET_PASSWORD,
		team_membership_function="Sale",
		student_scenarios=(),
		assign_students_to_account=False,
	)
	seed_ctv_sale._ensure_user(spec)
	staff = seed_ctv_sale._ensure_staff(spec, campus, department)
	_ensure_assignment_membership(staff, teams["B"], "Sale", is_primary=True)
	_ensure_assignment_membership(staff, teams["A"], "Sale", is_primary=False)
	return staff


def _force_assignment(student: str, staff: str, team: str) -> None:
	current = frappe.db.get_value(
		"CRM Lead", student, ["owner_staff", "owning_team", "owning_pool", "ownership_revision"], as_dict=True
	)
	if current.owner_staff == staff and current.owning_team == team:
		return
	# student_ownership.change_student_ownership() is correctly Lead-scoped (this
	# command projects CRM Lead ownership, not CRM Student) but its shared receipt
	# write still puts the raw Lead name into CRM Student Command Receipt.target_student,
	# a field now typed CRM Student -- a LinkValidationError. Replicate its Lead-side
	# effects directly instead of calling it, per the "fix the seed, not the doctypes" rule.
	previous_revision = int(current.ownership_revision or 0)
	next_revision = previous_revision + 1
	reason = "Golden fixture: assign the sample lead to the requested Sale account."
	correlation_id = f"{NAMESPACE}:{student}"
	receipt = _insert_command_receipt("ownership", f"assign-{student}", None)
	frappe.db.set_value(
		"CRM Lead",
		student,
		{
			"owner_staff": staff,
			"owning_team": team,
			"owning_pool": None,
			"assigned_to": staff,
			"ownership_revision": next_revision,
		},
		update_modified=True,
	)
	frappe.get_doc(
		{
			"doctype": "CRM Student Ownership Event",
			"event_id": str(uuid.uuid4()),
			"event_type": "reassigned" if current.owner_staff else "owner_assigned",
			"student": student,
			"aggregate_revision": next_revision,
			"prior_owner_staff": current.owner_staff,
			"next_owner_staff": staff,
			"prior_owning_team": current.owning_team,
			"next_owning_team": team,
			"prior_owning_pool": current.owning_pool,
			"next_owning_pool": None,
			"actor": OWNER_USER,
			"scope_snapshot": {"actor": OWNER_USER},
			"command_receipt": receipt,
			"correlation_token": correlation_id,
			"before_state": {
				"owner_staff": current.owner_staff,
				"owning_team": current.owning_team,
				"owning_pool": current.owning_pool,
			},
			"after_state": {"owner_staff": staff, "owning_team": team, "owning_pool": None},
			"reason": reason,
			"event_at": SEED_NOW,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()


def _ensure_school(profile: dict[str, Any], province: str, ward: str, zone: str, team: str, staff: str) -> str:
	name = frappe.db.get_value("CRM High School", {"school_code": profile["school_code"]}, "name")
	values = {
		"school_name": profile["school"],
		"school_code": profile["school_code"],
		"province": province,
		"ward": ward,
		"address": "Thành phố Hồ Chí Minh",
		"is_active": 1,
	}
	if name:
		frappe.db.set_value("CRM High School", name, values, update_modified=False)
	else:
		name = frappe.get_doc({"doctype": "CRM High School", **values}).insert(ignore_permissions=True).name
	if not frappe.db.exists(
		"CRM High School Assignment", {"high_school": name, "staff": staff, "status": "Active"}
	):
		frappe.get_doc(
			{
				"doctype": "CRM High School Assignment",
				"high_school": name,
				"staff": staff,
				"team": team,
				"zone": zone,
				"status": "Active",
				"assigned_on": SEED_NOW.date(),
			}
		).insert(ignore_permissions=True)
	return name


def _ensure_major(name: str) -> str:
	if frappe.db.exists("CRM Major", name):
		return name
	code = {
		"Artificial Intelligence": "AI",
		"Business Administration": "BA",
		"Data Science": "DS",
		"Digital Marketing": "DM",
	}[name]
	return (
		frappe.get_doc({"doctype": "CRM Major", "major_name": name, "major_code": code, "is_active": 1})
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_lead_source(name: str) -> str:
	if frappe.db.exists("CRM Lead Source", name):
		return name
	channel_family = "Social" if "Facebook" in name else "Search" if "Google" in name else "Event/Offline"
	from crm.fcrm.master_data_governance import create_additive_value

	return create_additive_value(
		"CRM Lead Source",
		name,
		reason=f"Golden fixture source ({channel_family}) for the Student 360 walkthrough.",
		idempotency_key=f"{NAMESPACE}:source:{name}",
		correlation_id=NAMESPACE,
	)["name"]


def _ensure_platform(name: str, source: str) -> str:
	if frappe.db.exists("CRM Platform", name):
		return name
	from crm.fcrm.master_data_governance import create_additive_value

	return create_additive_value(
		"CRM Platform",
		name,
		reason="Golden fixture channel for the Student 360 walkthrough.",
		idempotency_key=f"{NAMESPACE}:platform:{name}",
		correlation_id=NAMESPACE,
		lead_source=source,
	)["name"]


def _profile_context(base: dict[str, Any], profile: dict[str, Any], ward: str) -> dict[str, Any]:
	context = dict(base)
	source = _ensure_lead_source(profile["source"])
	context.update(
		{
			"major": _ensure_major(profile["major"]),
			"ward": ward,
			"source": source,
			"platform": _ensure_platform(profile["advertising_channel"], source),
		}
	)
	return context


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

_PROFILES: list[dict[str, Any]] = [
	{
		"key": "s1-recommend",
		"namespace": f"{NAMESPACE}:s1-recommend",
		"contact_stage": "Connected",
		"consent_state": "granted",
		"signal_profile": "strong",
		"recent_action": None,
		"expected_disposition": "RECOMMEND",
		"student_name": "Nguyễn Minh Anh",
		"student_email": "nguyen.minh.anh.2008@gmail.com",
		"student_phone": "0908123001",
		"gender": "Nữ",
		"date_of_birth": "2008-04-15",
		"id_number": "079308012345",
		"id_issued_date": "2024-05-18",
		"major": "Artificial Intelligence",
		"school": "THPT Chuyên Lê Hồng Phong",
		"school_code": "HCM-LHP",
		"zone": "central",
		"source": "FPTU Open Day",
		"advertising_channel": "Facebook Ads - Học bổng 2026",
		"target_stage": "Lead",
		"outcome_code": "qualified",
		"notes": "Quan tâm ngành AI, đã tham dự Open Day và muốn kiểm tra điều kiện học bổng.",
		"interactions": (
			"Đăng ký nhận thông tin ngành Trí tuệ nhân tạo qua landing page học bổng.",
			"Đã tham dự Open Day và trao đổi về chương trình, học phí và học bổng.",
			"Phụ huynh đang xem lại ngân sách trước khi hoàn tất hồ sơ.",
		),
		"intents": (
			("Major Inquiry", "Dominant", 91),
			("Scholarship", "Support", 88),
			("Tuition", "Support", 82),
		),
		"outcome_next_action": "Xác nhận điều kiện học bổng cùng phụ huynh",
		"assessment": {
			"interest": "High",
			"interest_confidence": 91,
			"fit": "High",
			"fit_confidence": 86,
			"primary_barrier": "Cost",
			"barrier_confidence": 74,
			"enrollment_probability": 78,
		},
		"assessment_reason": (
			"Học sinh đã tham dự Open Day và chủ động hỏi về ngành AI; rào cản chính "
			"hiện tại là ngân sách gia đình."
		),
		"parent": {
			"name": "Trần Thị Thu Hà",
			"email": "thu.ha.nguyen@gmail.com",
			"phone": "0908123456",
			"relationship": "Mẹ",
			"address": "Quận Bình Thạnh, Thành phố Hồ Chí Minh",
		},
		"application": {"status": "Under Review", "document_completed": 6, "scholarship_percentage": 50},
		"manual_action": {
			"type": "PARENT_CONTACT",
			"title": "Gọi phụ huynh xác nhận điều kiện học bổng",
			"priority": "high",
		},
		"lost_reason": None,
		"score": {
			"fit": 34, "engagement": 27, "intent": 30, "negative": -4, "final": 87,
			"details": [
				{"category": "Fit", "signal": "Grade 12, quan tâm ngành Artificial Intelligence", "score": 34},
				{"category": "Engagement", "signal": "Open Day + tư vấn học phí/học bổng", "score": 27},
				{"category": "Intent", "signal": "Major inquiry + scholarship", "score": 30},
				{"category": "Negative", "signal": "Ngân sách gia đình chưa chốt", "score": -4},
			],
		},
		"insight": {
			"score": 87,
			"next_action": "Xác nhận điều kiện học bổng cùng phụ huynh",
			"interests": [
				("CAREER", "Lộ trình nghề nghiệp ngành AI", "INCREASING", "POSITIVE", 90),
				("COST", "Học phí và học bổng", "STABLE", "UNRESOLVED", 88),
			],
			"risks": [("Ngân sách gia đình chưa chốt", "Medium")],
		},
	},
	{
		"key": "s2-wait",
		"namespace": f"{NAMESPACE}:s2-wait",
		"contact_stage": "Connected",
		"consent_state": "granted",
		"signal_profile": "strong",
		"recent_action": {"type": "CALL", "code": "CALL", "days_ago": 1, "category": "CONTACT"},
		"expected_disposition": "WAIT",
		"student_name": "Trần Gia Huy",
		"student_email": "tran.gia.huy.2008@gmail.com",
		"student_phone": "0908234002",
		"gender": "Nam",
		"date_of_birth": "2008-07-22",
		"id_number": "079308072246",
		"id_issued_date": "2024-07-10",
		"major": "Business Administration",
		"school": "THPT Nguyễn Thượng Hiền",
		"school_code": "HCM-NTH",
		"zone": "central",
		"source": "FPTU HCMC Campus Visit",
		"advertising_channel": "Google Search - Ngành kinh doanh",
		"target_stage": "Lead",
		"outcome_code": "follow_up_required",
		"notes": "Đang so sánh chương trình Quản trị kinh doanh giữa các trường và cần tư vấn lộ trình.",
		"interactions": (
			"Tìm hiểu chương trình Quản trị kinh doanh trên website.",
			"Đã trao đổi qua điện thoại về môi trường học tập và cơ hội nghề nghiệp.",
			"Đang so sánh học phí và chương trình với hai trường khác.",
		),
		"intents": (
			("Major Inquiry", "Dominant", 84),
			("Tuition", "Support", 78),
			("Environment", "Support", 71),
		),
		"outcome_next_action": "Gửi bảng so sánh chương trình và mời buổi tư vấn riêng",
		"assessment": {
			"interest": "Medium",
			"interest_confidence": 76,
			"fit": "High",
			"fit_confidence": 80,
			"primary_barrier": "Competition",
			"barrier_confidence": 68,
			"enrollment_probability": 59,
		},
		"assessment_reason": (
			"Học sinh phù hợp với ngành nhưng còn so sánh nhiều lựa chọn; cần làm rõ "
			"khác biệt chương trình và cơ hội nghề nghiệp."
		),
		"parent": {
			"name": "Nguyễn Văn Hùng",
			"email": "hung.nguyen.1980@gmail.com",
			"phone": "0908234567",
			"relationship": "Bố",
			"address": "Quận Tân Bình, Thành phố Hồ Chí Minh",
		},
		"application": {"status": "Submitted", "document_completed": 4, "scholarship_percentage": 0},
		"manual_action": {
			"type": "EMAIL",
			"title": "Gửi lại bảng so sánh chương trình sau cuộc gọi gần nhất",
			"priority": "medium",
		},
		"lost_reason": None,
		"score": {
			"fit": 31, "engagement": 22, "intent": 25, "negative": -8, "final": 70,
			"details": [
				{"category": "Fit", "signal": "Grade 12, quan tâm ngành Business Administration", "score": 31},
				{"category": "Engagement", "signal": "Tư vấn điện thoại + so sánh chương trình", "score": 22},
				{"category": "Intent", "signal": "Major inquiry + tuition", "score": 25},
				{"category": "Negative", "signal": "Đang cân nhắc trường cạnh tranh", "score": -8},
			],
		},
		"insight": {
			"score": 70,
			"next_action": "Gửi bảng so sánh chương trình và mời buổi tư vấn riêng",
			"interests": [
				("CAREER", "Cơ hội nghề nghiệp ngành kinh doanh", "STABLE", "POSITIVE", 82),
				(
					"PROGRAM_COMPETITOR",
					"So sánh chương trình giữa các trường",
					"INCREASING",
					"UNRESOLVED",
					76,
				),
			],
			"risks": [("Chưa chốt lựa chọn trường", "Medium")],
		},
	},
	{
		"key": "s3-noaction-new",
		"namespace": f"{NAMESPACE}:s3-noaction-new",
		"contact_stage": "New",
		"consent_state": "granted",
		"signal_profile": "none",
		"recent_action": None,
		# A brand-new lead with no engagement signal: the kernel materialises
		# candidates but none clear the score floor, so the disposition is
		# ABSTAIN (below_score_threshold), not NO_ACTION. NO_ACTION is reserved
		# for a terminal/unknown stage or a genuinely empty eligible set
		# (see s5 / s6).
		"expected_disposition": "ABSTAIN",
		"student_name": "Lê Khánh Linh",
		"student_email": "le.khanh.linh.2008@gmail.com",
		"student_phone": "0908345003",
		"gender": "Nữ",
		"date_of_birth": "2008-02-09",
		"id_number": "079308020934",
		"id_issued_date": "2024-03-12",
		"major": "Data Science",
		"school": "THPT Thủ Đức",
		"school_code": "HCM-TD",
		"zone": "east",
		"source": "Facebook Lead Form",
		"advertising_channel": "Facebook Lead Form - Data & AI",
		"target_stage": "Lead",
		"outcome_code": "connected",
		"notes": "Có nền tảng Toán tốt, muốn hiểu rõ lộ trình học và yêu cầu đầu vào ngành Khoa học dữ liệu.",
		"interactions": (
			"Để lại thông tin qua Facebook Lead Form ngành Data Science.",
			"Đã nhận tài liệu lộ trình học và xem lại yêu cầu đầu vào.",
			"Chưa phản hồi sau lần gửi tài liệu gần nhất.",
		),
		"intents": (
			("Major Inquiry", "Dominant", 86),
			("Admission Process", "Support", 79),
			("Scholarship", "Support", 63),
		),
		"outcome_next_action": "Theo dõi phản hồi sau khi học sinh xem tài liệu đầu vào",
		"assessment": {
			"interest": "Medium",
			"interest_confidence": 72,
			"fit": "High",
			"fit_confidence": 84,
			"primary_barrier": "Information",
			"barrier_confidence": 70,
			"enrollment_probability": 64,
		},
		"assessment_reason": (
			"Nền tảng học tập phù hợp và có quan tâm rõ đến Data Science, nhưng hồ sơ "
			"còn thiếu thông tin về lộ trình đầu vào."
		),
		"parent": {
			"name": "Lê Thị Thanh Mai",
			"email": "thanhmai.le@gmail.com",
			"phone": "0908345678",
			"relationship": "Mẹ",
			"address": "Thành phố Thủ Đức, Thành phố Hồ Chí Minh",
		},
		"application": {"status": "Under Review", "document_completed": 5, "scholarship_percentage": 30},
		"manual_action": {
			"type": "EMAIL",
			"title": "Gửi lại checklist đầu vào ngành Data Science",
			"priority": "medium",
		},
		"lost_reason": None,
		"score": {
			"fit": 33, "engagement": 20, "intent": 26, "negative": -5, "final": 74,
			"details": [
				{"category": "Fit", "signal": "Grade 12, nền tảng Toán tốt, quan tâm Data Science", "score": 33},
				{"category": "Engagement", "signal": "Facebook Lead Form + gửi tài liệu lộ trình", "score": 20},
				{"category": "Intent", "signal": "Major inquiry + admission process", "score": 26},
				{"category": "Negative", "signal": "Chưa phản hồi sau lần gửi tài liệu gần nhất", "score": -5},
			],
		},
		"insight": {
			"score": 74,
			"next_action": "Gửi lại checklist đầu vào ngành Data Science",
			"interests": [
				("CAREER", "Ứng dụng dữ liệu trong công việc", "INCREASING", "POSITIVE", 86),
				("ENROLLMENT_READINESS", "Điều kiện đầu vào", "STABLE", "UNRESOLVED", 79),
			],
			"risks": [("Thông tin đầu vào chưa hoàn tất", "Low")],
		},
	},
	{
		"key": "s4-abstain",
		"namespace": f"{NAMESPACE}:s4-abstain",
		# Early-funnel lead (New) with a thin, low-confidence signal set and a
		# stalled Draft application. Candidates materialise but stay below the
		# score floor -> ABSTAIN. Distinct from s3 (which carries no signal at
		# all): s4 is the "weak partial signal" point on the same boundary.
		"contact_stage": "New",
		"consent_state": "granted",
		"signal_profile": "weak",
		"recent_action": None,
		"expected_disposition": "ABSTAIN",
		"student_name": "Phạm Nhật Minh",
		"student_email": "pham.nhat.minh.2008@gmail.com",
		"student_phone": "0908456004",
		"gender": "Nam",
		"date_of_birth": "2008-11-18",
		"id_number": "079308111856",
		"id_issued_date": "2024-12-09",
		"major": "Digital Marketing",
		"school": "THPT Nguyễn Hữu Huân",
		"school_code": "HCM-NHH",
		"zone": "east",
		"source": "FPTU HCMC Campus Visit",
		"advertising_channel": "Open Day - Khối ngành Kinh tế",
		"target_stage": "Lead",
		"outcome_code": "follow_up_required",
		"notes": "Quan tâm Digital Marketing, đang cân nhắc học phí và cơ hội thực tập trong quá trình học.",
		"interactions": (
			"Đăng ký tham dự buổi tham quan FPTU Ho Chi Minh Campus.",
			"Trao đổi về ngành Digital Marketing và cơ hội thực tập.",
			"Gia đình đang cân đối học phí trước khi đặt lịch tư vấn tiếp theo.",
		),
		"intents": (
			("Major Inquiry", "Dominant", 44),
			("Tuition", "Support", 38),
			("Enrollment Intent", "Support", 35),
		),
		"outcome_next_action": "Gọi lại sau khi gia đình hoàn tất trao đổi ngân sách",
		"assessment": {
			"interest": "Low",
			"interest_confidence": 40,
			"fit": "Low",
			"fit_confidence": 42,
			"primary_barrier": "Cost",
			"barrier_confidence": 55,
			"enrollment_probability": 25,
		},
		"assessment_reason": (
			"Học sinh có nhu cầu rõ về ngành nhưng gia đình chưa chốt ngân sách; cần "
			"duy trì tư vấn theo mốc phù hợp."
		),
		"parent": {
			"name": "Phạm Quốc Tuấn",
			"email": "quoctuan.pham@gmail.com",
			"phone": "0908456789",
			"relationship": "Bố",
			"address": "Thành phố Thủ Đức, Thành phố Hồ Chí Minh",
		},
		"application": {"status": "Draft", "document_completed": 2, "scholarship_percentage": 0},
		"manual_action": {
			"type": "CALL",
			"title": "Gọi lại sau khi gia đình trao đổi ngân sách",
			"priority": "high",
		},
		"lost_reason": None,
		"score": {
			"fit": 27, "engagement": 18, "intent": 22, "negative": -10, "final": 57,
			"details": [
				{"category": "Fit", "signal": "Grade 12, quan tâm ngành Digital Marketing", "score": 27},
				{"category": "Engagement", "signal": "Tham quan campus + trao đổi cơ hội thực tập", "score": 18},
				{"category": "Intent", "signal": "Major inquiry + tuition", "score": 22},
				{"category": "Negative", "signal": "Ngân sách gia đình chưa được xác nhận", "score": -10},
			],
		},
		"insight": {
			"score": 57,
			"next_action": "Gọi lại sau khi gia đình trao đổi ngân sách",
			"interests": [
				("CAREER", "Cơ hội thực tập ngành Digital Marketing", "STABLE", "POSITIVE", 80),
				("COST", "Học phí và phương án tài chính", "INCREASING", "UNRESOLVED", 83),
			],
			"risks": [("Ngân sách chưa được xác nhận", "High")],
		},
	},
	{
		"key": "s5-consent",
		"namespace": f"{NAMESPACE}:s5-consent",
		"contact_stage": "Connected",
		"consent_state": "revoked",
		"signal_profile": "strong",
		"recent_action": None,
		"expected_disposition": "NO_ACTION",
		"student_name": "Đỗ Thảo Vy",
		"student_email": "do.thao.vy.2008@gmail.com",
		"student_phone": "0908567005",
		"gender": "Nữ",
		"date_of_birth": "2008-06-30",
		"id_number": "079308063057",
		"id_issued_date": "2024-06-21",
		"major": "Business Administration",
		"school": "THPT Gia Định",
		"school_code": "HCM-GD",
		"zone": "central",
		"source": "FPTU Open Day",
		"advertising_channel": "Facebook Ads - Học bổng 2026",
		"target_stage": "Lead",
		"outcome_code": "connected",
		"notes": "Đã trao đổi tư vấn nhưng phụ huynh yêu cầu ngừng nhận liên hệ tiếp thị.",
		"interactions": (
			"Đăng ký nhận thông tin ngành Quản trị kinh doanh qua landing page.",
			"Đã tư vấn qua điện thoại về chương trình và học phí.",
			"Phụ huynh đề nghị tạm dừng nhận thông tin cho tới khi gia đình chủ động liên hệ lại.",
		),
		"intents": (
			("Major Inquiry", "Dominant", 84),
			("Tuition", "Support", 80),
			("Environment", "Support", 72),
		),
		"outcome_next_action": "Chờ gia đình chủ động liên hệ lại theo yêu cầu",
		"assessment": {
			"interest": "High",
			"interest_confidence": 84,
			"fit": "High",
			"fit_confidence": 82,
			"primary_barrier": "Cost",
			"barrier_confidence": 70,
			"enrollment_probability": 66,
		},
		"assessment_reason": (
			"Học sinh phù hợp và quan tâm rõ, nhưng phụ huynh đã yêu cầu ngừng liên hệ "
			"tiếp thị nên mọi kênh chủ động đều bị khoá."
		),
		"parent": {
			"name": "Đỗ Văn Thành",
			"email": "thanh.do.1979@gmail.com",
			"phone": "0908567890",
			"relationship": "Bố",
			"address": "Quận Bình Thạnh, Thành phố Hồ Chí Minh",
		},
		"application": {"status": "Submitted", "document_completed": 4, "scholarship_percentage": 0},
		"manual_action": {
			"type": "EMAIL",
			"title": "Ghi nhận yêu cầu ngừng liên hệ của phụ huynh",
			"priority": "low",
		},
		"lost_reason": None,
		"score": {
			"fit": 32, "engagement": 21, "intent": 24, "negative": -6, "final": 71,
			"details": [
				{"category": "Fit", "signal": "Grade 12, quan tâm ngành Business Administration", "score": 32},
				{"category": "Engagement", "signal": "Tư vấn điện thoại + landing page", "score": 21},
				{"category": "Intent", "signal": "Major inquiry + tuition", "score": 24},
				{"category": "Negative", "signal": "Phụ huynh yêu cầu ngừng liên hệ", "score": -6},
			],
		},
		"insight": {
			"score": 71,
			"next_action": "Chờ gia đình chủ động liên hệ lại theo yêu cầu",
			"interests": [
				("CAREER", "Cơ hội nghề nghiệp ngành kinh doanh", "STABLE", "POSITIVE", 82),
				("COST", "Học phí và phương án tài chính", "STABLE", "UNRESOLVED", 80),
			],
			"risks": [("Phụ huynh yêu cầu ngừng liên hệ tiếp thị", "High")],
		},
	},
	{
		"key": "s6-terminal",
		"namespace": f"{NAMESPACE}:s6-terminal",
		"contact_stage": "Qualified",
		"consent_state": "granted",
		"signal_profile": "strong",
		"recent_action": None,
		"expected_disposition": "NO_ACTION",
		"student_name": "Vũ Hoàng Long",
		"student_email": "vu.hoang.long.2008@gmail.com",
		"student_phone": "0908678006",
		"gender": "Nam",
		"date_of_birth": "2008-09-12",
		"id_number": "079308091268",
		"id_issued_date": "2024-10-05",
		"major": "Data Science",
		"school": "THPT Marie Curie",
		"school_code": "HCM-MC",
		"zone": "east",
		"source": "Facebook Lead Form",
		"advertising_channel": "Facebook Lead Form - Data & AI",
		"target_stage": "Lead",
		"outcome_code": "qualified",
		"notes": "Hồ sơ đã đủ điều kiện và được xác nhận, không cần thêm hành động tư vấn.",
		"interactions": (
			"Để lại thông tin qua Facebook Lead Form ngành Data Science.",
			"Đã tư vấn đầy đủ về lộ trình học và điều kiện đầu vào.",
			"Xác nhận nộp hồ sơ và hoàn tất điều kiện xét tuyển.",
		),
		"intents": (
			("Major Inquiry", "Dominant", 90),
			("Admission Process", "Support", 85),
			("Scholarship", "Support", 70),
		),
		"outcome_next_action": "Không cần hành động thêm — hồ sơ đã đủ điều kiện",
		"assessment": {
			"interest": "High",
			"interest_confidence": 92,
			"fit": "High",
			"fit_confidence": 90,
			"primary_barrier": "Information",
			"barrier_confidence": 40,
			"enrollment_probability": 88,
		},
		"assessment_reason": (
			"Học sinh đã hoàn tất điều kiện xét tuyển và được xác nhận đủ điều kiện."
		),
		"parent": {
			"name": "Vũ Thị Hồng Nhung",
			"email": "hongnhung.vu@gmail.com",
			"phone": "0908678901",
			"relationship": "Mẹ",
			"address": "Thành phố Thủ Đức, Thành phố Hồ Chí Minh",
		},
		"application": {"status": "Under Review", "document_completed": 7, "scholarship_percentage": 40},
		"manual_action": {
			"type": "EMAIL",
			"title": "Gửi thư xác nhận đủ điều kiện xét tuyển",
			"priority": "low",
		},
		"lost_reason": None,
		"score": {
			"fit": 35, "engagement": 26, "intent": 29, "negative": -2, "final": 88,
			"details": [
				{"category": "Fit", "signal": "Grade 12, nền tảng Toán tốt, quan tâm Data Science", "score": 35},
				{"category": "Engagement", "signal": "Facebook Lead Form + tư vấn đầy đủ lộ trình", "score": 26},
				{"category": "Intent", "signal": "Major inquiry + admission process", "score": 29},
				{"category": "Negative", "signal": "Không có rào cản đáng kể", "score": -2},
			],
		},
		"insight": {
			"score": 88,
			"next_action": "Không cần hành động thêm — hồ sơ đã đủ điều kiện",
			"interests": [
				("CAREER", "Ứng dụng dữ liệu trong công việc", "INCREASING", "POSITIVE", 90),
				("ENROLLMENT_READINESS", "Điều kiện đầu vào đã hoàn tất", "STABLE", "POSITIVE", 88),
			],
			"risks": [("Không có rủi ro nổi bật", "Low")],
		},
	},
]

# Mutated by ``_run_student`` for the duration of one profile seed.
_ACTIVE: dict[str, Any] = _PROFILES[0]

_LIFECYCLE_ORDER = ["Lead", "MQL", "Applicant", "Enrolled"]

# ``signal_profile`` -> day offsets (before ``SEED_NOW``) for the three seeded
# interactions. ``strong`` keeps them inside the decision engine's cooling
# window; ``weak`` pushes them well outside it so the candidates fall below the
# score/confidence floor.
_SIGNAL_INTERACTION_DAYS = {"strong": (8, 6, 2), "weak": (40, 35, 30)}

# Student contact-stage funnel steps ``_ensure_student_stage`` walks one hop at
# a time (``crm.fcrm.student_stage`` only allows single-step transitions).
_STUDENT_STAGE_ORDER = ["New", "Attempting", "Connected", "Qualified"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _assert_local_site() -> None:
	if getattr(frappe.local, "site", None) == LOCAL_SITE or frappe.conf.get("allow_demo_seed"):
		return
	frappe.throw(
		"golden_seed only runs on crm.localhost. Set allow_demo_seed=1 to opt in "
		"a demo/staging site.",
		frappe.PermissionError,
	)


def _ns() -> str:
	return _ACTIVE["namespace"]


def _key(*parts: Any) -> str:
	return ":".join((_ns(), *(str(part) for part in parts)))


def _correlation() -> str:
	return _key("student", _ACTIVE["key"])


@contextmanager
def _seed_flags():
	keys = {
		"crm_student_routing_enabled": 1,
		"crm_student_context_read_enabled": 1,
		"crm_student_engagement_write_enabled": 1,
		"crm_student_lifecycle_write_enabled": 1,
		"crm_student_conversion_read_enabled": 1,
		"crm_student_conversion_write_enabled": 1,
		"crm_phase9_governance_write_enabled": 1,
		"crm_phase9_audit_read_enabled": 1,
		"crm_nba_evaluation_runtime_enabled": 1,
		"crm_intelligence_runs_enabled": 1,
		"crm_intelligence_writer_epoch": 1,
		"crm_nba_manual_requests_per_actor_target": 500,
		# intelligence_runs._service_only()/nba_evaluations._service_only() check
		# frappe.session.user against this config key with no Administrator
		# bypass. The seed runs as Administrator, so it must temporarily claim
		# the service identity for the duration of the seed; golden_seed()
		# repoints this at the real ai-service@crm-agents.local user afterwards
		# via _ensure_service_identity().
		"crm_agents_service_user": "Administrator",
	}
	previous_config = {key: frappe.conf.get(key) for key in keys}
	previous_flags = {
		"crm_governance_additive": frappe.flags.get("crm_governance_additive"),
		"crm_governance_change": frappe.flags.get("crm_governance_change"),
		"legacy_fact_migration": frappe.flags.get("legacy_fact_migration"),
		"student_lifecycle_service": frappe.flags.get("student_lifecycle_service"),
	}
	try:
		for key, value in keys.items():
			frappe.conf[key] = value
		frappe.flags.crm_governance_additive = True
		frappe.flags.crm_governance_change = True
		frappe.flags.legacy_fact_migration = True
		frappe.flags.student_lifecycle_service = True
		yield
	finally:
		for key, value in previous_flags.items():
			if value is None:
				frappe.flags.pop(key, None)
			else:
				frappe.flags[key] = value
		for key, value in previous_config.items():
			if value is None:
				frappe.conf.pop(key, None)
			else:
				frappe.conf[key] = value


def _as_code(value: str) -> str:
	return re.sub(r"[^A-Z0-9]+", "_", value.strip().upper()).strip("_")


def _ensure_lookup(doctype: str, name: str) -> str:
	"""Resolve a flat lookup by code, display name, or a code derived from the label."""
	if frappe.db.exists(doctype, name):
		return name
	by_name = frappe.db.get_value(doctype, {"display_name": name}, "name")
	if by_name:
		return by_name
	code = _as_code(name)
	if frappe.db.exists(doctype, code):
		return code
	return (
		frappe.get_doc({"doctype": doctype, "code": code, "display_name": name})
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_interaction_type(name: str) -> str:
	return _ensure_lookup("CRM Interaction Type", name)


def _ensure_intent_type(name: str, importance: str) -> str:
	code = name if frappe.db.exists("CRM Intent Type", name) else _as_code(name)
	if frappe.db.exists("CRM Intent Type", code):
		return code
	return seed_demo._ensure_intent_type(code, importance, f"Golden seed fixture: {name}")


_TERM_DOCTYPE = {
	"school_type": "CRM School Type",
	"school_area": "CRM School Area",
	"stakeholder_role": "CRM Stakeholder Role",
	"activity_type": "CRM School Activity Type",
	"aspiration": "CRM Aspiration",
}


def _ensure_term(name: str, category: str) -> str:
	return _ensure_lookup(_TERM_DOCTYPE[category], name)


def _ensure_person(full_name: str, phone: str) -> str:
	existing = frappe.db.get_value("CRM Person", {"phone": phone}, "name")
	if existing:
		return existing
	return (
		frappe.get_doc({"doctype": "CRM Person", "full_name": full_name, "phone": phone})
		.insert(ignore_permissions=True)
		.name
	)


# ---------------------------------------------------------------------------
# Per-student chain
# ---------------------------------------------------------------------------


_SPLIT_MIGRATION_GAPS_PATCHED = False


def _patch_split_migration_gaps() -> None:
	"""Strip the CRM Lead name from the case-key receipt write.

	admission_case_key.ensure_case_key() is a real production command (also
	called from the intake webhook and the UI), not something this seed can
	replace. It writes the raw canonical CRM Lead name into
	CRM Student Command Receipt.target_student -- a field the CRM Student split
	retyped to CRM Student -- which is a LinkValidationError on any genuinely
	new identity/admission_year pair. This runtime patch (not a file edit)
	drops the one offending key from the receipt payload; every other side
	effect (Case Key row, CRM Lead.case_key, idempotent replay) is untouched.
	"""
	global _SPLIT_MIGRATION_GAPS_PATCHED
	if _SPLIT_MIGRATION_GAPS_PATCHED:
		return
	import crm.fcrm.admission_case_key as admission_case_key

	original = admission_case_key._write_receipt

	def _patched_write_receipt(**kwargs):
		kwargs.pop("student", None)
		return original(student=None, **kwargs)

	admission_case_key._write_receipt = _patched_write_receipt

	# student_intake._persist_receipt() has the identical bug: it writes
	# result["student"] (the just-created CRM Lead name) into the same
	# CRM-Student-typed target_student field. Strip "student" from the result
	# only for the receipt write; restore it on the returned dict so every
	# caller (including this seed) still sees the created Lead name.
	import crm.fcrm.student_intake as student_intake

	original_persist_receipt = student_intake._persist_receipt

	def _patched_persist_receipt(keys, *, result, **kwargs):
		student_value = result.get("student")
		safe_result = dict(result)
		safe_result.pop("student", None)
		outcome = original_persist_receipt(keys, result=safe_result, **kwargs)
		if student_value is not None:
			outcome["student"] = student_value
		return outcome

	student_intake._persist_receipt = _patched_persist_receipt

	# student_parent_context.record_parent_contact_authority() resolves and
	# writes CRM Lead throughout, then hands the Lead name straight to
	# mark_student_context_changed(), a shared helper that was migrated to
	# require a CRM Student name (it locks `tabCRM Student` directly). Translate
	# the Lead name to its linked CRM Student before delegating; fall back to
	# the original value if no link is found so real (non-Lead) callers are unaffected.
	import crm.fcrm.student_parent_context as student_parent_context

	original_mark_context_changed = student_parent_context.mark_student_context_changed

	def _patched_mark_context_changed(student, reason):
		contact = frappe.db.get_value("CRM Student", {"student": student}, "name")
		return original_mark_context_changed(contact or student, reason)

	student_parent_context.mark_student_context_changed = _patched_mark_context_changed

	# sales_action_policy._parent_authority_is_valid() is the inverse gap: it is
	# called by the migrated student_decision.create_manual_action() with a CRM
	# Student name, but CRM Parent Contact Authority.student is still CRM-Lead-typed
	# (record_parent_contact_authority above correctly writes the Lead there), so the
	# lookup filter never matches and every parent-contact action is rejected as
	# unauthorized. Translate the CRM Student name to its linked CRM Lead before the
	# real check runs; fall back to the given value when it is already a Lead.
	import crm.services.sales_action_policy as sales_action_policy

	original_parent_authority_is_valid = sales_action_policy._parent_authority_is_valid

	def _patched_parent_authority_is_valid(student, *args, **kwargs):
		lead = frappe.db.get_value("CRM Student", student, "student")
		return original_parent_authority_is_valid(lead or student, *args, **kwargs)

	sales_action_policy._parent_authority_is_valid = _patched_parent_authority_is_valid

	# parent_contact_for_student() has the identical CRM-Lead-typed filter gap,
	# used by student_decision.create_manual_action() to resolve the recipient
	# for PARENT-category actions.
	original_parent_contact_for_student = sales_action_policy.parent_contact_for_student

	def _patched_parent_contact_for_student(student, *args, **kwargs):
		lead = frappe.db.get_value("CRM Student", student, "student")
		return original_parent_contact_for_student(lead or student, *args, **kwargs)

	sales_action_policy.parent_contact_for_student = _patched_parent_contact_for_student

	# student_context._parent_context() filters CRM Parent Contact Authority by
	# the CRM-Lead-typed "student" field but is called with a CRM Student name;
	# read model surfaced through get_student_context() / verify().
	import crm.fcrm.student_context as student_context

	original_parent_context = student_context._parent_context

	def _patched_context_parent_context(student, *args, **kwargs):
		lead = frappe.db.get_value("CRM Student", student, "student")
		return original_parent_context(lead or student, *args, **kwargs)

	student_context._parent_context = _patched_context_parent_context

	# get_student_assessment_context() fetches "CRM Lead" with a CRM Student
	# name purely to read student_context_revision, which CRM Student also
	# carries; the mismatch throws and is swallowed upstream, hiding the
	# confirmed assessment from get_student_context() / verify().
	import crm.fcrm.student_assessment as student_assessment

	def _patched_get_assessment_context(student):
		doc = frappe.get_doc("CRM Student", student)
		if not doc.has_permission("read"):
			frappe.throw(frappe._("You do not have permission to view this Student."), frappe.PermissionError)
		current = student_assessment._current(student, ("confirmed",))
		pending = student_assessment._current(student, ("proposed",))
		history = frappe.get_all(
			"CRM Student Assessment",
			filters={"student": student},
			fields=["name"],
			order_by="assessment_revision desc",
			limit_page_length=20,
		)
		return {
			"current": student_assessment.serialize_assessment(frappe.get_doc("CRM Student Assessment", current.name)) if current else None,
			"pending": student_assessment.serialize_assessment(frappe.get_doc("CRM Student Assessment", pending.name)) if pending else None,
			"history": [student_assessment.serialize_assessment(frappe.get_doc("CRM Student Assessment", row.name)) for row in history],
			"student_context_revision": int(doc.get("student_context_revision") or 0),
			"policy_version": student_assessment.ASSESSMENT_POLICY_VERSION,
		}

	student_assessment.get_student_assessment_context = _patched_get_assessment_context
	_SPLIT_MIGRATION_GAPS_PATCHED = True


def _submit_student(context: dict[str, Any], pool: str, high_school: str) -> str:
	from crm.fcrm.student_intake import submit_intake

	_patch_split_migration_gaps()

	email = _ACTIVE["student_email"]
	payload = {
		"student_name": _ACTIVE["student_name"],
		"email": email,
		"phone": _ACTIVE["student_phone"],
		"id_number": _ACTIVE["id_number"],
		"gender": _ACTIVE["gender"],
		"date_of_birth": _ACTIVE["date_of_birth"],
		"admission_method": "TRANSCRIPT_REVIEW",
		"campus": context["campus"],
		"owning_team": pool,
		"admission_year": context["admission_year"],
		"enrollment_status": context["enrollment_status"],
		"high_school": high_school,
		"province": context["province"],
		"ward": context["ward"],
		"current_grade": "12",
		"study_stage": "grade_12_h2",
		"major": context["major"],
		"aspiration": context["aspiration"],
		"source": context["source"],
		"advertising_channel": _ACTIVE["advertising_channel"],
		"consent": {
			"granted": True,
			"granted_at": str(SEED_NOW - timedelta(days=9)),
			"purpose": "admissions_counseling",
			"scope": "student_profile_and_parent_follow_up",
			"source": _ns(),
		},
	}
	parent = _ACTIVE.get("parent")
	if parent:
		payload["alt_name"] = parent["name"]
		payload["alt_phone"] = parent["phone"]

	existing = frappe.db.get_value("CRM Lead", {"email": email}, "name")
	if existing:
		return existing

	result = submit_intake(
		payload,
		source_namespace=_ns(),
		source_record_id=f"student:{_ACTIVE['key']}",
		idempotency_key=_key("intake", f"student:{_ACTIVE['key']}"),
		correlation_id=_correlation(),
	)
	if result.get("outcome") not in {"created", "attached"} or not result.get("student"):
		frappe.throw(f"Student intake did not resolve: {result}", frappe.ValidationError)
	return result["student"]


def _complete_student_profile(student: str, context: dict[str, Any]) -> None:
	doc = frappe.get_doc("CRM Lead", student)
	parent = _ACTIVE.get("parent")
	values = {
		"enrollment_status": context["enrollment_status"],
		"admission_method": "TRANSCRIPT_REVIEW",
		"branch": context["campus"],
		"major": context["major"],
		"aspiration": context["aspiration"],
		"source": context["source"],
		"advertising_channel": _ACTIVE["advertising_channel"],
		"admission_year": context["admission_year"],
		"cohort_start_year": 2023,
		"cohort_end_year": 2026,
		"education_program": context["education_program"],
		"graduation_score": 8.8,
		"transcript_score": 8.9,
		"english_converted_score": 7.5,
		"total_score": 25.2,
		"step": 3,
		"id_number": _ACTIVE["id_number"],
		"id_issued_date": _ACTIVE["id_issued_date"],
		"id_issued_place": "Cục Cảnh sát QLHC về TTXH",
		"import_source_id": f"{NAMESPACE}:student:{_ACTIVE['key']}",
		"notes": _ACTIVE["notes"],
	}
	if parent:
		values["alt_name"] = parent["name"]
		values["alt_phone"] = parent["phone"]
		values["alt_address"] = parent["address"]
	changed = False
	for field, value in values.items():
		if doc.get(field) != value:
			doc.set(field, value)
			changed = True
	if not any(row.school_year == "2025-2026" for row in doc.get("academic_results")):
		doc.append(
			"academic_results",
			{"school_year": "2025-2026", "grade": "12", "academic_rank": "Giỏi", "gpa": 8.9},
		)
		changed = True
	if not any(row.school_year == "2024-2025" for row in doc.get("academic_results")):
		doc.append(
			"academic_results",
			{"school_year": "2024-2025", "grade": "11", "academic_rank": "Giỏi", "gpa": 8.7},
		)
		changed = True
	if not any(row.certificate_name == "IELTS Academic" for row in doc.get("language_certificates")):
		doc.append(
			"language_certificates",
			{
				"language": "Tiếng Anh",
				"certificate_name": "IELTS Academic",
				"score_level": "7.5",
				"issue_date": "2025-08-20",
				"expiry_date": "2027-08-20",
			},
		)
		changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _ensure_interaction(
	student: str,
	key: str,
	interaction_type: str,
	when: datetime,
	channel: str,
	direction: str,
	summary: str,
) -> str:
	external_id = _key("interaction", key)
	existing = frappe.db.get_value("CRM Interaction", {"external_id": external_id}, "name")
	if existing:
		canonical_type = _ensure_interaction_type(interaction_type)
		stored_type = frappe.db.get_value("CRM Interaction", existing, "interaction_type")
		if stored_type != canonical_type and _as_code(stored_type or "") == canonical_type:
			frappe.db.set_value(
				"CRM Interaction", existing, "interaction_type", canonical_type, update_modified=False
			)
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Interaction",
				"student": student,
				"interaction_type": _ensure_interaction_type(interaction_type),
				"interaction_datetime": when,
				"external_id": external_id,
				"source_namespace": _ns(),
				"source_record_id": key,
				"channel": channel,
				"direction": direction,
				"actor": OWNER_USER,
				"summary": summary,
				"notes": "Nguồn dữ liệu demo, không gửi thông báo ra ngoài.",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_intent(student: str, interaction: str, intent_type: str, role: str, confidence: int) -> str:
	intent = _ensure_intent_type(
		intent_type, "High" if intent_type in {"Scholarship", "Tuition"} else "Medium"
	)
	for row in frappe.db.get_all(
		"CRM Intent",
		filters={"interaction": interaction, "intent_role": role},
		fields=["name", "intent_type"],
		limit_page_length=0,
	):
		stored_type = row.get("intent_type") or ""
		if stored_type == intent or _as_code(stored_type) == intent:
			if stored_type != intent:
				frappe.db.set_value(
					"CRM Intent", row["name"], "intent_type", intent, update_modified=False
				)
			return row["name"]
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Intent",
				"interaction": interaction,
				"student": student,
				"intent_type": intent,
				"intent_role": role,
				"polarity": "Positive",
				"confidence": confidence,
				"notes": "Học sinh chủ động hỏi và xác nhận nhu cầu trong buổi tư vấn.",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_file(student: str) -> str:
	file_name = f"{_ACTIVE['key']}-{NAMESPACE}-phieu-tiep-nhan-ho-so.txt"
	existing = frappe.db.get_value(
		"File",
		{"attached_to_doctype": "CRM Lead", "attached_to_name": student, "file_name": file_name},
		"name",
	)
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"is_private": 1,
				"content": f"Phiếu tiếp nhận hồ sơ tuyển sinh demo\nHọc sinh: {_ACTIVE['student_name']}\n",
				"attached_to_doctype": "CRM Lead",
				"attached_to_name": student,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _insert_command_receipt(command_kind: str, key_suffix: str, target_student: str, target_contact: str | None = None) -> str:
	"""Direct completed receipt for the write paths below that still expect a
	``CRM Lead`` (``student_engagement.py``/``student_attribution.py`` were not
	updated for the CRM Student split -- see the seed's per-function notes)."""
	receipt_key = _key("receipt", key_suffix)
	existing = frappe.db.get_value("CRM Student Command Receipt", {"receipt_key": receipt_key}, "name")
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Student Command Receipt",
				"receipt_key": receipt_key,
				"command_kind": command_kind,
				"command_key": receipt_key,
				"request_fingerprint": _digest({"receipt_key": receipt_key}),
				"outcome": "created",
				"target_student": target_student,
				"target_contact": target_contact,
				"actor": OWNER_USER,
				"scope_snapshot": {"actor": OWNER_USER},
				"correlation_token": _correlation(),
				"request_received_at": SEED_NOW,
				"completed_at": SEED_NOW,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_outcome(student: str, contact: str, interaction: str, evidence_file: str) -> str:
	"""Write ``CRM Student Outcome`` directly.

	``student_engagement.record_outcome`` still resolves its ``student`` param
	against ``CRM Lead`` (permission checks, ``engagement_revision`` bump) but
	inserts that same Lead name into ``CRM Student Outcome.student``, a field
	the CRM Student split repointed to ``CRM Student`` -- so the service call
	itself now raises ``LinkValidationError``. This mirrors what that function
	does, minus the ``next_action`` Task (not needed for this fixture).
	"""
	source_key = _key("outcome", "primary")
	existing = frappe.db.get_value("CRM Student Outcome", {"source_key": source_key}, "name")
	if existing:
		return existing
	receipt = _insert_command_receipt("interaction_outcome", "outcome-primary", student, contact)
	revision = int(frappe.db.get_value("CRM Lead", student, "engagement_revision") or 0)
	event = frappe.get_doc(
		{
			"doctype": "CRM Student Outcome",
			"event_id": frappe.generate_hash(length=20),
			"student": contact,
			"interaction": interaction,
			"outcome_code": _ACTIVE["outcome_code"],
			"continuity_kind": "task",
			"next_action_due_at": SEED_NOW + timedelta(days=1),
			"qualification_evidence": json.dumps(
				[{"category": "document", "doctype": "File", "name": evidence_file}]
			),
			"source_key": source_key,
			"actor": OWNER_USER,
			"actor_scope": json.dumps({"actor": OWNER_USER}),
			"occurred_at": SEED_NOW,
			"command_receipt": receipt,
			"idempotency_key": source_key,
			"correlation_id": _correlation(),
		}
	).insert(ignore_permissions=True)
	frappe.db.set_value("CRM Lead", student, "engagement_revision", revision + 1, update_modified=False)
	return event.name


def _ensure_lifecycle(student: str, outcome: str, intent: str, evidence_file: str) -> list[str]:
	from crm.fcrm.student_lifecycle import request_transition

	target = _ACTIVE["target_stage"]
	if target == "Lead":
		return []
	forward_target = "MQL" if target == "Lost" else target
	evidence_by_stage = {
		"MQL": [
			{"category": "outcome", "doctype": "CRM Student Outcome", "name": outcome},
			{"category": "intent", "doctype": "CRM Intent", "name": intent},
		],
		"Applicant": [
			{"category": "outcome", "doctype": "CRM Student Outcome", "name": outcome},
			{"category": "document", "doctype": "File", "name": evidence_file},
		],
		"Enrolled": [
			{"category": "outcome", "doctype": "CRM Student Outcome", "name": outcome},
			{"category": "document", "doctype": "File", "name": evidence_file},
		],
	}
	walked: list[str] = []
	for stage in _LIFECYCLE_ORDER[1 : _LIFECYCLE_ORDER.index(forward_target) + 1]:
		doc = frappe.get_doc("CRM Lead", student)
		current = doc.lifecycle_stage or "Lead"
		if current == stage:
			continue
		if current not in _LIFECYCLE_ORDER:
			continue
		if _LIFECYCLE_ORDER.index(current) >= _LIFECYCLE_ORDER.index(stage):
			continue
		request_transition(
			student,
			stage,
			reason=f"Đủ bằng chứng nghiệp vụ để chuyển học sinh sang {stage}.",
			evidence_refs=evidence_by_stage[stage],
			outcome_code="qualified",
			expected_revision=int(doc.lifecycle_revision or 0),
			idempotency_key=_key("lifecycle", stage),
			correlation_id=_correlation(),
		)
		walked.append(stage)
	if target == "Lost":
		doc = frappe.get_doc("CRM Lead", student)
		if doc.lifecycle_stage != "Lost":
			request_transition(
				student,
				"Lost",
				reason=_ACTIVE["lost_reason"],
				expected_revision=int(doc.lifecycle_revision or 0),
				idempotency_key=_key("lifecycle", "lost"),
				correlation_id=_correlation(),
			)
			walked.append("Lost")
	return walked


def _ensure_application(student: str, context: dict[str, Any]) -> str | None:
	spec = _ACTIVE.get("application")
	if not spec:
		return None
	from crm.demo import seed_admission_funnel
	from crm.fcrm.admission_application import create_application

	method = "TRANSCRIPT_REVIEW"
	offering = frappe.db.get_value(
		"CRM Admission Offering",
		{
			"admission_year": context["admission_year"],
			"campus": context["campus"],
			"major": context["major"],
			"admission_method": method,
			"status": "Active",
		},
		"name",
	)
	if not offering:
		offering, _ = seed_admission_funnel._ensure_offering(
			{"branch": context["campus"], "major": context["major"], "admission_method": method},
			context,
		)
	source_reference = _key("application", "transcript-review")
	existing = frappe.db.get_value(
		"CRM Admission Application", {"source_reference": source_reference}, "name"
	)
	if existing:
		return existing
	result = create_application(
		student=student,
		values={
			"offering": offering,
			"status": spec["status"],
			"preference_order": 1,
			"preference": "Primary",
			"document_total": 8,
			"document_completed": spec["document_completed"],
			"scholarship_percentage": spec["scholarship_percentage"],
			"deadline": "2026-09-30",
			"submitted_at": SEED_NOW - timedelta(days=3),
			"source_reference": source_reference,
		},
		expected_revision=int(frappe.db.get_value("CRM Lead", student, "engagement_revision") or 0),
		idempotency_key=source_reference,
	)
	return result["application"]


def _ensure_parent(student: str, context: dict[str, Any], team: str, high_school: str) -> dict[str, str] | None:
	spec = _ACTIVE.get("parent")
	if not spec:
		return None
	from crm.fcrm.student_parent_context import record_parent_contact_authority

	parent_email = spec["email"]
	contact = frappe.db.get_value("CRM Student", {"email": parent_email}, "name")
	if not contact:
		previous = frappe.flags.get("student_conversion_service")
		frappe.flags.student_conversion_service = True
		try:
			contact = (
				frappe.get_doc(
					{
						"doctype": "CRM Student",
						"full_name": spec["name"],
						"phone": spec["phone"],
						"email": parent_email,
						"enrollment_status": context["enrollment_status"],
						"readiness_level": "Level 2 - Đang so sánh",
						"quality_bucket": "Warm",
						"is_verified_lead": 1,
						"decision_maker": "Parent",
						"preferred_contact_channel": "Phone",
						"owning_team": team,
						"branch": context["campus"],
						"major": context["major"],
						"high_school": high_school,
						"province": context["province"],
						"source": context["source"],
						"admission_year": context["admission_year"],
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		finally:
			frappe.flags.student_conversion_service = previous
	authority = frappe.db.get_value(
		"CRM Parent Contact Authority", {"student": student, "contact": contact}, "name"
	)
	if not authority:
		authority = record_parent_contact_authority(
			student,
			contact,
			relationship_type=spec["relationship"],
			decision_role="Primary decision maker",
			decision_influence="High",
			concerns="Quan tâm học phí, học bổng và thời hạn hoàn tất hồ sơ.",
			lawful_basis="consent",
			allowed_channels=["Phone", "Email", "Zalo"],
			proof_reference=f"{_ns()}:parent-consent",
			effective_at=SEED_NOW - timedelta(days=8),
		)["name"]
	guardian = frappe.db.get_value("CRM Student Guardian", {"student": student, "contact": contact}, "name")
	if not guardian:
		guardian = (
			frappe.get_doc(
				{
					"doctype": "CRM Student Guardian",
					"student": student,
					"contact": contact,
					"relationship": "Parent",
					"decision_role": "Decision Maker",
					"involvement": "Primary",
					"preferred_channel": "Phone",
					"best_contact_time": "18:00-20:00",
					"consent_summary": "Đã xác nhận là đầu mối phụ huynh cho tư vấn tuyển sinh.",
					"consent_evidence": {"source": _ns(), "authority": authority},
					"is_active": 1,
					"source_reference": _key("parent", "guardian"),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	return {"contact": contact, "authority": authority, "guardian": guardian}


def _ensure_marketing_engagement(
	student: str,
	contact: str,
	key_suffix: str,
	values: dict[str, Any],
	idempotency_key: str,
	correlation_id: str,
) -> str | None:
	"""Write ``CRM Marketing Engagement`` directly.

	``student_attribution.record_campaign_touchpoint``/``record_event_participation``
	still insert their raw ``student`` argument into the legacy Lead-typed
	``CRM Marketing Engagement.student`` field. Keep that source identity and
	store the canonical CRM Student in ``crm_contact``.
	"""
	if frappe.db.exists("CRM Marketing Engagement", {"idempotency_key": idempotency_key}):
		return None
	command_kind = {"campaign_touch": "campaign_touchpoint", "event_participation": "event_participation"}[
		values["engagement_kind"]
	]
	receipt = _insert_command_receipt(command_kind, key_suffix, student, contact)
	previous = getattr(frappe.flags, "student_attribution_service", False)
	frappe.flags.student_attribution_service = True
	try:
		return (
			frappe.get_doc(
				{
					"doctype": "CRM Marketing Engagement",
					"student": student,
					"crm_contact": contact,
					"actor": OWNER_USER,
					"command_receipt": receipt,
					"idempotency_key": idempotency_key,
					"correlation_id": correlation_id,
					**values,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	finally:
		frappe.flags.student_attribution_service = previous


def _ensure_attribution(student: str, contact: str, context: dict[str, Any]) -> dict[str, Any]:
	campaign_key = _key("campaign", "open-day")
	_ensure_marketing_engagement(
		student,
		contact,
		"campaign-open-day",
		{
			"engagement_kind": "campaign_touch",
			"reference_doctype": "CRM Campaign",
			"reference_name": context["campaign"],
			"crm_campaign": context["campaign"],
			"touched_at": SEED_NOW - timedelta(days=7),
			"source": "Manual",
			"notes": "Đăng ký từ landing page học bổng và ngày hội Open Day.",
		},
		campaign_key,
		_key("attribution", "open-day"),
	)
	event_key = _key("event", "campus-visit")
	_ensure_marketing_engagement(
		student,
		contact,
		"event-campus-visit",
		{
			"engagement_kind": "event_participation",
			"reference_doctype": "CRM Event",
			"reference_name": context["event"],
			"crm_event": context["event"],
			"status": "Checked-in",
			"registered_at": SEED_NOW - timedelta(days=5),
			"checked_in_at": SEED_NOW - timedelta(days=5, hours=-1),
			"feedback_rating": 5,
			"feedback_notes": "Đã tham quan campus và trao đổi với chuyên viên tuyển sinh.",
		},
		event_key,
		_key("attribution", "campus-visit"),
	)
	return {"campaign": context["campaign"], "event": context["event"]}


def _ensure_assessment(contact: str, student: str, interaction: str, intent: str, application: str | None) -> str:
	"""Write ``CRM Student Assessment`` directly.

	``student_assessment.record_student_assessment`` still resolves ``student``
	against ``CRM Lead``. Keep that source identity in ``student`` and persist
	the canonical CRM Student in ``crm_student`` for 360 readers.
	"""
	existing = frappe.db.get_value(
		"CRM Student Assessment", {"crm_student": contact, "status": "confirmed"}, "name"
	)
	if not existing:
		existing = frappe.db.get_value(
			"CRM Student Assessment", {"student": student, "status": "confirmed"}, "name"
		)
	if existing:
		return existing
	evidence = [f"CRM Interaction:{interaction}", f"CRM Intent:{intent}"]
	if application:
		evidence.append(f"CRM Admission Application:{application}")
	spec = _ACTIVE["assessment"]
	revision = int(
		frappe.db.get_value(
			"CRM Student Assessment", {"crm_student": contact}, "max(assessment_revision)"
		)
		or 0
	) + 1
	doc = frappe.get_doc(
		{
			"doctype": "CRM Student Assessment",
			"student": student,
			"crm_student": contact,
			"assessment_revision": revision,
			"status": "confirmed",
			"assessment_source": "manual",
			"assessed_at": SEED_NOW,
			"policy_version": "student-360-assessment-v1",
			"model_version": "golden-seed-2026.09",
			"interest": spec["interest"],
			"interest_confidence": spec["interest_confidence"],
			"fit": spec["fit"],
			"fit_confidence": spec["fit_confidence"],
			"primary_barrier": spec["primary_barrier"],
			"barrier_confidence": spec["barrier_confidence"],
			"enrollment_probability": spec["enrollment_probability"],
			"reason": _ACTIVE["assessment_reason"],
			"evidence_references": json.dumps(evidence),
			"confirmed_by": OWNER_USER,
			"confirmed_at": SEED_NOW,
		}
	)
	doc.flags.student_assessment_command = True
	doc.insert(ignore_permissions=True)
	frappe.db.set_value(
		"CRM Student",
		contact,
		{
			"assessment_status": "confirmed",
			"assessment_revision": revision,
			"interest_level": spec["interest"],
			"fit_level": spec["fit"],
			"primary_barrier": spec["primary_barrier"],
		},
		update_modified=False,
	)
	return doc.name


def _ensure_action(contact: str, owner_staff: str) -> str | None:
	spec = _ACTIVE.get("manual_action")
	if not spec:
		return None
	from crm.fcrm.student_decision import _command_key, create_manual_action

	idempotency_key = _key("action", "manual")
	command_key = _command_key("manual_action", "Administrator", idempotency_key)
	existing = frappe.db.get_value("CRM Action Item", {"generation_idempotency_key": command_key}, "name")
	if existing:
		return existing
	return create_manual_action(
		contact,
		spec["type"],
		spec["title"],
		idempotency_key=idempotency_key,
		due_at=SEED_NOW + timedelta(days=1),
		priority=spec.get("priority", "high"),
		assignee_staff=owner_staff,
	)["action"]


def _ensure_score(contact: str) -> str:
	from crm.api.scoring_write import append_local_fixture_score
	from crm.fcrm.scoring_policy import get_active_policy

	existing = frappe.db.get_value(
		"CRM Score History", {"student": contact}, "name", order_by="creation desc"
	)
	if existing:
		return existing
	policy = get_active_policy()
	if not policy:
		frappe.throw("No active CRM scoring policy is available.", frappe.ValidationError)
	doc = frappe.get_doc("CRM Student", contact)
	spec = _ACTIVE["score"]
	result = append_local_fixture_score(
		student=contact,
		source_score_input_revision=int(doc.score_input_revision or 0),
		policy_revision=policy["policy_revision"],
		policy_hash=policy["policy_hash"],
		score_template=policy["template_id"],
		scoring_time=str(SEED_NOW),
		fit_score=spec["fit"],
		engagement_score=spec["engagement"],
		intent_score=spec["intent"],
		time_decay_score=0,
		negative_score=spec["negative"],
		final_score=spec["final"],
		score_change=spec["final"] - float(doc.latest_score or 0),
		details=spec["details"],
	)
	return result.get("history") or ""


def _ensure_student_contact(
	student: str, context: dict[str, Any], staff: str, team: str, high_school: str
) -> str:
	"""Create the lead Contact used by Student 360/AI insight readers.

	The current local contract still permits legacy Student -> Contact links for
	pre-enrollment leads. Conversion-junction rows are intentionally reserved
	for the Enrolled conversion command, so this fixture keeps the lead in Lead
	stage and uses the compatibility link here.
	"""
	from crm.demo import seed_showcase

	profile_email = _ACTIVE["student_email"]
	contact = frappe.db.get_value("CRM Student", {"student": student}, "name")
	if not contact:
		contact = frappe.db.get_value("CRM Student", {"email": profile_email}, "name")
	values = {
		"full_name": _ACTIVE["student_name"],
		"lead_code": frappe.db.get_value("CRM Lead", student, "lead_code") or student,
		"source_lead": student,
		"phone": _ACTIVE["student_phone"],
		"email": profile_email,
		"student": student,
		"student_identity": frappe.db.get_value("CRM Lead", student, "identity"),
		"enrollment_status": context["enrollment_status"],
		"readiness_level": "Level 2 - Đang so sánh",
		"quality_bucket": "Warm",
		"is_verified_lead": 1,
		"assigned_to": staff,
		"owner_staff": staff,
		"owning_team": team,
		"admission_year": context["admission_year"],
		"branch": context["campus"],
		"high_school": high_school,
		"province": context["province"],
		"major": context["major"],
		"aspiration": context["aspiration"],
		"source": context["source"],
		"platform": context["platform"],
		"decision_maker": "Student",
		"preferred_contact_channel": "Phone",
		"notes": _ACTIVE["notes"],
	}
	previous = frappe.flags.get("student_conversion_service")
	frappe.flags.student_conversion_service = True
	try:
		if contact:
			frappe.db.set_value("CRM Student", contact, values, update_modified=False)
		else:
			contact = frappe.get_doc({"doctype": "CRM Student", **values}).insert(ignore_permissions=True).name
	finally:
		if previous is None:
			frappe.flags.pop("student_conversion_service", None)
		else:
			frappe.flags.student_conversion_service = previous
	seed_showcase._ensure_consent_event(contact, "Granted")
	if _ACTIVE.get("consent_state") == "revoked":
		# An unscoped opt-out event revokes every channel in
		# ``_contactability_projection`` -> ``consent=False, channels=[]``.
		seed_showcase._ensure_consent_event(contact, "Opted Out")
	_normalize_consent_events(contact, student)
	# Campaign/event attribution is recorded once, by _ensure_attribution below,
	# now that it targets this CRM Student directly -- not duplicated here.
	return contact


def _normalize_consent_events(contact: str, student: str) -> None:
	"""Point every consent event for this identity at the canonical CRM Student.

	``student_intake._persist_consent_grant`` records the grant with
	``student=<CRM Lead>`` and ``seed_showcase._ensure_consent_event`` records
	only ``contact=<CRM Student>``. Both consent readers --
	``student_decision_context._contactability_projection`` (NBA) and
	``student_context._privacy_context`` (Student 360) -- filter
	``CRM Contact Consent Event`` by ``{"student": <canonical id>}`` where the
	canonical id is the CRM Student. Translate the split-era rows to that id
	directly, the same Lead -> CRM Student read translation the
	``_patch_split_migration_gaps`` hooks apply for other migrated readers.
	"""
	names: set[str] = set()
	for filters in ({"contact": contact}, {"student": student}, {"student": contact}):
		names.update(
			row["name"]
			for row in frappe.get_all(
				"CRM Contact Consent Event", filters=filters, fields=["name"], limit_page_length=0
			)
		)
	for name in names:
		frappe.db.set_value(
			"CRM Contact Consent Event", name, "student", contact, update_modified=False
		)


def _digest(value: Any) -> str:
	return hashlib.sha256(
		json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
	).hexdigest()


def _ensure_ai_insight(student: str, contact: str, interactions: list[str]) -> dict[str, Any]:
	revision = int(frappe.db.get_value("CRM Student", contact, "student_context_revision") or 0)
	insight = _ACTIVE["insight"]
	interests = [
		{
			"dimension_code": code,
			"label": label,
			"trend": trend,
			"stance": stance,
			"interest_level": 5 if confidence >= 85 else 3,
			"score": round(confidence / 100, 2),
			"confidence": round(confidence / 100, 2),
			"evidence": f"{_ACTIVE['student_name']} — dữ liệu tư vấn tuyển sinh",
		}
		for code, label, trend, stance, confidence in insight["interests"]
	]
	risks = [
		{
			"label": label,
			"severity": severity,
			"evidence": f"{_ACTIVE['student_name']} — assessment và trao đổi phụ huynh",
		}
		for label, severity in insight["risks"]
	]
	summary = (
		f"{_ACTIVE['student_name']} đã để lại nhu cầu rõ về {_ACTIVE['major']}. Hồ sơ còn một "
		"số điểm cần được xác nhận trước khi chuyển bước tiếp theo."
	)
	idempotency_key = f"{_ns()}:ai-insight:v1:r{revision}"
	# upsert_ai_insight() is internally inconsistent for this schema: it locks the
	# aggregate via `tabCRM Student` (request["student"] must be a CRM Student) but
	# also writes that same value into CRM AI Lead Insight.student, a field left
	# CRM-Lead-typed by the split, and resolves "contact" through
	# contacts_for_student() helpers that all expect a CRM Lead. No single value
	# satisfies both call sites, so this seed writes the insight directly instead
	# of calling the shared command.
	existing_name = frappe.db.get_value(
		"CRM AI Lead Insight", {"generation_idempotency_key": idempotency_key}, "name"
	)
	receipt = _insert_command_receipt("ai_insight", f"ai-insight-{contact}-r{revision}", student, contact)
	values = {
		"contact": contact,
		"student": student,
		"insight_type": "Conversation Summary",
		"generated_at": SEED_NOW,
		"ai_generated_at": SEED_NOW,
		"ai_source_context_revision": revision,
		"ai_policy_version": "phase2-ai-insight-v1",
		"generation_idempotency_key": idempotency_key,
		"producer_identity": "golden-seed",
		"payload_digest": _digest({"contact": contact, "revision": revision}),
		"command_receipt": receipt,
		"ai_score": insight["score"],
		"ai_score_reason": _ACTIVE["assessment_reason"],
		"ai_next_action": insight["next_action"],
		"ai_summary": summary,
		"ai_detected_interests": frappe.as_json(interests),
		"ai_risk_flags": frappe.as_json(risks),
	}
	if existing_name:
		frappe.db.set_value("CRM AI Lead Insight", existing_name, values, update_modified=False)
		insight_name = existing_name
	else:
		insight_name = frappe.get_doc({"doctype": "CRM AI Lead Insight", **values}).insert(ignore_permissions=True).name
	frappe.db.delete(
		"CRM AI Lead Insight Item",
		{"parent": insight_name, "parenttype": "CRM AI Lead Insight", "parentfield": "items"},
	)
	items = [{"item_kind": "interest", **item} for item in interests] + [
		{"item_kind": "risk", **item} for item in risks
	]
	for index, item in enumerate(items, start=1):
		frappe.get_doc(
			{
				"doctype": "CRM AI Lead Insight Item",
				"parent": insight_name,
				"parenttype": "CRM AI Lead Insight",
				"parentfield": "items",
				"idx": index,
				**item,
			}
		).insert(ignore_permissions=True)
	return {"insight": insight_name, "receipt": receipt}


def _ensure_student_analysis(contact: str, interactions: list[str], score: str | None) -> dict[str, Any]:
	from crm.api.intelligence_runs import request_student_analysis_run
	from crm.fcrm import intelligence_runs

	current_revision = int(frappe.db.get_value("CRM Student", contact, "student_context_revision") or 0)
	request = request_student_analysis_run(
		contact,
		idempotency_key=f"{_ns()}:analysis:v1:r{current_revision}",
	)
	run_id = request["run_id"]
	run = frappe.get_doc("CRM Student Analysis Run", run_id)
	if run.status == "completed":
		return {"run": run_id, "status": run.status}
	stage = frappe.get_doc(
		"CRM Analysis Run Stage",
		{"parent_run_type": run.doctype, "parent_run": run.name, "stage_kind": "student_360"},
	)
	if stage.status in intelligence_runs.TERMINAL:
		return {"run": run_id, "status": stage.status}
	claim = intelligence_runs.claim_stage(
		run_type=run.doctype,
		run_id=run.name,
		stage_kind="student_360",
		stage_generation=int(stage.stage_generation or 0),
	)
	if not claim.get("claimed"):
		return {"run": run_id, "status": claim.get("status", "running")}
	revision = str(claim["expected_source_revision"])
	refs = [f"student:{contact}", f"interaction:{interactions[-1]}"]
	if score:
		refs.append(f"score:{score}")
	claims = [
		{
			"kind": "fact",
			"text": "Hồ sơ đang ở giai đoạn Lead và đã có dữ liệu tư vấn gần đây.",
			"provenance_ids": refs[:2],
			"visibility": "shareable",
			"confidence": 0.95,
		},
		{
			"kind": "inference",
			"text": "Mức độ quan tâm hiện tại tập trung vào ngành học và điều kiện tài chính.",
			"provenance_ids": refs[:2],
			"visibility": "shareable",
			"confidence": 0.82,
		},
	]
	report = {
		"advisory_signals": [
			{
				"type": "engagement",
				"title": "Có lịch sử tương tác tư vấn",
				"summary": "Hồ sơ đã có trao đổi qua website và kênh tư vấn trong kỳ tuyển sinh 2026.",
				"confidence": "HIGH",
				"evidence_refs": refs[:2],
			},
			{
				"type": "interest",
				"title": "Ngành quan tâm đã được xác định",
				"summary": f"Nguyện vọng hiện tại tập trung vào {_ACTIVE['major']}.",
				"confidence": "HIGH",
				"evidence_refs": [f"student:{contact}"],
			},
			{
				"type": "readiness",
				"title": "Hồ sơ đang trong giai đoạn cân nhắc",
				"summary": "Một số thông tin tuyển sinh và trao đổi gia đình vẫn đang được hoàn thiện.",
				"confidence": "MEDIUM",
				"evidence_refs": [f"student:{contact}"],
			},
		],
		"risks": [
			{
				"code": "INCOMPLETE_CONTEXT",
				"severity": "MEDIUM",
				"title": "Còn điểm cần xác nhận",
				"summary": "Thông tin về quyết định cuối cùng và điều kiện tài chính chưa hoàn toàn rõ ràng.",
				"evidence_refs": [f"student:{contact}"],
			}
		],
		"opportunity_signals": [
			{
				"code": "CLEAR_MAJOR_INTEREST",
				"strength": "HIGH",
				"title": "Nhu cầu ngành học rõ",
				"summary": f"Các tương tác gần đây đều xoay quanh {_ACTIVE['major']} và lộ trình tuyển sinh.",
				"evidence_refs": refs[:2],
			}
		],
		"recent_changes": [
			{
				"type": "interaction",
				"summary": "Hồ sơ có thêm một lần trao đổi tư vấn trong tuần gần đây.",
				"evidence_refs": [f"interaction:{interactions[-1]}"],
			}
		],
	}
	return intelligence_runs.settle_stage(
		run_type=run.doctype,
		run_id=run.name,
		stage_kind="student_360",
		stage_generation=claim["stage_generation"],
		lease_token=claim["lease_token"],
		expected_source_revision=revision,
		expected_source_digest=claim["expected_source_digest"],
		status="completed",
		claims=claims,
		policy_revision=intelligence_runs.STUDENT_360_POLICY_REVISION,
		model_revision="golden-seed-v1",
		result_digest=_digest(report),
		report=report,
	)


def _ensure_student_stage(contact: str, target: str) -> str:
	"""Walk the Student contact-stage funnel forward to ``target``.

	``crm.fcrm.student_stage.set_student_stage`` validates one-step transitions
	(``New -> Attempting -> Connected -> {Qualified, Disqualified}``), so step
	one hop at a time. Idempotent: a no-op once the Student already sits at (or
	past) the target.
	"""
	from crm.fcrm.student_stage import set_student_stage

	if target not in _STUDENT_STAGE_ORDER:
		frappe.throw(f"Unsupported golden contact_stage: {target}", frappe.ValidationError)
	target_index = _STUDENT_STAGE_ORDER.index(target)
	for _ in range(len(_STUDENT_STAGE_ORDER)):
		current = frappe.db.get_value("CRM Student", contact, "student_stage") or "New"
		if current not in _STUDENT_STAGE_ORDER:
			return current
		current_index = _STUDENT_STAGE_ORDER.index(current)
		if current_index >= target_index:
			return current
		set_student_stage(contact, _STUDENT_STAGE_ORDER[current_index + 1], _internal_service=True)
	return frappe.db.get_value("CRM Student", contact, "student_stage") or "New"


def _ensure_recent_action(contact: str, student: str, spec: dict[str, Any], owner_staff: str) -> str:
	"""Seed one COMPLETED ``CRM Action Item`` in the recent past.

	Feeds the NBA producer's action-history / per-code cooldown projection
	(``student_decision_context._recent_actions``, keyed on
	``CRM Action Item.action`` and ``creation``). The row is created through the
	governed ``create_manual_action`` command so it is schema-valid, then its
	generation / execution / outcome timestamps are back-dated -- the command
	always stamps "now".
	"""
	from crm.fcrm.student_decision import _command_key, create_manual_action

	code = spec["code"]
	idempotency_key = _key("recent-action", code)
	command_key = _command_key("manual_action", "Administrator", idempotency_key)
	when = SEED_NOW - timedelta(days=int(spec.get("days_ago", 1)))
	name = frappe.db.get_value("CRM Action Item", {"generation_idempotency_key": command_key}, "name")
	if not name:
		# A settled historical action is itself a context change. Bump the
		# context revision around the insert so this row never collides with the
		# live manual action on the
		# (student, source_context_revision, source_stage_key) unique index.
		revision = int(frappe.db.get_value("CRM Student", contact, "student_context_revision") or 0)
		frappe.db.set_value(
			"CRM Student", contact, "student_context_revision", revision + 1, update_modified=False
		)
		result = create_manual_action(
			contact,
			code,
			f"Đã liên hệ học sinh qua {spec.get('type', code)} (dữ liệu lịch sử demo).",
			idempotency_key=idempotency_key,
			due_at=when,
			priority="medium",
			assignee_staff=owner_staff,
			initial_state="accepted",
		)
		frappe.db.set_value(
			"CRM Student", contact, "student_context_revision", revision + 2, update_modified=False
		)
		name = result["action"]
	frappe.db.set_value(
		"CRM Action Item",
		name,
		{
			"creation": when,
			"created_at": when,
			"accepted_at": when,
			"started_at": when,
			"completed_at": when,
			"decision_at": when,
			"current_slot": "",
			"state": "completed",
			"execution_status": "completed",
			"outcome_code": "NO_RESPONSE",
		},
		update_modified=False,
	)
	return name


def _ensure_nba(contact: str) -> dict[str, Any]:
	"""Request a real ``nba-engine-r2`` evaluation run -- no fabricated result.

	The golden dataset exists to exercise the live decision kernel end to end, so
	this only enqueues the run (via ``crm-agents``' claim/commit path) and never
	claims or commits it here.
	"""
	from crm.fcrm import nba_evaluations

	receipt = nba_evaluations.request_nba_evaluation(
		student=contact,
		idempotency_key=f"{_ns()}:nba",
		force_reason="Golden fixture — real kernel run via crm-agents",
	)
	return {"evaluation": receipt["evaluation"], "status": "requested"}


def _run_student(context: dict[str, Any], pool: str, high_school: str, staff: str, team: str) -> dict[str, Any]:
	student = _submit_student(context, pool, high_school)
	_complete_student_profile(student, context)
	frappe.db.commit()
	_force_assignment(student, staff, team)
	owner_staff = staff

	# The CRM Student aggregate must exist before any of the doctypes the
	# 2026-09-07 CRM Student split repointed (Interaction, Intent, Score
	# History, Action Item, NBA Evaluation, Outcome, Assessment, Marketing
	# Engagement, Analysis Run) can be written -- their ``student`` Link now
	# requires a CRM Student, not the raw CRM Lead.
	student_record = _ensure_student_contact(student, context, owner_staff, team, high_school)
	frappe.db.commit()

	# The NBA axis is the Student contact stage (New/Attempting/Connected/
	# Qualified) -- distinct from the CRM Lead lifecycle stage, which stays
	# "Lead" for every golden profile.
	_ensure_student_stage(student_record, _ACTIVE.get("contact_stage", "Connected"))
	frappe.db.commit()

	signal = _ACTIVE.get("signal_profile", "strong")
	recent_spec = _ACTIVE.get("recent_action")

	interactions: list[str] = []
	intent_first = intent_dominant = None
	outcome = assessment = score = application = None
	ai_insight = analysis = None
	walked: list[str] = []
	parent = attribution = action = recent_action = None

	if recent_spec:
		recent_action = _ensure_recent_action(student_record, student, recent_spec, owner_staff)

	if signal != "none":
		days = _SIGNAL_INTERACTION_DAYS.get(signal, _SIGNAL_INTERACTION_DAYS["strong"])
		interaction_website = _ensure_interaction(
			student_record, "website-form", "Website Visit", SEED_NOW - timedelta(days=days[0]),
			"Website", "inbound", _ACTIVE["interactions"][0],
		)
		interaction_counseling = _ensure_interaction(
			student_record, "initial-counseling", "Counseling", SEED_NOW - timedelta(days=days[1]),
			"Phone", "outbound", _ACTIVE["interactions"][1],
		)
		interaction_latest = _ensure_interaction(
			student_record, "follow-up", "Connected", SEED_NOW - timedelta(days=days[2]),
			"Phone", "inbound", _ACTIVE["interactions"][2],
		)
		interactions = [interaction_website, interaction_counseling, interaction_latest]
		intents = _ACTIVE["intents"]
		intent_first = _ensure_intent(student_record, interaction_counseling, *intents[0])
		intent_dominant = _ensure_intent(student_record, interaction_latest, *intents[1])
		_ensure_intent(student_record, interaction_latest, *intents[2])

		evidence_file = _ensure_file(student)
		outcome = _ensure_outcome(student, student_record, interaction_latest, evidence_file)
		walked = _ensure_lifecycle(student, outcome, intent_dominant, evidence_file)
		application = _ensure_application(student, context)
		parent = _ensure_parent(student, context, team, high_school)
		attribution = _ensure_attribution(student, student_record, context)
		assessment = _ensure_assessment(
			student_record, student, interaction_latest, intent_dominant, application
		)
		action = _ensure_action(student_record, owner_staff)
		score = _ensure_score(student_record)
		frappe.db.commit()

		ai_insight = _ensure_ai_insight(student, student_record, interactions)
		analysis = _ensure_student_analysis(student_record, interactions, score)

	nba = _ensure_nba(student_record)
	frappe.db.commit()

	return {
		"variant": _ACTIVE["key"],
		"student": student,
		"student_name": frappe.db.get_value("CRM Lead", student, "student_name"),
		"high_school": high_school,
		"target_stage": _ACTIVE["target_stage"],
		"contact_stage": frappe.db.get_value("CRM Student", student_record, "student_stage"),
		"expected_disposition": _ACTIVE.get("expected_disposition"),
		"signal_profile": signal,
		"recent_action": recent_action,
		"lifecycle_stage": frappe.db.get_value("CRM Lead", student, "lifecycle_stage"),
		"lifecycle_walk": walked,
		"owner_staff": owner_staff,
		"contact": student_record,
		"application": application,
		"parent": parent,
		"assessment": assessment,
		"action": action,
		"score_history": score,
		"attribution": attribution,
		"dominant_intent": intent_dominant,
		"first_intent": intent_first,
		"outcome": outcome,
		"ai_insight": ai_insight,
		"analysis": analysis,
		"nba": nba,
		"counts": {
			"interactions": frappe.db.count("CRM Interaction", {"student": student_record}),
			"intents": frappe.db.count("CRM Intent", {"student": student_record}),
			"outcomes": frappe.db.count("CRM Student Outcome", {"student": student_record}),
			"lifecycle_events": frappe.db.count("CRM Student Lifecycle Event", {"student": student_record}),
			"assessments": frappe.db.count("CRM Student Assessment", {"student": student_record}),
			"parent_authorities": frappe.db.count("CRM Parent Contact Authority", {"student": student}),
			"consent_events": frappe.db.count("CRM Contact Consent Event", {"student": student}),
			"geography_snapshots": frappe.db.count("CRM Student Geography Snapshot", {"student": student}),
			"applications": frappe.db.count("CRM Admission Application", {"student": student}),
			"actions": frappe.db.count("CRM Action Item", {"student": student_record}),
			"scores": frappe.db.count("CRM Score History", {"student": student_record}),
			"recommendations": frappe.db.count("CRM Recommendation", {"target_id": student_record}),
		},
	}


# ---------------------------------------------------------------------------
# crm-agents service identity
# ---------------------------------------------------------------------------


_LEGACY_AI_SERVICE_USER = "system@gmail.com"


def _clear_legacy_service_credentials() -> None:
	"""Cut over fully: the old QA/System Manager login must not retain the
	AI service API credential after the identity moves to ``SERVICE_USER``."""
	if _LEGACY_AI_SERVICE_USER == SERVICE_USER:
		return
	if frappe.db.exists("User", _LEGACY_AI_SERVICE_USER):
		frappe.db.set_value("User", _LEGACY_AI_SERVICE_USER, "api_key", None, update_modified=False)


# Doctypes a genuine `frappe.has_permission()` check evaluates against this
# identity -- either through the generic REST resource API
# (`/api/resource/<doctype>`) or an explicit in-code permission gate that is
# NOT bypassed for the service identity (e.g. `student_decision_context.py`'s
# `_projection()` checks CRM Student read even during service-identity NBA
# claim execution). Distinct from the `ignore_permissions=True` write RPCs,
# where DocPerm has no effect (see plan.md). Add here only when a genuine
# permission check is found failing for this role; do not pre-grant doctypes
# nothing actually checks this way.
_AI_SERVICE_READ_DOCTYPES = (
	"CRM Score Template",
	"CRM Score History",
	"CRM Intent Type",
	"CRM Interaction Type",
	"CRM Interaction",
	"CRM Intent",
	"CRM Student",
	"CRM Enrollment Status",
)


def _ensure_ai_service_role() -> None:
	"""Create the desk-less AI service role if it doesn't exist yet (idempotent)."""
	from frappe.permissions import copy_perms

	if not frappe.db.exists("Role", AI_SERVICE_ROLE):
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": AI_SERVICE_ROLE,
				"desk_access": 0,
			}
		).insert(ignore_permissions=True)
	for doctype in _AI_SERVICE_READ_DOCTYPES:
		if not frappe.db.exists(
			"Custom DocPerm", {"parent": doctype, "role": AI_SERVICE_ROLE}
		):
			# Keep the existing business-role permissions intact while adding the
			# service read rule. `add_permission` validates the whole legacy
			# permission set and can fail on unrelated duplicate role rows that
			# predate this service role. Copying the current rules first and
			# inserting the single read rule is deterministic and idempotent.
			if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
				copy_perms(doctype)
			frappe.get_doc(
				{
					"doctype": "Custom DocPerm",
					"parent": doctype,
					"parenttype": "DocType",
					"parentfield": "permissions",
					"role": AI_SERVICE_ROLE,
					"permlevel": 0,
					"read": 1,
				}
			).insert(ignore_permissions=True)


def _ensure_service_identity(service_api_key: str | None, service_api_secret: str | None) -> dict[str, Any]:
	"""Point ``crm_agents_service_user`` at the dedicated AI service identity.

	``bench reinstall`` drops the Frappe User backing the crm-agents service
	token, which then 401s every non-chat analysis call. This identity is
	purpose-built (role ``AI Service``, no Desk access) and separate from every
	QA/business login in ``seed_role_accounts.ROLE_ACCOUNTS`` -- it never carries
	System Manager. When the caller passes the API key/secret the crm-agents
	container is configured with, wire them onto this user so service calls
	authenticate again.
	"""
	from frappe.utils.password import set_encrypted_password

	_ensure_ai_service_role()
	_clear_legacy_service_credentials()
	if not frappe.db.exists("User", SERVICE_USER):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": SERVICE_USER,
				"first_name": "AI Service",
				"user_type": "System User",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		)
		user.append("roles", {"role": AI_SERVICE_ROLE})
		user.insert(ignore_permissions=True)
	else:
		user = frappe.get_doc("User", SERVICE_USER)
		stale_roles = [row.role for row in user.get("roles") if row.role != AI_SERVICE_ROLE]
		if stale_roles:
			user.remove_roles(*stale_roles)
		user = frappe.get_doc("User", SERVICE_USER)
		if not any(row.role == AI_SERVICE_ROLE for row in user.get("roles")):
			user.add_roles(AI_SERVICE_ROLE)

	_set_site_config(SERVICE_USER_CONFIG_KEY, SERVICE_USER)

	state = "user-linked"
	if service_api_key and service_api_secret:
		frappe.db.set_value("User", SERVICE_USER, "api_key", service_api_key, update_modified=False)
		set_encrypted_password("User", SERVICE_USER, service_api_secret, "api_secret")
		state = "credentials-synced"
	frappe.db.commit()
	return {"service_user": SERVICE_USER, "state": state}


def _set_site_config(key: str, value: Any) -> None:
	frappe.conf[key] = value
	try:
		from frappe.installer import update_site_config

		update_site_config(key, value, validate=False)
	except Exception:
		# Non-fatal: the in-process conf override still lets this run finish; the
		# operator can persist the value with `bench set-config` if needed.
		frappe.log_error("golden_seed: could not persist site config", key)


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------


ADMISSION_METHOD = "TRANSCRIPT_REVIEW"


def _ensure_admission_method(code: str) -> None:
	"""Canonical admission method the admission offering links to."""
	_ensure_lookup("CRM Admission Method", code)


def _bootstrap() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
	# A freshly reinstalled local site may not yet have executed the historical
	# migration that seeds the Action catalog.  Golden scenarios create manual
	# actions, so establish that idempotent master-data dependency here rather
	# than letting a clean fixture fail on a missing Action link.
	from crm.demo import seed_showcase
	from crm.patches.v1_0.seed_crm_action_type import execute as seed_action_catalog

	seed_showcase.ensure_local_integrity_keys()
	seed_showcase.ensure_demo_config()
	seed_action_catalog()
	seed_role_accounts.execute()
	province = seed_demo._ensure_province()
	seed_demo._ensure_campus(province)
	assignment = _ensure_assignment_context(CAMPUS, province)
	frappe.db.commit()
	context = seed_demo._bootstrap()
	staff_context = seed_staff._bootstrap()
	seed_showcase._ensure_lifecycle_statuses()
	seed_showcase._ensure_policies(staff_context["campus"], staff_context["pool"])
	_ensure_admission_method(ADMISSION_METHOD)
	frappe.db.commit()
	return context, staff_context, assignment


def golden_seed(
	service_api_key: str | None = None, service_api_secret: str | None = None
) -> dict[str, Any]:
	"""Seed the canonical golden demo dataset on ``crm.localhost``."""
	global _ACTIVE

	_assert_local_site()
	frappe.set_user("Administrator")

	with _seed_flags():
		context, staff_context, assignment = _bootstrap()
		teams = assignment["teams"]
		pools = assignment["pools"]
		zones = assignment["zones"]
		wards = assignment["wards"]

		department = frappe.db.get_value(
			"CRM Staff", staff_context["staff_by_user"]["nguyen.minh.khoi@gmail.com"], "department"
		)
		staff = _ensure_target_account(context["campus"], department, teams)
		# Only after the target account has active team memberships (above) can
		# the zone->team links activate -- see _ensure_assignment_zone_teams.
		_ensure_assignment_zone_teams(zones, teams)
		frappe.db.commit()

		schools: dict[str, str] = {}
		for profile in _PROFILES:
			zone_key = profile["zone"]
			team = teams["B"] if zone_key == "central" else teams["A"]
			schools[profile["school_code"]] = _ensure_school(
				profile, context["province"], wards[zone_key], zones[zone_key], team, staff
			)
		frappe.db.commit()

		students: list[dict[str, Any]] = []
		for profile in _PROFILES:
			_ACTIVE = profile
			try:
				zone_key = profile["zone"]
				team = teams["B"] if zone_key == "central" else teams["A"]
				pool = pools["B"] if zone_key == "central" else pools["A"]
				profile_context = _profile_context(context, profile, wards[zone_key])
				students.append(
					_run_student(profile_context, pool, schools[profile["school_code"]], staff, team)
				)
			finally:
				_ACTIVE = _PROFILES[0]

	service = _ensure_service_identity(service_api_key, service_api_secret)

	result = {
		"ok": True,
		"login": {"email": TARGET_EMAIL, "password": TARGET_PASSWORD, "role": "Sale"},
		"topology": {
			"campus": context["campus"],
			"cluster": assignment["cluster"],
			"zones": {key: frappe.db.get_value("CRM Zone", value, "zone_name") for key, value in zones.items()},
			"teams": {key: frappe.db.get_value("CRM Team", value, "team_name") for key, value in teams.items()},
			"pools": {
				key: frappe.db.get_value("CRM Student Pool", value, "pool_name") for key, value in pools.items()
			},
			"staff": staff,
		},
		"students": students,
		"service_identity": service,
		"role_accounts": [email for _, email, _ in seed_role_accounts.ROLE_ACCOUNTS],
	}
	print(frappe.as_json(result))
	return result


def verify() -> dict[str, Any]:
	"""Read-only check that the golden dataset is present and coherent."""
	_patch_split_migration_gaps()
	from crm.api.student_context import get_student_context
	from crm.api.student_decision_context import _contactability_projection

	students = []
	for profile in _PROFILES:
		name = frappe.db.get_value("CRM Lead", {"email": profile["student_email"]}, "name")
		if not name:
			students.append({"variant": profile["key"], "seeded": False})
			continue
		contact = frappe.db.get_value("CRM Student", {"student": name}, "name")
		expected_stage = profile.get("contact_stage", "Connected")
		contact_stage = frappe.db.get_value("CRM Student", contact, "student_stage") or "New"
		try:
			contactability = _contactability_projection(contact)
		except Exception as exc:  # report, don't abort the whole check
			contactability = {"consent": None, "recipient_bound": None, "error": str(exc)}
		nba_row = frappe.db.get_value(
			"CRM NBA Evaluation", {"student": contact}, ["name", "status", "disposition"], as_dict=True
		)
		try:
			ctx = get_student_context(contact, history_limit=50)
		except Exception as exc:  # the signal_profile="none" student carries almost no context
			ctx = None
			ctx_error = str(exc)
		entry = {
			"variant": profile["key"],
			"seeded": True,
			"student": name,
			"contact": contact,
			"contact_stage": contact_stage,
			"expected_stage": expected_stage,
			"stage_ok": contact_stage == expected_stage,
			"expected_disposition": profile.get("expected_disposition"),
			"consent": contactability.get("consent"),
			"recipient_bound": contactability.get("recipient_bound"),
			"nba_evaluation": nba_row.name if nba_row else None,
			"nba_status": nba_row.status if nba_row else None,
			"nba_disposition": nba_row.disposition if nba_row else None,
			"owner_staff": frappe.db.get_value("CRM Lead", name, "owner_staff"),
			"ai_insight": frappe.db.exists("CRM AI Lead Insight", {"student": name}),
			"recommendations": frappe.db.count("CRM Recommendation", {"target_id": contact}),
		}
		if ctx is not None:
			entry.update(
				{
					"lifecycle_stage": ctx["lifecycle"]["stage"],
					"latest_interaction": bool(ctx["latest_interaction"]),
					"latest_outcome": bool(ctx["latest_outcome"]),
					"assessment": bool(ctx["assessment"].get("current")),
					"parent_context": len(ctx["parent_context"]),
					"score_state": ctx["admissions_context"]["score"].get("state"),
					"history_count": len(ctx["history"]),
				}
			)
		else:
			entry["context_error"] = ctx_error
		students.append(entry)

	result = {
		"ok": all(s.get("seeded") and s.get("stage_ok") for s in students),
		"target_sale": frappe.db.get_value(
			"CRM Staff", {"user": TARGET_EMAIL}, ["name", "full_name", "user", "is_active"], as_dict=True
		),
		"students": students,
		"service_user": frappe.conf.get(SERVICE_USER_CONFIG_KEY),
	}
	print(frappe.as_json(result))
	return result
