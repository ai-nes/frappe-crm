"""Idempotent finance-ledger data for the Director revenue forecast dashboard."""

from __future__ import annotations

from typing import Any

import frappe

NAMESPACE = "crm-demo-showcase:director-revenue-forecast"


def execute() -> dict[str, Any]:
	"""Seed only this dashboard dataset in a prepared local demo site."""
	year = frappe.db.get_value("CRM Admission Year", {"is_active": 1}, "year_name") or "2026"
	return seed({"admission_year": str(year)})


def seed(context: dict[str, Any]) -> dict[str, Any]:
	"""Create recognised payments and approved national targets from demo applications."""
	required = ("CRM Student Payment", "CRM Revenue Recognition", "CRM Planning Scope", "CRM Target")
	if not all(frappe.db.table_exists(doctype) for doctype in required):
		return {"status": "skipped", "reason": "revenue_forecast_doctypes_unavailable"}
	year = str(context["admission_year"])
	applications = frappe.get_all(
		"CRM Admission Application",
		filters={"admission_year": year},
		fields=["name", "student"],
		limit_page_length=6,
		order_by="creation asc",
	)
	if not applications:
		return {"status": "skipped", "reason": "admission_applications_unavailable"}
	created = 0
	for index, application in enumerate(applications):
		amount = 300_000_000 + index * 25_000_000
		discount = 10_000_000 if index % 3 == 0 else 0
		period = f"{year}-{5 + index:02d}-15"
		payment = _ensure_payment(application, index, amount, period)
		created += _ensure_recognition(payment, application, index, amount, discount, period)
	scope = _ensure_scope(year)
	_ensure_target(
		scope,
		year,
		"revenue",
		sum(300_000_000 + index * 25_000_000 for index in range(len(applications))) * 1.35,
	)
	_ensure_target(scope, year, "enrollment", max(len(applications) + 4, 12))
	frappe.db.commit()
	return {
		"status": "available",
		"payments": len(applications),
		"recognitions_created": created,
		"scope": scope,
	}


def _ensure_payment(application: Any, index: int, amount: float, period: str) -> str:
	key = f"{NAMESPACE}:payment:{application.name}"
	existing = frappe.db.get_value("CRM Student Payment", {"transaction_key": key}, "name")
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Student Payment",
				"transaction_key": key,
				"application": application.name,
				"student": application.student,
				"payment_reference": f"DEMO-RF-{index + 1:03d}",
				"amount": amount,
				"currency": "VND",
				"status": "Received",
				"received_at": f"{period} 10:00:00",
				"business_period": period,
				"timezone": "Asia/Ho_Chi_Minh",
				"source_system": "demo-seed",
				"source_run": NAMESPACE,
				"source_reference": key,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_recognition(
	payment: str, application: Any, index: int, gross: float, discount: float, period: str
) -> int:
	key = f"{NAMESPACE}:revenue:{payment}"
	if frappe.db.exists("CRM Revenue Recognition", {"ledger_entry_key": key}):
		return 0
	frappe.get_doc(
		{
			"doctype": "CRM Revenue Recognition",
			"ledger_entry_key": key,
			"payment": payment,
			"application": application.name,
			"student": application.student,
			"gross_amount": gross,
			"award_amount": discount,
			"recognized_amount": gross - discount,
			"currency": "VND",
			"status": "Recognized",
			"recognized_at": f"{period} 10:00:00",
			"recognition_period": period,
			"timezone": "Asia/Ho_Chi_Minh",
			"source_system": "demo-seed",
			"source_run": NAMESPACE,
			"verification_status": "Verified",
			"source_reference": key,
		}
	).insert(ignore_permissions=True)
	return 1


def _ensure_scope(year: str) -> str:
	key = "national"
	existing = frappe.db.get_value("CRM Planning Scope", {"scope_key": key}, "name")
	values = {
		"effective_from": f"{year}-01-01",
		"effective_until": f"{year}-12-31",
		"status": "Approved",
		"source_reference": f"{NAMESPACE}:scope",
	}
	if existing:
		doc = frappe.get_doc("CRM Planning Scope", existing)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return doc.name
	return (
		frappe.get_doc({"doctype": "CRM Planning Scope", "scope_key": key, **values})
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_target(scope: str, year: str, metric: str, value: float) -> None:
	reference = f"{NAMESPACE}:target:{year}:{metric}"
	values = {
		"admission_year": year,
		"period_type": "Annual",
		"period_start": f"{year}-01-01",
		"period_end": f"{year}-12-31",
		"metric_key": metric,
		"planning_scope": scope,
		"target_value": value,
		"status": "Approved",
		"version": 1,
		"effective_from": f"{year}-01-01",
		"effective_until": f"{year}-12-31",
		"source_reference": reference,
	}
	existing = frappe.db.get_value("CRM Target", {"source_reference": reference}, "name")
	if existing:
		doc = frappe.get_doc("CRM Target", existing)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return
	frappe.get_doc({"doctype": "CRM Target", **values}).insert(ignore_permissions=True)


def sample_amounts(count: int) -> list[int]:
	"""Expose the deterministic fixture amounts for a small contract test."""
	return [300_000_000 + index * 25_000_000 for index in range(count)]
