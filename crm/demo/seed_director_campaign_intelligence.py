"""Idempotent campaign-intelligence fixtures for the Director dashboard."""

from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
from typing import Any

import frappe

from crm.fcrm.campaign_performance_fact import record_performance_fact

NAMESPACE = "crm-demo-showcase:director-campaign-intelligence"
CHANNELS = ("Facebook Ads", "Google Search", "Zalo OA")


def seed(context: dict[str, Any], marketing: dict[str, Any]) -> dict[str, Any]:
	"""Seed realistic weekly observations against showcase campaigns."""

	required = ("CRM Campaign Performance Fact", "CRM Campaign Channel Assignment", "CRM Platform")
	if not all(frappe.db.table_exists(doctype) for doctype in required):
		return {"status": "skipped", "reason": "campaign_intelligence_doctypes_unavailable"}
	campaigns = list(marketing.get("campaigns") or [])[: len(CHANNELS)]
	if not campaigns:
		return {"status": "skipped", "reason": "showcase_campaigns_unavailable"}

	year = str(context["admission_year"])
	platforms = [_ensure_platform(channel, context["source"]) for channel in CHANNELS[: len(campaigns)]]
	assignments = [
		_ensure_channel_assignment(campaign, platform, year)
		for campaign, platform in zip(campaigns, platforms, strict=True)
	]
	created_or_replayed = 0
	for campaign_index, (campaign, assignment) in enumerate(zip(campaigns, assignments, strict=True)):
		for week_index, observation in enumerate(_weekly_observations(campaign_index)):
			week_start = date(int(year), 8, 3) + timedelta(days=week_index * 7)
			record_performance_fact(
				campaign=campaign,
				channel_assignment=assignment,
				period_start=week_start.isoformat(),
				period_end=(week_start + timedelta(days=6)).isoformat(),
				timezone="Asia/Ho_Chi_Minh",
				source_system="demo-seed",
				ingestion_run=NAMESPACE,
				source_key=f"{campaign}:{week_start.isoformat()}",
				dimension_values={"campus": context["campus"]},
				measures=observation,
			)
			created_or_replayed += 1
	_attributions = _ensure_attributions(campaigns, year)
	frappe.db.commit()
	return {
		"status": "available",
		"campaigns": len(campaigns),
		"facts": created_or_replayed,
		"attributions": _attributions,
	}


def execute() -> dict[str, Any]:
	"""Seed only Campaign Intelligence fixtures on a prepared local demo site."""
	# Reuse the showcase's local-only flags so governed references still pass
	# through their command boundary when this seed is run standalone.
	from crm.demo.seed_showcase import _temporary_local_flags

	with _temporary_local_flags():
		years = frappe.get_all(
			"CRM Admission Year", filters={"is_active": 1}, fields=["name", "year_name"], limit_page_length=2
		)
		if len(years) != 1:
			raise frappe.ValidationError(
				"Campaign Intelligence seed requires exactly one active admission year."
			)
		campaigns = frappe.get_all(
			"CRM Campaign",
			filters={"status": ["in", ["Active", "Approved", "Completed"]]},
			fields=["name", "campus"],
			order_by="start_date desc, name asc",
			limit_page_length=len(CHANNELS),
		)
		source = frappe.db.get_value("CRM Lead Source", {"approval_state": "Approved"}, "name")
		if not campaigns or not source or not campaigns[0].get("campus"):
			raise frappe.ValidationError(
				"Campaign Intelligence seed requires prepared campaign, campus, and lead source data."
			)
		return seed(
			{
				"admission_year": years[0].get("year_name") or years[0]["name"],
				"campus": campaigns[0]["campus"],
				"source": source,
			},
			{"campaigns": [row["name"] for row in campaigns]},
		)


def _ensure_platform(channel: str, source: str) -> str:
	from crm.fcrm.master_data_governance import create_additive_value

	name = f"Demo Campaign Intelligence {channel}"
	if frappe.db.exists("CRM Platform", name):
		return name
	result = create_additive_value(
		"CRM Platform",
		name,
		reason="Canonical platform used by the Campaign Intelligence demo.",
		idempotency_key=f"{NAMESPACE}:platform:{channel}",
		correlation_id=NAMESPACE,
		lead_source=source,
	)
	return result["name"]


def _ensure_channel_assignment(campaign: str, platform: str, year: str) -> str:
	source_reference = f"{NAMESPACE}:channel:{campaign}"
	existing = frappe.db.get_value(
		"CRM Campaign Channel Assignment", {"source_reference": source_reference}, "name"
	)
	values = {
		"campaign": campaign,
		"channel": platform,
		"effective_from": f"{year}-01-01",
		"effective_until": f"{year}-12-31",
		"is_active": 1,
		"source_reference": source_reference,
	}
	if existing:
		doc = frappe.get_doc("CRM Campaign Channel Assignment", existing)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return doc.name
	return (
		frappe.get_doc({"doctype": "CRM Campaign Channel Assignment", **values})
		.insert(ignore_permissions=True)
		.name
	)


def _weekly_observations(campaign_index: int) -> list[dict[str, int]]:
	"""Keep each campaign distinct so recommendations have a meaningful basis."""
	profiles = (
		(420_000, 18_000, 1_050, 710, 132, 72, 34, 12, 145_000, 240_000),
		(300_000, 14_000, 720, 500, 82, 39, 18, 5, 38_000, 96_000),
		(260_000, 10_000, 590, 430, 74, 46, 22, 8, 84_000, 132_000),
	)
	spend, impressions, clicks, visits, leads, qualified, applications, enrolled, revenue, pipeline = (
		profiles[campaign_index]
	)
	return [
		{
			"spend": spend + week * 8_000,
			"impressions": impressions + week * 500,
			"clicks": clicks + week * 25,
			"leads": leads + week * 4,
			"applications": applications + week,
			"enrolled": enrolled + (1 if week == 3 and campaign_index != 1 else 0),
			"landing_visits": visits + week * 20,
			"qualified_leads": qualified + week * 2,
			"confirmed_revenue": revenue + week * 12_000,
			"pipeline_revenue": pipeline + week * 20_000,
		}
		for week in range(4)
	]


def _ensure_attributions(campaigns: list[str], year: str) -> int:
	students = frappe.get_all(
		"CRM Lead",
		filters={"import_source_id": ["like", "crm-demo-showcase:%"]},
		pluck="name",
		order_by="name asc",
		limit_page_length=len(campaigns),
	)
	created = 0
	for index, (campaign, student) in enumerate(zip(campaigns, students, strict=False)):
		fingerprint = _fingerprint(campaign, student)
		if frappe.db.exists("CRM Campaign Attribution", {"idempotency_fingerprint": fingerprint}):
			continue
		frappe.get_doc(
			{
				"doctype": "CRM Campaign Attribution",
				"student": student,
				"campaign": campaign,
				"weight": 1,
				"attributed_at": f"{year}-08-{10 + index:02d} 10:00:00",
				"source_kind": "observed",
				"confidence": (92, 58, 78)[index],
				"source_reference": f"{NAMESPACE}:attribution:{campaign}",
				"idempotency_fingerprint": fingerprint,
			}
		).insert(ignore_permissions=True)
		created += 1
	return created


def _fingerprint(campaign: str, student: str) -> str:
	return sha256(f"{NAMESPACE}|{campaign}|{student}".encode()).hexdigest()
