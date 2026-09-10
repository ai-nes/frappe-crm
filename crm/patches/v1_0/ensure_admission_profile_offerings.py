"""Ensure the admission profile UI has an active offering for each catalog method."""

from __future__ import annotations

import frappe

from crm.fcrm.admission_offering import approve_offering


def _date(value, year: str, end: bool = False) -> str:
	if value:
		return str(value)
	return f"{year}-12-31" if end else f"{year}-01-01"


def execute():
	years = frappe.get_all(
		"CRM Admission Year",
		filters={"is_active": 1},
		fields=["name", "year_name", "start_date", "end_date"],
		limit_page_length=0,
	)
	campuses = frappe.get_all("CRM Campus", fields=["name"], limit_page_length=0)
	majors = frappe.get_all("CRM Major", fields=["name"], limit_page_length=0)
	methods = frappe.get_all(
		"CRM Admission Method",
		filters={"enabled": 1},
		fields=["name"],
		limit_page_length=0,
	)

	for year in years:
		year_label = str(year.year_name or year.name)
		for campus in campuses:
			for major in majors:
				for method in methods:
					filters = {
						"admission_year": year.name,
						"campus": campus.name,
						"major": major.name,
						"admission_method": method.name,
					}
					active = frappe.db.get_value(
						"CRM Admission Offering", {**filters, "status": "Active"}, "name"
					)
					if active:
						continue

					offering_key = "admission-profile-catalog:{0}:{1}:{2}:{3}".format(
						year.name, campus.name, major.name, method.name
					)
					offering_name = frappe.db.get_value(
						"CRM Admission Offering", {"offering_key": offering_key}, "name"
					)
					if offering_name:
						offering = frappe.get_doc("CRM Admission Offering", offering_name)
					else:
						offering = frappe.get_doc(
							{
								"doctype": "CRM Admission Offering",
								"offering_key": offering_key,
								**filters,
								"quota": 500,
								"effective_from": _date(year.start_date, year_label),
								"effective_until": _date(year.end_date, year_label, end=True),
								"status": "Draft",
								"policy_version": "admission-profile-catalog-v1",
								"source_reference": offering_key,
							}
						).insert(ignore_permissions=True)

					if offering.status != "Active":
						approve_offering(
							offering=offering.name,
							idempotency_key=f"{offering_key}:approval",
						)
