"""Remove legacy AI insight tables after the DocTypes have been renamed."""

from __future__ import annotations

import frappe

from crm.patches.v1_0.rename_ai_lead_insight_to_student_insight import _drop_legacy_table

LEGACY_TABLES = (
	("CRM AI Lead Insight Item", "CRM AI Student Insight Item"),
	("CRM AI Lead Insight", "CRM AI Student Insight"),
)


def execute():
	for old, new in LEGACY_TABLES:
		if frappe.db.exists("DocType", old):
			continue
		if not frappe.db.exists("DocType", new):
			continue
		_drop_legacy_table(old, new)
