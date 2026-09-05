"""Canonical golden demo seed: four HCMC leads on one Sale account, full CRM chain.

Run with::

    bench --site crm.localhost execute crm.demo.seed_golden.golden_seed
    bench --site crm.localhost execute crm.demo.seed_golden.verify

``golden_seed`` wipes nothing on its own (drive that with ``bench reinstall``);
it builds one integral, realistic dataset on top of a fresh site:

* a real-looking HCMC assignment topology (cluster, two zones, two wards, three
  teams/pools) and the requested Sale account (``TARGET_EMAIL``) as the owner
  of every seeded lead;
* four ``CRM Student`` leads (Lead stage) spread across two zones/schools,
  each with the complete raw CRM chain the admissions API and the AI features
  read: consent + geography snapshot on intake, three interactions, three
  intents, a qualification outcome, an admission application, parent
  authority + guardian, marketing attribution, a confirmed assessment, a
  score-history row, a lead Contact, an AI insight row, a completed Student
  360 analysis run and three pending NBA recommendations.

This is the single golden dataset -- there is no parallel/local variant.
"""

from __future__ import annotations

import hashlib
import json
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
		"CRM Student", student, ["owner_staff", "owning_team", "ownership_revision"], as_dict=True
	)
	if current.owner_staff == staff and current.owning_team == team:
		return
	from crm.fcrm.student_ownership import change_student_ownership

	change_student_ownership(
		student=student,
		target_kind="owner",
		target_id=staff,
		target_team_id=team,
		reason="Golden fixture: assign the sample lead to the requested Sale account.",
		idempotency_key=f"{NAMESPACE}:assign:{student}:r{int(current.ownership_revision or 0)}",
		expected_revision=int(current.ownership_revision or 0),
		correlation_id=f"{NAMESPACE}:{student}",
		_internal_service=True,
		_internal_actor="Administrator",
		_commit=False,
	)
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
		"key": "minh-anh",
		"namespace": f"{NAMESPACE}:minh-anh",
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
		"key": "gia-huy",
		"namespace": f"{NAMESPACE}:gia-huy",
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
			"type": "CALL",
			"title": "Gọi lại sau khi gửi bảng so sánh chương trình",
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
		"key": "khanh-linh",
		"namespace": f"{NAMESPACE}:khanh-linh",
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
		"key": "nhat-minh",
		"namespace": f"{NAMESPACE}:nhat-minh",
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
			("Major Inquiry", "Dominant", 81),
			("Tuition", "Support", 75),
			("Enrollment Intent", "Support", 66),
		),
		"outcome_next_action": "Gọi lại sau khi gia đình hoàn tất trao đổi ngân sách",
		"assessment": {
			"interest": "Medium",
			"interest_confidence": 70,
			"fit": "Medium",
			"fit_confidence": 66,
			"primary_barrier": "Cost",
			"barrier_confidence": 81,
			"enrollment_probability": 48,
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
]

# Mutated by ``_run_student`` for the duration of one profile seed.
_ACTIVE: dict[str, Any] = _PROFILES[0]

_LIFECYCLE_ORDER = ["Lead", "MQL", "Applicant", "Enrolled"]


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
	}
	try:
		for key, value in keys.items():
			frappe.conf[key] = value
		frappe.flags.crm_governance_additive = True
		frappe.flags.crm_governance_change = True
		frappe.flags.legacy_fact_migration = True
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


def _ensure_interaction_type(name: str) -> str:
	term = frappe.db.get_value("CRM Term", {"term_name": name, "category": "interaction_type"}, "name")
	if term:
		return term
	return (
		frappe.get_doc({"doctype": "CRM Term", "term_name": name, "category": "interaction_type"})
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_intent_type(name: str, importance: str) -> str:
	term = frappe.db.get_value("CRM Term", {"term_name": name, "category": "intent_type"}, "name")
	if term:
		return term
	return seed_demo._ensure_intent_type(name, importance, f"Golden seed fixture: {name}")


def _ensure_term(name: str, category: str) -> str:
	existing = frappe.db.get_value("CRM Term", {"term_name": name, "category": category}, "name")
	if existing:
		return existing
	return (
		frappe.get_doc({"doctype": "CRM Term", "term_name": name, "category": category})
		.insert(ignore_permissions=True)
		.name
	)


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


def _submit_student(context: dict[str, Any], pool: str, high_school: str) -> str:
	from crm.fcrm.student_intake import submit_intake

	email = _ACTIVE["student_email"]
	payload = {
		"student_name": _ACTIVE["student_name"],
		"email": email,
		"phone": _ACTIVE["student_phone"],
		"id_number": _ACTIVE["id_number"],
		"gender": _ACTIVE["gender"],
		"date_of_birth": _ACTIVE["date_of_birth"],
		"admission_method": "Transcript Review",
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

	existing = frappe.db.get_value("CRM Student", {"email": email}, "name")
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
	doc = frappe.get_doc("CRM Student", student)
	parent = _ACTIVE.get("parent")
	values = {
		"admission_method": "Transcript Review",
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
	existing = frappe.db.get_value(
		"CRM Intent", {"interaction": interaction, "intent_type": intent, "intent_role": role}, "name"
	)
	if existing:
		return existing
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
		{"attached_to_doctype": "CRM Student", "attached_to_name": student, "file_name": file_name},
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
				"attached_to_doctype": "CRM Student",
				"attached_to_name": student,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_outcome(student: str, interaction: str, evidence_file: str) -> str:
	from crm.fcrm.student_engagement import record_outcome

	source_key = _key("outcome", "primary")
	existing = frappe.db.get_value("CRM Student Outcome", {"source_key": source_key}, "name")
	if existing:
		return existing
	result = record_outcome(
		student=student,
		interaction=interaction,
		outcome_code=_ACTIVE["outcome_code"],
		continuity_kind="task",
		next_action={"title": _ACTIVE["outcome_next_action"]},
		next_action_assignee=OWNER_USER,
		next_action_due_at=SEED_NOW + timedelta(days=1),
		qualification_evidence=[{"category": "document", "doctype": "File", "name": evidence_file}],
		source_key=source_key,
		expected_revision=int(frappe.db.get_value("CRM Student", student, "engagement_revision") or 0),
		idempotency_key=source_key,
		correlation_id=_correlation(),
	)
	return result["event"]


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
		doc = frappe.get_doc("CRM Student", student)
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
		doc = frappe.get_doc("CRM Student", student)
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

	method = "Transcript Review"
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
		expected_revision=int(frappe.db.get_value("CRM Student", student, "engagement_revision") or 0),
		idempotency_key=source_reference,
	)
	return result["application"]


def _ensure_parent(student: str, context: dict[str, Any], team: str, high_school: str) -> dict[str, str] | None:
	spec = _ACTIVE.get("parent")
	if not spec:
		return None
	from crm.fcrm.student_parent_context import record_parent_contact_authority

	parent_email = spec["email"]
	contact = frappe.db.get_value("CRM Contact", {"email": parent_email}, "name")
	if not contact:
		previous = frappe.flags.get("student_conversion_service")
		frappe.flags.student_conversion_service = True
		try:
			contact = (
				frappe.get_doc(
					{
						"doctype": "CRM Contact",
						"full_name": spec["name"],
						"phone": spec["phone"],
						"email": parent_email,
						"enrollment_status": context["enrollment_status"],
						"lead_status": "Mới",
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


def _ensure_attribution(student: str, context: dict[str, Any]) -> dict[str, Any]:
	from crm.fcrm.student_attribution import record_campaign_touchpoint, record_event_participation

	campaign_key = _key("campaign", "open-day")
	if not frappe.db.exists("CRM Marketing Engagement", {"idempotency_key": campaign_key}):
		record_campaign_touchpoint(
			student,
			context["campaign"],
			touched_at=SEED_NOW - timedelta(days=7),
			source="Manual",
			notes="Đăng ký từ landing page học bổng và ngày hội Open Day.",
			idempotency_key=campaign_key,
			correlation_id=_key("attribution", "open-day"),
		)
	event_key = _key("event", "campus-visit")
	if not frappe.db.exists("CRM Marketing Engagement", {"idempotency_key": event_key}):
		record_event_participation(
			student,
			context["event"],
			status="Checked-in",
			registered_at=SEED_NOW - timedelta(days=5),
			checked_in_at=SEED_NOW - timedelta(days=5, hours=-1),
			feedback_rating=5,
			feedback_notes="Đã tham quan campus và trao đổi với chuyên viên tuyển sinh.",
			idempotency_key=event_key,
			correlation_id=_key("attribution", "campus-visit"),
		)
	return {"campaign": context["campaign"], "event": context["event"]}


def _ensure_assessment(student: str, interaction: str, intent: str, application: str | None) -> str:
	from crm.fcrm.student_assessment import record_student_assessment

	existing = frappe.db.get_value(
		"CRM Student Assessment", {"student": student, "status": "confirmed"}, "name"
	)
	if existing:
		return existing
	evidence = [f"CRM Interaction:{interaction}", f"CRM Intent:{intent}"]
	if application:
		evidence.append(f"CRM Admission Application:{application}")
	result = record_student_assessment(
		student,
		dict(_ACTIVE["assessment"]),
		source="manual",
		reason=_ACTIVE["assessment_reason"],
		evidence_references=evidence,
		model_version="golden-seed-2026.09",
		confirm=True,
	)
	return result["name"]


def _ensure_action(student: str, owner_staff: str) -> str | None:
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
		student,
		spec["type"],
		spec["title"],
		idempotency_key=idempotency_key,
		due_at=SEED_NOW + timedelta(days=1),
		priority=spec.get("priority", "high"),
		assignee_staff=owner_staff,
	)["action"]


def _ensure_score(student: str) -> str:
	from crm.api.scoring_write import append_local_fixture_score
	from crm.fcrm.scoring_policy import get_active_policy

	existing = frappe.db.get_value(
		"CRM Score History", {"student": student}, "name", order_by="creation desc"
	)
	if existing:
		return existing
	policy = get_active_policy()
	if not policy:
		frappe.throw("No active CRM scoring policy is available.", frappe.ValidationError)
	doc = frappe.get_doc("CRM Student", student)
	spec = _ACTIVE["score"]
	result = append_local_fixture_score(
		student=student,
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
	contact = frappe.db.get_value("CRM Contact", {"student": student}, "name")
	if not contact:
		contact = frappe.db.get_value("CRM Contact", {"email": profile_email}, "name")
	values = {
		"full_name": _ACTIVE["student_name"],
		"phone": _ACTIVE["student_phone"],
		"email": profile_email,
		"student": student,
		"student_identity": frappe.db.get_value("CRM Student", student, "identity"),
		"enrollment_status": context["enrollment_status"],
		"lead_status": "Mới",
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
			frappe.db.set_value("CRM Contact", contact, values, update_modified=False)
		else:
			contact = frappe.get_doc({"doctype": "CRM Contact", **values}).insert(ignore_permissions=True).name
	finally:
		if previous is None:
			frappe.flags.pop("student_conversion_service", None)
		else:
			frappe.flags.student_conversion_service = previous
	seed_showcase._ensure_consent_event(contact, "Granted")
	seed_showcase._ensure_marketing_engagement(student, contact, context.get("campaign"), context.get("event"))
	return contact


def _digest(value: Any) -> str:
	return hashlib.sha256(
		json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
	).hexdigest()


def _ensure_ai_insight(student: str, interactions: list[str]) -> dict[str, Any]:
	from crm.api.ai_insight import upsert_ai_insight

	revision = int(frappe.db.get_value("CRM Student", student, "student_context_revision") or 0)
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
	return upsert_ai_insight(
		student=student,
		expected_context_revision=revision,
		generation_idempotency_key=f"{_ns()}:ai-insight:v1:r{revision}",
		producer_identity="golden-seed",
		ai_policy_version="phase2-ai-insight-v1",
		ai_score=insight["score"],
		ai_score_reason=_ACTIVE["assessment_reason"],
		ai_next_action=insight["next_action"],
		ai_summary=(
			f"{_ACTIVE['student_name']} đã để lại nhu cầu rõ về {_ACTIVE['major']}. Hồ sơ còn một "
			"số điểm cần được xác nhận trước khi chuyển bước tiếp theo."
		),
		ai_detected_interests=interests,
		ai_risk_flags=risks,
	)


def _ensure_student_analysis(student: str, interactions: list[str], score: str | None) -> dict[str, Any]:
	from crm.api.intelligence_runs import request_student_analysis_run
	from crm.fcrm import intelligence_runs

	current_revision = int(frappe.db.get_value("CRM Student", student, "student_context_revision") or 0)
	request = request_student_analysis_run(
		student,
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
	refs = [f"student:{student}", f"interaction:{interactions[-1]}"]
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
				"evidence_refs": [f"student:{student}"],
			},
			{
				"type": "readiness",
				"title": "Hồ sơ đang trong giai đoạn cân nhắc",
				"summary": "Một số thông tin tuyển sinh và trao đổi gia đình vẫn đang được hoàn thiện.",
				"confidence": "MEDIUM",
				"evidence_refs": [f"student:{student}"],
			},
		],
		"risks": [
			{
				"code": "INCOMPLETE_CONTEXT",
				"severity": "MEDIUM",
				"title": "Còn điểm cần xác nhận",
				"summary": "Thông tin về quyết định cuối cùng và điều kiện tài chính chưa hoàn toàn rõ ràng.",
				"evidence_refs": [f"student:{student}"],
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


def _ensure_nba(student: str) -> dict[str, Any]:
	from crm.fcrm import nba_evaluations, nba_policy

	receipt = nba_evaluations.request_nba_evaluation(
		student=student,
		idempotency_key=f"{_ns()}:nba",
		force_reason="Golden fixture for manual NBA walkthrough",
	)
	evaluation = receipt["evaluation"]
	doc = frappe.get_doc("CRM NBA Evaluation", evaluation)
	if doc.status == "completed":
		return {
			"evaluation": evaluation,
			"status": doc.status,
			"recommendations": frappe.db.count("CRM Recommendation", {"evaluation": evaluation}),
		}
	claim = nba_evaluations.claim_nba_evaluation(
		evaluation=evaluation, run_generation=int(doc.run_generation or 0)
	)
	if not claim.get("claimed"):
		return {"evaluation": evaluation, "status": claim.get("status", "running")}
	eligible = nba_policy.eligible_action_set_for_student(student, actor="Administrator", now=SEED_NOW)
	preferred = ["ACTIVATE_WINBACK", "ADD_TAG", "ADVISE_CAREER", "CALL", "EMAIL"]
	available = {row["code"]: row for row in eligible.get("actions") or []}
	actions = [available[code] for code in preferred if code in available][:3]
	if not actions:
		actions = (eligible.get("actions") or [])[:3]
	recommendations = []
	for rank, action in enumerate(actions, start=1):
		code = action["code"]
		recommendations.append(
			{
				"recommendation_key": f"{_ns()}:recommendation:{rank}",
				"rank": rank,
				"action_ref": {
					"action_id": f"ACT-{code}",
					"action_revision": int(action["revision"]),
					"action_digest": action["digest"],
				},
				"opportunity_refs": [],
				"recommended_execution_params": {},
				"recommended_timing": {
					"earliest_at": None,
					"latest_at": None,
					"scheduled_at": (SEED_NOW + timedelta(hours=rank * 4)).isoformat(),
					"timezone": "Asia/Ho_Chi_Minh",
				},
				"score": {"total": round(max(0.45, 0.92 - rank * 0.11), 2)},
				"confidence": round(max(0.55, 0.91 - rank * 0.08), 2),
				"reason_codes": ["ENGAGE_OR_REENGAGE"],
				"evidence_refs": [f"student:{student}"],
				"explanation_facts": [
					f"{_ACTIVE['student_name']} có tín hiệu cần tiếp tục chăm sóc ở ưu tiên {rank}.",
					f"Ngành quan tâm: {_ACTIVE['major']}.",
				],
				"conflict_keys": [f"action:{code}"],
				"expires_at": (SEED_NOW + timedelta(days=14)).isoformat(),
			}
		)
	if not recommendations:
		return {"evaluation": evaluation, "status": "abstained", "reason": "No eligible action catalog rows"}
	return nba_evaluations.commit_nba_evaluation_result(
		evaluation=evaluation,
		run_generation=claim["run_generation"],
		lease_token=claim["lease_token"],
		engine_revision="golden-seed-nba-v1",
		run_status="completed",
		disposition="RECOMMEND",
		reason_codes=["ENGAGE_OR_REENGAGE"],
		result_digest=_digest(recommendations),
		trace_digest=_digest({"student": student, "source": NAMESPACE}),
		recommendations=recommendations,
		trace_entries=[
			{"kind": "golden_fixture", "student": student, "recommendation_count": len(recommendations)}
		],
	)


def _run_student(context: dict[str, Any], pool: str, high_school: str, staff: str, team: str) -> dict[str, Any]:
	student = _submit_student(context, pool, high_school)
	_complete_student_profile(student, context)
	frappe.db.commit()
	_force_assignment(student, staff, team)
	owner_staff = staff

	interaction_website = _ensure_interaction(
		student, "website-form", "Website Visit", SEED_NOW - timedelta(days=8),
		"Website", "inbound", _ACTIVE["interactions"][0],
	)
	interaction_counseling = _ensure_interaction(
		student, "initial-counseling", "Counseling", SEED_NOW - timedelta(days=6),
		"Phone", "outbound", _ACTIVE["interactions"][1],
	)
	interaction_latest = _ensure_interaction(
		student, "follow-up", "Connected", SEED_NOW - timedelta(days=2),
		"Phone", "inbound", _ACTIVE["interactions"][2],
	)
	intents = _ACTIVE["intents"]
	intent_first = _ensure_intent(student, interaction_counseling, *intents[0])
	intent_dominant = _ensure_intent(student, interaction_latest, *intents[1])
	_ensure_intent(student, interaction_latest, *intents[2])

	evidence_file = _ensure_file(student)
	outcome = _ensure_outcome(student, interaction_latest, evidence_file)
	walked = _ensure_lifecycle(student, outcome, intent_dominant, evidence_file)
	application = _ensure_application(student, context)
	parent = _ensure_parent(student, context, team, high_school)
	attribution = _ensure_attribution(student, context)
	assessment = _ensure_assessment(student, interaction_latest, intent_dominant, application)
	action = _ensure_action(student, owner_staff)
	score = _ensure_score(student)
	contact = _ensure_student_contact(student, context, owner_staff, team, high_school)
	frappe.db.commit()

	interactions = [interaction_website, interaction_counseling, interaction_latest]
	ai_insight = _ensure_ai_insight(student, interactions)
	analysis = _ensure_student_analysis(student, interactions, score)
	nba = _ensure_nba(student)
	frappe.db.commit()

	return {
		"variant": _ACTIVE["key"],
		"student": student,
		"student_name": frappe.db.get_value("CRM Student", student, "student_name"),
		"high_school": high_school,
		"target_stage": _ACTIVE["target_stage"],
		"lifecycle_stage": frappe.db.get_value("CRM Student", student, "lifecycle_stage"),
		"lifecycle_walk": walked,
		"owner_staff": owner_staff,
		"contact": contact,
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
			"interactions": frappe.db.count("CRM Interaction", {"student": student}),
			"intents": frappe.db.count("CRM Intent", {"student": student}),
			"outcomes": frappe.db.count("CRM Student Outcome", {"student": student}),
			"lifecycle_events": frappe.db.count("CRM Student Lifecycle Event", {"student": student}),
			"assessments": frappe.db.count("CRM Student Assessment", {"student": student}),
			"parent_authorities": frappe.db.count("CRM Parent Contact Authority", {"student": student}),
			"consent_events": frappe.db.count("CRM Contact Consent Event", {"student": student}),
			"geography_snapshots": frappe.db.count("CRM Student Geography Snapshot", {"student": student}),
			"applications": frappe.db.count("CRM Admission Application", {"student": student}),
			"actions": frappe.db.count("CRM Action Item", {"student": student}),
			"scores": frappe.db.count("CRM Score History", {"student": student}),
			"recommendations": frappe.db.count("CRM Recommendation", {"target_id": student}),
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
	"CRM Term",
	"CRM Student",
)


def _ensure_ai_service_role() -> None:
	"""Create the desk-less AI service role if it doesn't exist yet (idempotent)."""
	from frappe.permissions import add_permission

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
			add_permission(doctype, AI_SERVICE_ROLE, 0)


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


ADMISSION_METHOD = "Transcript Review"


def _ensure_admission_method(name: str) -> None:
	"""Canonical admission method Term the admission offering links to."""
	if frappe.db.exists("CRM Term", {"term_name": name, "category": "admission_method"}):
		return
	from crm.fcrm.master_data_governance import create_additive_value

	create_additive_value(
		"CRM Term",
		name,
		reason="Canonical admission method used by the golden demo dataset.",
		idempotency_key=f"golden-seed:admission-method:{name}",
		correlation_id="golden-seed",
		category="admission_method",
	)


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
	from crm.api.student_context import get_student_context

	students = []
	for profile in _PROFILES:
		name = frappe.db.get_value("CRM Student", {"email": profile["student_email"]}, "name")
		if not name:
			students.append({"variant": profile["key"], "seeded": False})
			continue
		ctx = get_student_context(name, history_limit=50)
		students.append(
			{
				"variant": profile["key"],
				"seeded": True,
				"student": name,
				"stage": ctx["lifecycle"]["stage"],
				"expected_stage": profile["target_stage"],
				"stage_ok": ctx["lifecycle"]["stage"] == profile["target_stage"],
				"latest_interaction": bool(ctx["latest_interaction"]),
				"latest_outcome": bool(ctx["latest_outcome"]),
				"assessment": bool(ctx["assessment"].get("current")),
				"parent_context": len(ctx["parent_context"]),
				"score_state": ctx["admissions_context"]["score"].get("state"),
				"history_count": len(ctx["history"]),
				"owner_staff": frappe.db.get_value("CRM Student", name, "owner_staff"),
				"ai_insight": frappe.db.exists("CRM AI Lead Insight", {"student": name}),
				"recommendations": frappe.db.count("CRM Recommendation", {"target_id": name}),
			}
		)

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
