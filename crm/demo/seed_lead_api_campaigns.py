"""Idempotently seed campaigns used by the public Lead API example."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import frappe

LEAD_API_CAMPAIGNS: tuple[dict[str, Any], ...] = (
	{
		"code": "CAM-2026-00001",
		"title": "Lead API 2026 - Website",
		"utm_source": "website",
		"utm_medium": "organic",
		"utm_campaign": "lead-api-website-2026",
	},
	{
		"code": "CAM-2026-00002",
		"title": "Lead API 2026 - Facebook",
		"utm_source": "facebook",
		"utm_medium": "paid_social",
		"utm_campaign": "lead-api-facebook-2026",
	},
	{
		"code": "CAM-2026-00003",
		"title": "Lead API 2026 - Open Day",
		"utm_source": "open_day",
		"utm_medium": "offline",
		"utm_campaign": "lead-api-open-day-2026",
	},
	{
		"code": "CAM-2026-00004",
		"title": "Lead API 2026 - Scholarship",
		"utm_source": "scholarship",
		"utm_medium": "referral",
		"utm_campaign": "lead-api-scholarship-2026",
	},
)


def _resolve_campus(campus: str | None) -> str:
	if campus:
		campus_name = campus if frappe.db.exists("CRM Campus", campus) else None
		campus_name = campus_name or frappe.db.get_value("CRM Campus", {"campus_name": campus}, "name")
		if campus_name:
			return campus_name
		frappe.throw(f"CRM Campus không tồn tại: {campus}", frappe.ValidationError)

	default_campus = frappe.db.get_value("CRM Campus", {"is_default": 1}, "name")
	if default_campus:
		return default_campus

	campuses = frappe.get_all("CRM Campus", fields=["name"], order_by="creation asc", limit_page_length=1)
	if campuses:
		return campuses[0].name
	frappe.throw("Cần có ít nhất một CRM Campus trước khi seed Campaign.", frappe.ValidationError)


def _ensure_campaign(spec: dict[str, Any], campus: str) -> tuple[str, bool, str, str]:
	code = spec["code"]
	title = spec["title"]

	existing = frappe.db.get_value("CRM Campaign", {"stable_code": code}, ["name", "title"], as_dict=True)
	if existing:
		existing_code = frappe.db.get_value("CRM Campaign", existing.name, "stable_code")
		return existing.name, False, existing.title, existing_code

	existing_name = frappe.db.get_value("CRM Campaign", {"title": title}, "name")
	if existing_name:
		existing_code = frappe.db.get_value("CRM Campaign", existing_name, "stable_code")
		return existing_name, False, title, existing_code

	doc = frappe.get_doc(
		{
			"doctype": "CRM Campaign",
			"title": title,
			"campus": campus,
			"status": "ACTIVE",
			"start_date": "2026-01-01",
			"end_date": "2026-12-31",
			"utm_source": spec["utm_source"],
			"utm_medium": spec["utm_medium"],
			"utm_campaign": spec["utm_campaign"],
			"notes": "Seeded for the public create_public_lead API.",
		}
	).insert(ignore_permissions=True)

	return doc.name, True, title, doc.stable_code


def execute(
	campus: str | None = None,
	campaign_specs: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
	"""Create the four public-Lead campaigns and return their stable codes."""
	resolved_campus = _resolve_campus(campus)
	specs = tuple(campaign_specs or LEAD_API_CAMPAIGNS)
	created = 0
	campaigns = []
	for spec in specs:
		name, was_created, title, code = _ensure_campaign(spec, resolved_campus)
		created += int(was_created)
		campaigns.append({"name": name, "code": code, "title": title})

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
	return {"created": created, "existing": len(campaigns) - created, "campaigns": campaigns}
