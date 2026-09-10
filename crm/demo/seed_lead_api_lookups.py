"""Seed the small geography and major catalog used by the public Lead form."""

from __future__ import annotations

from typing import Any

import frappe

from crm.demo.school_domain_import import DEMO_CANONICAL_PROVINCES, seed_school_seed

SCHOOLS_PER_PROVINCE = 5
PUBLIC_LEAD_MAJORS: tuple[dict[str, str], ...] = (
	{"name": "Software Engineering", "code": "SE"},
	{"name": "Artificial Intelligence", "code": "AI"},
	{"name": "Data Science", "code": "DS"},
	{"name": "Digital Marketing", "code": "DM"},
	{"name": "Business Administration", "code": "BA"},
	{"name": "Graphic Design", "code": "GD"},
)


def _ensure_major(spec: dict[str, str]) -> tuple[str, bool]:
	name = spec["name"]
	existing = frappe.db.get_value(
		"CRM Major", {"major_name": name}, ["name", "major_code", "is_active"], as_dict=True
	)
	if existing:
		updates = {}
		if not existing.major_code:
			updates["major_code"] = spec["code"]
		if not existing.is_active:
			updates["is_active"] = 1
		if updates:
			frappe.db.set_value("CRM Major", existing.name, updates, update_modified=False)
		return existing.name, False

	doc = frappe.get_doc(
		{
			"doctype": "CRM Major",
			"major_name": name,
			"major_code": spec["code"],
			"is_active": 1,
		}
	).insert(ignore_permissions=True)
	return doc.name, True


def execute() -> dict[str, Any]:
	"""Seed approximately 35 schools, related geography and public-form majors."""
	geography = seed_school_seed(
		dry_run=False,
		commit_policy="all",
		max_schools_per_province=SCHOOLS_PER_PROVINCE,
	)
	if geography.get("errors"):
		raise RuntimeError(f"Canonical school seed failed with {len(geography['errors'])} errors.")

	created = 0
	majors = []
	for spec in PUBLIC_LEAD_MAJORS:
		name, was_created = _ensure_major(spec)
		created += int(was_created)
		majors.append({"name": name, "code": spec["code"], "label": spec["name"]})

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()

	return {
		"schools_per_province": SCHOOLS_PER_PROVINCE,
		"provinces": list(DEMO_CANONICAL_PROVINCES),
		"geography": geography.get("mutations", {}),
		"majors_created": created,
		"majors_existing": len(majors) - created,
		"majors": majors,
	}
