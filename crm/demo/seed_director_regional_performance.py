"""Idempotent province targets for the Director regional-performance dashboard."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from math import ceil
from typing import Any

import frappe

NAMESPACE = "crm-demo-showcase:director-regional-performance"


def recommended_target(*, applications: int, enrollments: int) -> int:
	"""Return a meaningful but attainable target for one seeded province."""
	return max(enrollments + max(1, ceil(applications * 0.15)), 1)


def seed(context: dict[str, Any]) -> dict[str, Any]:
	"""Create one approved annual enrollment target per seeded province."""
	if not all(
		frappe.db.table_exists(doctype) for doctype in ("CRM Planning Scope", "CRM Target", "CRM Lead")
	):
		return {"status": "skipped", "reason": "regional_target_doctypes_unavailable"}

	year = str(context["admission_year"])
	metrics = _province_metrics(year)
	created = updated = 0
	for province, values in metrics.items():
		scope = _ensure_province_scope(province, year)
		_ensure_regional_workforce(province, year, values)
		result = _ensure_target(scope, province, year, recommended_target(**values))
		if result == "created":
			created += 1
		else:
			updated += 1
	frappe.db.commit()
	return {
		"status": "available",
		"provinces": len(metrics),
		"targets_created": created,
		"targets_updated": updated,
	}


def _ensure_regional_workforce(province: str, year: str, metrics: dict[str, int]) -> None:
	"""Seed one advisor and a throughput target owned by one province territory."""
	territory = _ensure_territory(province, year)
	_ensure_geography_assignment(territory, province, year)
	staff = _ensure_advisor(province, territory)
	open_workload = max(metrics["applications"] - metrics["enrollments"], 1)
	desired_capacity = 72 + (sum(ord(char) for char in province) % 19)
	staff.target = ceil(open_workload / (desired_capacity / 100))
	staff.territory = territory
	staff.is_active = 1
	staff.save(ignore_permissions=True)


def _ensure_territory(province: str, year: str) -> str:
	name = f"Demo regional {province}"
	if frappe.db.exists("CRM Territory", name):
		return name
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Territory",
				"territory_name": name,
				"territory_code": f"DEMO-RP-{_stable_number(province):05d}",
				"effective_from": f"{year}-01-01",
				"effective_until": f"{year}-12-31",
				"is_active": 1,
				"source_reference": f"{NAMESPACE}:territory:{province}",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_geography_assignment(territory: str, province: str, year: str) -> None:
	source_reference = f"{NAMESPACE}:territory-geography:{province}"
	if frappe.db.exists("CRM Territory Geography Assignment", {"source_reference": source_reference}):
		return
	frappe.get_doc(
		{
			"doctype": "CRM Territory Geography Assignment",
			"business_key": f"{territory}|Province|{province}|{year}-01-01|1",
			"territory": territory,
			"geography_type": "Province",
			"geography": province,
			"effective_from": f"{year}-01-01",
			"effective_until": f"{year}-12-31",
			"status": "Active",
			"source_reference": source_reference,
		}
	).insert(ignore_permissions=True)


def _ensure_advisor(province: str, territory: str):
	index = _stable_number(province)
	email = f"demo.regional.advisor.{index}@example.test"
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Demo Regional Advisor",
				"user_type": "System User",
				"enabled": 1,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	staff_name = frappe.db.get_value("CRM Staff", {"user": email}, "name")
	if staff_name:
		return frappe.get_doc("CRM Staff", staff_name)
	base = frappe.get_all(
		"CRM Staff", filters={"is_active": 1}, fields=["campus", "department"], limit_page_length=1
	)
	if not base or not base[0].get("campus") or not base[0].get("department"):
		raise frappe.ValidationError("Regional performance seed requires one active CRM Staff baseline.")
	return frappe.get_doc(
		{
			"doctype": "CRM Staff",
			"full_name": f"Demo Regional Advisor {index}",
			"user": email,
			"campus": base[0]["campus"],
			"department": base[0]["department"],
			"territory": territory,
			"is_active": 1,
		}
	).insert(ignore_permissions=True)


def _province_metrics(year: str) -> dict[str, dict[str, int]]:
	rows = frappe.get_all(
		"CRM Lead",
		filters={"admission_year": year, "import_source_id": ["like", "crm-demo-showcase:%"]},
		fields=["province", "lifecycle_stage", "enrollment_status"],
		limit_page_length=0,
	)
	result: dict[str, dict[str, int]] = defaultdict(lambda: {"applications": 0, "enrollments": 0})
	for row in rows:
		province = row.get("province")
		if not province:
			continue
		result[province]["applications"] += 1
		if _is_enrolled(row):
			result[province]["enrollments"] += 1
	return dict(result)


def _ensure_province_scope(province: str, year: str) -> str:
	scope_key = f"province:{province}"
	existing = frappe.db.get_value("CRM Planning Scope", {"scope_key": scope_key}, "name")
	values = {
		"province": province,
		"effective_from": f"{year}-01-01",
		"effective_until": f"{year}-12-31",
		"status": "Approved",
		"source_reference": f"{NAMESPACE}:scope:{province}",
	}
	if existing:
		doc = frappe.get_doc("CRM Planning Scope", existing)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return doc.name
	return (
		frappe.get_doc({"doctype": "CRM Planning Scope", "scope_key": scope_key, **values})
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_target(scope: str, province: str, year: str, target_value: int) -> str:
	source_reference = f"{NAMESPACE}:target:{year}:{province}"
	values = {
		"admission_year": year,
		"period_type": "Annual",
		"period_start": f"{year}-01-01",
		"period_end": f"{year}-12-31",
		"metric_key": "enrollment",
		"planning_scope": scope,
		"target_value": target_value,
		"status": "Approved",
		"version": 1,
		"effective_from": f"{year}-01-01",
		"effective_until": f"{year}-12-31",
		"source_reference": source_reference,
	}
	existing = frappe.db.get_value("CRM Target", {"source_reference": source_reference}, "name")
	if existing:
		doc = frappe.get_doc("CRM Target", existing)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return "updated"
	frappe.get_doc({"doctype": "CRM Target", **values}).insert(ignore_permissions=True)
	return "created"


def _is_enrolled(row: dict[str, Any]) -> bool:
	return (
		str(row.get("lifecycle_stage") or "").casefold() == "enrolled"
		or "nhập học" in str(row.get("enrollment_status") or "").casefold()
	)


def _stable_number(value: str) -> int:
	return int(sha256(value.encode()).hexdigest()[:8], 16) % 100000
