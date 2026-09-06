"""Bounded local golden fixture for the Sale + Student 360 + NBA demo.

This fixture is intentionally local-only and additive.  It creates the same
kind of data used by the production walkthrough without copying production
document names, ids, users, or credentials:

* real-looking HCMC assignment topology and the requested Sale account;
* four Gmail leads with school, ward, major, consent, and ownership data;
* parent authority, guardian, application, campaign/event attribution;
* interactions, intents, outcome, assessment, score history and AI insight;
* a completed Student 360 snapshot and three pending NBA recommendations per
  lead, written through the durable contracts so the UI can be tested.

Run on a disposable local site with::

    bench --site crm.localhost execute crm.demo.seed_golden_local.seed
    bench --site crm.localhost execute crm.demo.seed_golden_local.verify

The seed never deletes data.  Re-running it updates only rows identified by
``NAMESPACE``/the profile email and reuses existing master data.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any

import frappe

from crm.demo import (
	seed_ctv_sale,
	seed_demo,
	seed_golden,
	seed_role_accounts,
	seed_showcase,
	seed_staff,
)
from crm.patches.v1_0.seed_crm_action_type import execute as seed_action_catalog

LOCAL_SITE = "crm.localhost"
NAMESPACE = "crm-demo-golden-local-2026"
TARGET_EMAIL = "hoalvpse181951@fpt.edu.vn"
TARGET_NAME = "Le Vu Phuong Hoa (K18 HCM)"
PASSWORD = "123456"
CAMPUS = "FPTU Ho Chi Minh Campus"
SEED_NOW = datetime(2026, 9, 5, 9, 0, 0)
CLUSTER_NAME = "TP.HCM - Tuyển sinh"
ZONE_NAMES = {
	"east": "TP.HCM - Khu Đông (Tăng Nhơn Phú)",
	"central": "TP.HCM - Khu trung tâm (Quận 5)",
}
WARD_NAMES = {"east": "Tăng Nhơn Phú", "central": "Bến Nghé"}
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


PROFILES: tuple[dict[str, Any], ...] = (
	{
		"key": "minh-anh",
		"student_name": "Nguyễn Minh Anh",
		"email": "nguyen.minh.anh.2008@gmail.com",
		"phone": "0908123001",
		"gender": "Nữ",
		"date_of_birth": "2008-04-15",
		"id_number": "079308012345",
		"id_issued_date": "2024-05-18",
		"major": "Artificial Intelligence",
		"school": "THPT Chuyên Lê Hồng Phong",
		"school_code": "HCM-LHP",
		"zone": "central",
		"ward": "central",
		"source": "FPTU Open Day",
		"advertising_channel": "Facebook Ads - Học bổng 2026",
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
		"outcome_code": "qualified",
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
		"assessment_reason": "Học sinh đã tham dự Open Day và chủ động hỏi về ngành AI; rào cản chính hiện tại là ngân sách gia đình.",
		"parent": {
			"name": "Trần Thị Thu Hà",
			"email": "thu.ha.nguyen@gmail.com",
			"phone": "0908123456",
			"relationship": "Mẹ",
			"address": "Quận Bình Thạnh, Thành phố Hồ Chí Minh",
		},
		"application": {"status": "Under Review", "document_completed": 6, "scholarship_percentage": 50},
		"action": {
			"type": "PARENT_CONTACT",
			"title": "Gọi phụ huynh xác nhận điều kiện học bổng",
			"priority": "high",
		},
		"score": {"fit": 34, "engagement": 27, "intent": 30, "negative": -4, "final": 87},
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
		"student_name": "Trần Gia Huy",
		"email": "tran.gia.huy.2008@gmail.com",
		"phone": "0908234002",
		"gender": "Nam",
		"date_of_birth": "2008-07-22",
		"id_number": "079308072246",
		"id_issued_date": "2024-07-10",
		"major": "Business Administration",
		"school": "THPT Nguyễn Thượng Hiền",
		"school_code": "HCM-NTH",
		"zone": "central",
		"ward": "central",
		"source": "FPTU HCMC Campus Visit",
		"advertising_channel": "Google Search - Ngành kinh doanh",
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
		"outcome_code": "follow_up_required",
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
		"assessment_reason": "Học sinh phù hợp với ngành nhưng còn so sánh nhiều lựa chọn; cần làm rõ khác biệt chương trình và cơ hội nghề nghiệp.",
		"parent": {
			"name": "Nguyễn Văn Hùng",
			"email": "hung.nguyen.1980@gmail.com",
			"phone": "0908234567",
			"relationship": "Bố",
			"address": "Quận Tân Bình, Thành phố Hồ Chí Minh",
		},
		"application": {"status": "Submitted", "document_completed": 4, "scholarship_percentage": 0},
		"action": {
			"type": "CALL",
			"title": "Gọi lại sau khi gửi bảng so sánh chương trình",
			"priority": "medium",
		},
		"score": {"fit": 31, "engagement": 22, "intent": 25, "negative": -8, "final": 70},
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
		"student_name": "Lê Khánh Linh",
		"email": "le.khanh.linh.2008@gmail.com",
		"phone": "0908345003",
		"gender": "Nữ",
		"date_of_birth": "2008-02-09",
		"id_number": "079308020934",
		"id_issued_date": "2024-03-12",
		"major": "Data Science",
		"school": "THPT Thủ Đức",
		"school_code": "HCM-TD",
		"zone": "east",
		"ward": "east",
		"source": "Facebook Lead Form",
		"advertising_channel": "Facebook Lead Form - Data & AI",
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
		"outcome_code": "connected",
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
		"assessment_reason": "Nền tảng học tập phù hợp và có quan tâm rõ đến Data Science, nhưng hồ sơ còn thiếu thông tin về lộ trình đầu vào.",
		"parent": {
			"name": "Lê Thị Thanh Mai",
			"email": "thanhmai.le@gmail.com",
			"phone": "0908345678",
			"relationship": "Mẹ",
			"address": "Thành phố Thủ Đức, Thành phố Hồ Chí Minh",
		},
		"application": {"status": "Under Review", "document_completed": 5, "scholarship_percentage": 30},
		"action": {
			"type": "EMAIL",
			"title": "Gửi lại checklist đầu vào ngành Data Science",
			"priority": "medium",
		},
		"score": {"fit": 33, "engagement": 20, "intent": 26, "negative": -5, "final": 74},
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
		"student_name": "Phạm Nhật Minh",
		"email": "pham.nhat.minh.2008@gmail.com",
		"phone": "0908456004",
		"gender": "Nam",
		"date_of_birth": "2008-11-18",
		"id_number": "079308111856",
		"id_issued_date": "2024-12-09",
		"major": "Digital Marketing",
		"school": "THPT Nguyễn Hữu Huân",
		"school_code": "HCM-NHH",
		"zone": "east",
		"ward": "east",
		"source": "FPTU HCMC Campus Visit",
		"advertising_channel": "Open Day - Khối ngành Kinh tế",
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
		"outcome_code": "follow_up_required",
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
		"assessment_reason": "Học sinh có nhu cầu rõ về ngành nhưng gia đình chưa chốt ngân sách; cần duy trì tư vấn theo mốc phù hợp.",
		"parent": {
			"name": "Phạm Quốc Tuấn",
			"email": "quoctuan.pham@gmail.com",
			"phone": "0908456789",
			"relationship": "Bố",
			"address": "Thành phố Thủ Đức, Thành phố Hồ Chí Minh",
		},
		"application": {"status": "Draft", "document_completed": 2, "scholarship_percentage": 0},
		"action": {
			"type": "CALL",
			"title": "Gọi lại sau khi gia đình trao đổi ngân sách",
			"priority": "high",
		},
		"score": {"fit": 27, "engagement": 18, "intent": 22, "negative": -10, "final": 57},
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
)


def _assert_local_site() -> None:
	site = getattr(frappe.local, "site", "") or ""
	if (
		site == LOCAL_SITE
		or site.endswith(".localhost")
		or site.endswith(".local")
		or frappe.conf.get("allow_demo_seed")
	):
		return
	frappe.throw(
		"This fixture runs only on crm.localhost. Set allow_demo_seed=1 only for a disposable local site.",
		frappe.PermissionError,
	)


def _set_config(key: str, value: Any) -> None:
	frappe.conf[key] = value
	from frappe.installer import update_site_config

	update_site_config(key, value, validate=False)


@contextmanager
def _seed_context():
	previous_user = frappe.session.user
	previous_flags = {
		"crm_governance_additive": frappe.flags.get("crm_governance_additive"),
		"crm_governance_change": frappe.flags.get("crm_governance_change"),
		"legacy_fact_migration": frappe.flags.get("legacy_fact_migration"),
	}
	previous = {
		key: frappe.conf.get(key)
		for key in (
			"crm_agents_service_user",
			"crm_nba_evaluation_runtime_enabled",
			"crm_intelligence_runs_enabled",
			"crm_intelligence_writer_epoch",
			"crm_nba_manual_requests_per_actor_target",
		)
	}
	frappe.set_user("Administrator")
	frappe.flags.crm_governance_additive = True
	frappe.flags.crm_governance_change = True
	frappe.flags.legacy_fact_migration = True
	for key, value in {
		"crm_agents_service_user": "Administrator",
		"crm_nba_evaluation_runtime_enabled": 1,
		"crm_intelligence_runs_enabled": 1,
		"crm_intelligence_writer_epoch": 1,
		"crm_nba_manual_requests_per_actor_target": 500,
	}.items():
		frappe.conf[key] = value
	try:
		yield
	finally:
		frappe.set_user(previous_user)
		for key, value in previous_flags.items():
			if value is None:
				frappe.flags.pop(key, None)
			else:
				frappe.flags[key] = value
		for key, value in previous.items():
			if value is None:
				frappe.conf.pop(key, None)
			else:
				frappe.conf[key] = value


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

	result = create_additive_value(
		"CRM Lead Source",
		name,
		reason=f"Local golden fixture source ({channel_family}) for the Student 360 walkthrough.",
		idempotency_key=f"{NAMESPACE}:source:{name}",
		correlation_id=NAMESPACE,
	)
	return result["name"]


def _ensure_platform(name: str, source: str) -> str:
	if frappe.db.exists("CRM Platform", name):
		return name
	from crm.fcrm.master_data_governance import create_additive_value

	return create_additive_value(
		"CRM Platform",
		name,
		reason="Local golden fixture channel for the Student 360 walkthrough.",
		idempotency_key=f"{NAMESPACE}:platform:{name}",
		correlation_id=NAMESPACE,
		lead_source=source,
	)["name"]


def _normalize_assignment_labels() -> None:
	"""Keep the local topology readable when an older fixture was run first."""
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
		frappe.db.set_value(
			"CRM Zone",
			zone,
			{"cluster": cluster, "is_placeholder": 0},
			update_modified=False,
		)
		zones[key] = zone

	wards: dict[str, str] = {}
	for key, ward_name in WARD_NAMES.items():
		ward = frappe.db.exists("CRM Ward", {"ward_name": ward_name})
		if not ward:
			ward = (
				frappe.get_doc(
					{
						"doctype": "CRM Ward",
						"ward_code": "760" if key == "central" else "HCM-TNP",
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
				"zone": zones[key],
				"province": province,
				"province_name": "Ho Chi Minh City",
				"ward_code": "760" if key == "central" else "HCM-TNP",
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
		"CRM Team Zone Assignment",
		{"zone": zone, "status": "Active"},
		["name", "team"],
		as_dict=True,
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


def _ensure_assignment_policies(
	campus: str,
	teams: dict[str, str],
	pools: dict[str, str],
	zones: dict[str, str],
	staff_by_user: dict[str, str],
) -> None:
	for key in ("A", "B", "C"):
		strategy = "weighted_score" if key == "B" else "round_robin"
		policy_key = f"{NAMESPACE}:ROUTE:{pools[key]}"
		if not frappe.db.exists(
			"CRM Student Routing Policy",
			{"campus": campus, "student_pool": pools[key], "status": "active"},
		):
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
						"break_glass_reason": "Local golden Student 360 fixture",
						"schema_version": "phase7-v1",
					}
				).insert(ignore_permissions=True)
			finally:
				if previous is None:
					frappe.flags.pop("student_policy_service", None)
				else:
					frappe.flags.student_policy_service = previous
		if key in ("A", "B"):
			member_user = (
				"nguyen.minh.khoi@gmail.com" if key == "A" else "le.thanh.huong@gmail.com"
			)
			_ensure_assignment_membership(
				staff_by_user[member_user],
				teams[key],
				"Sale" if key == "A" else "Lead Sale",
				is_primary=False,
			)
			_ensure_zone_team(zones["east"] if key == "A" else zones["central"], teams[key])


def _ensure_assignment_context(
	campus: str, province: str, staff_by_user: dict[str, str]
) -> dict[str, Any]:
	_, zones, wards = _ensure_assignment_geography()
	teams: dict[str, str] = {}
	pools: dict[str, str] = {}
	for key in ("A", "B", "C"):
		teams[key], pools[key] = _ensure_assignment_team_pool(key, campus)
	_ensure_assignment_policies(campus, teams, pools, zones, staff_by_user)
	return {"cluster": CLUSTER_NAME, "zones": zones, "wards": wards, "teams": teams, "pools": pools}


def _repair_assignment_wards(province: str, zone_ids: dict[str, str], ward_ids: dict[str, str]) -> None:
	"""Backfill Zone on legacy local Ward rows before shared-context seeding."""
	for key, ward in ward_ids.items():
		if frappe.db.exists("CRM Ward", ward):
			frappe.db.set_value(
				"CRM Ward",
				ward,
				{
					"province": province,
					"province_name": "Ho Chi Minh City",
					"zone": zone_ids[key],
					# The legacy shared-context seed looks up the default ward by
					# code 760; keep that compatibility code while retaining the
					# user-facing ward/zone labels from the assignment fixture.
					"ward_code": "760" if key == "central" else "HCM-TNP",
				},
				update_modified=False,
			)


def _ensure_school(
	profile: dict[str, Any], province: str, ward: str, zone: str, team: str, staff: str
) -> str:
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


def _ensure_target_account(campus: str, department: str, teams: dict[str, str]) -> tuple[str, str]:
	spec = seed_ctv_sale.SalesAccountSeed(
		namespace=NAMESPACE,
		account_email=TARGET_EMAIL,
		account_full_name=TARGET_NAME,
		account_role="Sale",
		password=PASSWORD,
		team_membership_function="Sale",
		student_scenarios=(),
		assign_students_to_account=False,
	)
	seed_ctv_sale._ensure_user(spec)
	staff = seed_ctv_sale._ensure_staff(spec, campus, department)
	_ensure_assignment_membership(staff, teams["B"], "Sale", is_primary=True)
	_ensure_assignment_membership(staff, teams["A"], "Sale", is_primary=False)
	return staff, teams["B"]


def _force_assignment(student: str, staff: str, team: str) -> None:
	current = frappe.db.get_value(
		"CRM Student",
		student,
		["owner_staff", "owning_team", "owning_pool", "ownership_revision"],
		as_dict=True,
	)
	if current.owner_staff == staff and current.owning_team == team:
		return
	from crm.fcrm.student_ownership import change_student_ownership

	change_student_ownership(
		student=student,
		target_kind="owner",
		target_id=staff,
		target_team_id=team,
		reason="Local golden fixture: assign the sample lead to the requested Sale account.",
		idempotency_key=f"{NAMESPACE}:assign:{student}:r{int(current.ownership_revision or 0)}",
		expected_revision=int(current.ownership_revision or 0),
		correlation_id=f"{NAMESPACE}:{student}",
		_internal_service=True,
		_internal_actor="Administrator",
		_commit=False,
	)
	frappe.db.commit()


def _ensure_student_contact(
	student: str,
	profile: dict[str, Any],
	context: dict[str, Any],
	staff: str,
	team: str,
	school: str,
) -> str:
	"""Create the lead Contact used by Student 360/AI insight readers.

	The current local contract still permits legacy Student -> Contact links for
	pre-enrollment leads.  Conversion-junction rows are intentionally reserved
	for the Enrolled conversion command, so this fixture keeps the lead in Lead
	stage and uses the compatibility link here.
	"""
	contact = frappe.db.get_value("CRM Contact", {"student": student}, "name")
	if not contact:
		contact = frappe.db.get_value("CRM Contact", {"email": profile["email"]}, "name")
	values = {
		"full_name": profile["student_name"],
		"phone": profile["phone"],
		"email": profile["email"],
		"student": student,
		"student_identity": frappe.db.get_value("CRM Student", student, "identity"),
		"enrollment_status": context["enrollment_status"],
		"readiness_level": "Level 2 - Đang so sánh",
		"quality_bucket": "Warm",
		"is_verified_lead": 1,
		"assigned_to": staff,
		"owner_staff": staff,
		"owning_team": team,
		"admission_year": context["admission_year"],
		"branch": context["campus"],
		"high_school": school,
		"province": context["province"],
		"major": context["major"],
		"aspiration": context["aspiration"],
		"source": context["source"],
		"platform": context["platform"],
		"decision_maker": "Student",
		"preferred_contact_channel": "Phone",
		"notes": profile["notes"],
	}
	previous = frappe.flags.get("student_conversion_service")
	frappe.flags.student_conversion_service = True
	try:
		if contact:
			# The fixture owns this email namespace. Direct db_set avoids reopening
			# protected post-conversion fields through a normal browser save path.
			frappe.db.set_value("CRM Contact", contact, values, update_modified=False)
		else:
			contact = (
				frappe.get_doc({"doctype": "CRM Contact", **values}).insert(ignore_permissions=True).name
			)
	finally:
		if previous is None:
			frappe.flags.pop("student_conversion_service", None)
		else:
			frappe.flags.student_conversion_service = previous
	seed_showcase._ensure_consent_event(contact, "Granted")
	seed_showcase._ensure_marketing_engagement(student, contact, context.get("campaign"), context.get("event"))
	return contact


def _profile_context(base: dict[str, Any], profile: dict[str, Any], ward: str) -> dict[str, Any]:
	context = dict(base)
	context.update(
		{
			"major": _ensure_major(profile["major"]),
			"ward": ward,
			"source": _ensure_lead_source(profile["source"]),
			"platform": _ensure_platform(
				profile["advertising_channel"], _ensure_lead_source(profile["source"])
			),
			"aspiration": base["aspiration"],
			"campaign": base["campaign"],
			"event": base["event"],
		}
	)
	return context


def _seed_student(
	profile: dict[str, Any], context: dict[str, Any], pool: str, school: str, staff: str, team: str
) -> dict[str, Any]:
	from crm.demo import seed_golden

	profile = dict(profile)
	profile["student_email"] = profile["email"]
	profile["student_phone"] = profile["phone"]
	profile["namespace"] = f"{NAMESPACE}:{profile['key']}"
	profile["school"] = profile["school_code"]
	profile["target_stage"] = "Lead"
	profile["manual_action"] = profile["action"]
	profile["score"] = {
		**profile["score"],
		"details": [
			{
				"category": "Fit",
				"signal": f"Học sinh lớp 12 quan tâm {profile['major']}",
				"score": profile["score"]["fit"],
			},
			{
				"category": "Engagement",
				"signal": "Có lịch sử tương tác với tư vấn tuyển sinh",
				"score": profile["score"]["engagement"],
			},
			{
				"category": "Intent",
				"signal": "Có tín hiệu quan tâm ngành và lộ trình xét tuyển",
				"score": profile["score"]["intent"],
			},
			{
				"category": "Negative",
				"signal": "Còn điểm cần xác nhận trước bước tiếp theo",
				"score": profile["score"]["negative"],
			},
		],
	}
	seed_golden._ACTIVE = profile
	seed_golden.OWNER_USER = TARGET_EMAIL
	student = seed_golden._submit_student(context, pool, school)
	seed_golden._complete_student_profile(student, context)
	frappe.db.commit()
	_force_assignment(student, staff, team)

	interaction_1 = seed_golden._ensure_interaction(
		student,
		"website-form",
		"Website Visit",
		SEED_NOW - timedelta(days=8),
		"Website",
		"inbound",
		profile["interactions"][0],
	)
	interaction_2 = seed_golden._ensure_interaction(
		student,
		"initial-counseling",
		"Counseling",
		SEED_NOW - timedelta(days=6),
		"Phone",
		"outbound",
		profile["interactions"][1],
	)
	interaction_3 = seed_golden._ensure_interaction(
		student,
		"follow-up",
		"Connected",
		SEED_NOW - timedelta(days=2),
		"Phone",
		"inbound",
		profile["interactions"][2],
	)
	intent_1 = seed_golden._ensure_intent(student, interaction_2, *profile["intents"][0])
	intent_2 = seed_golden._ensure_intent(student, interaction_3, *profile["intents"][1])
	seed_golden._ensure_intent(student, interaction_3, *profile["intents"][2])
	file_name = seed_golden._ensure_file(student)
	outcome = seed_golden._ensure_outcome(student, interaction_3, file_name)
	application = seed_golden._ensure_application(student, context)
	parent = seed_golden._ensure_parent(student, context, team, school)
	attribution = seed_golden._ensure_attribution(student, context)
	assessment = seed_golden._ensure_assessment(student, interaction_3, intent_2, application)
	action = seed_golden._ensure_action(student, staff)
	score = seed_golden._ensure_score(student)
	frappe.db.commit()
	return {
		"student": student,
		"student_name": profile["student_name"],
		"school": school,
		"owner_staff": staff,
		"team": team,
		"parent": parent,
		"contact": _ensure_student_contact(student, profile, context, staff, team, school),
		"application": application,
		"assessment": assessment,
		"action": action,
		"score": score,
		"outcome": outcome,
		"attribution": attribution,
		"interactions": [interaction_1, interaction_2, interaction_3],
		"intent": intent_1,
	}


def _ensure_ai_insight(item: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
	from crm.api.ai_insight import upsert_ai_insight

	revision = int(frappe.db.get_value("CRM Student", item["student"], "student_context_revision") or 0)
	insight = profile["insight"]
	interests = [
		{
			"dimension_code": code,
			"label": label,
			"trend": trend,
			"stance": stance,
			"interest_level": 5 if confidence >= 85 else 3,
			"score": round(confidence / 100, 2),
			"confidence": round(confidence / 100, 2),
			"evidence": f"{profile['student_name']} — dữ liệu tư vấn tuyển sinh",
		}
		for code, label, trend, stance, confidence in insight["interests"]
	]
	risks = [
		{
			"label": label,
			"severity": severity,
			"evidence": f"{profile['student_name']} — assessment và trao đổi phụ huynh",
		}
		for label, severity in insight["risks"]
	]
	return upsert_ai_insight(
		student=item["student"],
		expected_context_revision=revision,
		# Include the source revision so a rerun after the fixture refreshes the
		# same insight instead of colliding with an earlier command receipt.
		generation_idempotency_key=f"{NAMESPACE}:{profile['key']}:ai-insight:v5:r{revision}",
		producer_identity="local-golden-seed",
		ai_policy_version="phase2-ai-insight-v1",
		ai_score=insight["score"],
		ai_score_reason=profile["assessment_reason"],
		ai_next_action=insight["next_action"],
		ai_summary=f"{profile['student_name']} đã để lại nhu cầu rõ về {profile['major']}. Hồ sơ còn một số điểm cần được xác nhận trước khi chuyển bước tiếp theo.",
		ai_detected_interests=interests,
		ai_risk_flags=risks,
	)


def _digest(value: Any) -> str:
	return hashlib.sha256(
		json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
	).hexdigest()


def _ensure_student_analysis(item: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
	from crm.api.intelligence_runs import request_student_analysis_run
	from crm.fcrm import intelligence_runs

	current_revision = int(
		frappe.db.get_value("CRM Student", item["student"], "student_context_revision") or 0
	)
	request = request_student_analysis_run(
		item["student"],
		idempotency_key=f"{NAMESPACE}:{profile['key']}:analysis:v3:r{current_revision}",
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
	refs = [f"student:{item['student']}", f"interaction:{item['interactions'][-1]}"]
	if item.get("score"):
		refs.append(f"score:{item['score']}")
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
				"summary": f"Nguyện vọng hiện tại tập trung vào {profile['major']}.",
				"confidence": "HIGH",
				"evidence_refs": [f"student:{item['student']}"],
			},
			{
				"type": "readiness",
				"title": "Hồ sơ đang trong giai đoạn cân nhắc",
				"summary": "Một số thông tin tuyển sinh và trao đổi gia đình vẫn đang được hoàn thiện.",
				"confidence": "MEDIUM",
				"evidence_refs": [f"student:{item['student']}"],
			},
		],
		"risks": [
			{
				"code": "INCOMPLETE_CONTEXT",
				"severity": "MEDIUM",
				"title": "Còn điểm cần xác nhận",
				"summary": "Thông tin về quyết định cuối cùng và điều kiện tài chính chưa hoàn toàn rõ ràng.",
				"evidence_refs": [f"student:{item['student']}"],
			}
		],
		"opportunity_signals": [
			{
				"code": "CLEAR_MAJOR_INTEREST",
				"strength": "HIGH",
				"title": "Nhu cầu ngành học rõ",
				"summary": f"Các tương tác gần đây đều xoay quanh {profile['major']} và lộ trình tuyển sinh.",
				"evidence_refs": refs[:2],
			}
		],
		"recent_changes": [
			{
				"type": "interaction",
				"summary": "Hồ sơ có thêm một lần trao đổi tư vấn trong tuần gần đây.",
				"evidence_refs": [f"interaction:{item['interactions'][-1]}"],
			}
		],
	}
	result = intelligence_runs.settle_stage(
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
		model_revision="local-golden-seed-v1",
		result_digest=_digest(report),
		report=report,
	)
	return result


def _ensure_nba(item: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
	from crm.fcrm import nba_evaluations, nba_policy

	receipt = nba_evaluations.request_nba_evaluation(
		student=item["student"],
		idempotency_key=f"{NAMESPACE}:{profile['key']}:nba",
		force_reason="Local golden fixture for manual NBA walkthrough",
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
	eligible = nba_policy.eligible_action_set_for_student(
		item["student"], actor="Administrator", now=SEED_NOW
	)
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
				"recommendation_key": f"{NAMESPACE}:{profile['key']}:recommendation:{rank}",
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
				"evidence_refs": [f"student:{item['student']}"],
				"explanation_facts": [
					f"{profile['student_name']} có tín hiệu cần tiếp tục chăm sóc ở ưu tiên {rank}.",
					f"Ngành quan tâm: {profile['major']}.",
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
		engine_revision="local-golden-seed-nba-v1",
		run_status="completed",
		disposition="RECOMMEND",
		reason_codes=["ENGAGE_OR_REENGAGE"],
		result_digest=_digest(recommendations),
		trace_digest=_digest({"student": item["student"], "source": NAMESPACE}),
		recommendations=recommendations,
		trace_entries=[
			{
				"kind": "local_fixture",
				"student": item["student"],
				"recommendation_count": len(recommendations),
			}
		],
	)


def seed() -> dict[str, Any]:
	"""Create the complete bounded local fixture."""
	_assert_local_site()
	with _seed_context():
		seed_showcase.ensure_local_integrity_keys()
		seed_showcase.ensure_demo_config()
		seed_action_catalog()
		seed_role_accounts.execute()
		# CRM Ward is now governed by CRM Zone.  Create the geography first so
		# the historical shared-context helper can safely reuse the Ward row.
		province = seed_demo._ensure_province()
		seed_demo._ensure_campus(province)
		# Team-zone assignments validate that each team already has an active
		# member, so bootstrap Staff before creating the assignment topology.
		# If a previous interrupted seed created assignment memberships, they must
		# not compete with the canonical fixture team's primary membership.
		for team_label in TEAM_NAMES.values():
			team = frappe.db.get_value("CRM Team", {"team_name": team_label}, "name")
			if team:
				for membership in frappe.get_all(
					"CRM Team Membership", filters={"team": team}, pluck="name"
				):
					frappe.db.set_value("CRM Team Membership", membership, "is_primary", 0, update_modified=False)
		staff_context = seed_staff._bootstrap()
		assignment = _ensure_assignment_context(CAMPUS, province, staff_context["staff_by_user"])
		zone_ids = assignment["zones"]
		ward_ids = assignment["wards"]
		_repair_assignment_wards(province, zone_ids, ward_ids)
		frappe.db.commit()
		base = seed_demo._bootstrap()
		teams = {
			key: frappe.db.get_value("CRM Team", {"team_name": name}, "name")
			for key, name in TEAM_NAMES.items()
		}
		pools = {
			key: frappe.db.get_value("CRM Student Pool", {"pool_name": name}, "name")
			for key, name in POOL_NAMES.items()
		}
		# Assignment opens SLA attempts, so publish the same active SLA policy
		# contract used by the showcase seed before creating Students.
		for pool in pools.values():
			seed_showcase._ensure_policies(CAMPUS, pool)
		# Admission offerings link to a CRM Admission Method lookup on a fresh local site.
		seed_golden._ensure_admission_method("TRANSCRIPT_REVIEW")
		_ensure_nba_policy()
		department = frappe.db.get_value(
			"CRM Staff", staff_context["staff_by_user"]["nguyen.minh.khoi@gmail.com"], "department"
		)
		staff, _ = _ensure_target_account(base["campus"], department, teams)
		province = base["province"]
		schools: dict[str, str] = {}
		for profile in PROFILES:
			zone = zone_ids[profile["zone"]]
			ward = ward_ids[profile["ward"]]
			schools[profile["school_code"]] = _ensure_school(
				profile,
				province,
				ward,
				zone,
				teams["B"] if profile["zone"] == "central" else teams["A"],
				staff,
			)
		frappe.db.commit()

		results = []
		for profile in PROFILES:
			ward = ward_ids[profile["ward"]]
			context = _profile_context(base, profile, ward)
			item = _seed_student(
				profile,
				context,
				pools["B"] if profile["zone"] == "central" else pools["A"],
				schools[profile["school_code"]],
				staff,
				teams["B"] if profile["zone"] == "central" else teams["A"],
			)
			ai = _ensure_ai_insight(item, profile)
			analysis = _ensure_student_analysis(item, profile)
			nba = _ensure_nba(item, profile)
			results.append({**item, "ai_insight": ai, "analysis": analysis, "nba": nba})
			frappe.db.commit()

		result = {
			"ok": True,
			"namespace": NAMESPACE,
			"login": {"email": TARGET_EMAIL, "password": PASSWORD, "role": "Sale"},
			"topology": {
				"campus": base["campus"],
				"cluster": assignment["cluster"],
				"zones": {
					key: frappe.db.get_value("CRM Zone", value, "zone_name")
					for key, value in zone_ids.items()
				},
				"teams": {
					key: frappe.db.get_value("CRM Team", value, "team_name") for key, value in teams.items()
				},
				"pools": {
					key: frappe.db.get_value("CRM Student Pool", value, "pool_name")
					for key, value in pools.items()
				},
				"staff": staff,
				"students": results,
			},
		}
		print(frappe.as_json(result))
		return result


def verify() -> dict[str, Any]:
	"""Read-only verification for the fixture and its dependent DocTypes."""
	_assert_local_site()
	rows = frappe.get_all(
		"CRM Student",
		filters={"import_source_id": ["like", f"{NAMESPACE}:%"]},
		fields=[
			"name",
			"student_name",
			"email",
			"owner_staff",
			"owning_team",
			"owning_pool",
			"high_school",
			"lifecycle_stage",
		],
		order_by="creation asc",
		limit_page_length=0,
	)
	student_names = [row.name for row in rows]
	counts = {}
	for doctype, field in (
		("CRM Contact", "student"),
		("CRM Interaction", "student"),
		("CRM Intent", "student"),
		("CRM Student Outcome", "student"),
		("CRM Student Assessment", "student"),
		("CRM Score History", "student"),
		("CRM AI Lead Insight", "student"),
		("CRM Student Analysis Run", "student"),
		("CRM NBA Evaluation", "student"),
		("CRM Recommendation", "target_id"),
		("CRM Action Item", "student"),
		("CRM Admission Application", "student"),
		("CRM Student Guardian", "student"),
		("CRM Parent Contact Authority", "student"),
	):
		counts[doctype] = frappe.db.count(doctype, {field: ["in", student_names]}) if student_names else 0
	contact_names = (
		frappe.get_all(
			"CRM Contact", filters={"student": ["in", student_names]}, pluck="name", limit_page_length=0
		)
		if student_names
		else []
	)
	counts["CRM Contact Consent Event"] = (
		frappe.db.count("CRM Contact Consent Event", {"contact": ["in", contact_names]})
		if contact_names
		else 0
	)
	recommendations = frappe.get_all(
		"CRM Recommendation",
		filters={"target_id": ["in", student_names]} if student_names else {"name": "__none__"},
		fields=["name", "target_id", "rank", "decision_status", "execution_status", "action"],
		order_by="target_id asc, rank asc",
		limit_page_length=0,
	)
	result = {
		"ok": len(rows) == len(PROFILES) and all(row.owner_staff for row in rows),
		"target_sale": frappe.db.get_value(
			"CRM Staff", {"user": TARGET_EMAIL}, ["name", "full_name", "user", "is_active"], as_dict=True
		),
		"students": rows,
		"counts": counts,
		"recommendations": recommendations,
	}
	print(frappe.as_json(result))
	return result


def _ensure_nba_policy() -> None:
	"""Publish the deterministic decision policy required by NBA evaluations."""
	if frappe.db.exists("CRM NBA Decision Policy", {"policy_key": "default"}):
		return
	frappe.get_doc(
		{
			"doctype": "CRM NBA Decision Policy",
			"policy_key": "default",
			"is_active": 1,
			"top_n": 3,
			"max_recommendations": 10,
			"min_score_threshold": 0,
			"score_weights": json.dumps({"intent": 1, "readiness": 1, "engagement": 1}),
			"conflict_key_fields": json.dumps(["student", "action"]),
			"diversity_rule": "unique_action_type",
			"effective_from": datetime.now(),
		}
	).insert(ignore_permissions=True)
