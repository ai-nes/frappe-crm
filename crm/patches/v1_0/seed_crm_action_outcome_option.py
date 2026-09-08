"""Seed CRM Action Outcome Option rows from the crm.services.action_outcome registry."""

import frappe

from crm.fcrm.action_type_catalog import ACTION_TYPE_CATALOG
from crm.services.action_outcome import OUTCOME_DISPLAY_NAMES, allowed_outcomes, derive_decision_effects


def _insert_if_missing(doctype, name, values):
	if frappe.db.exists(doctype, name):
		return
	frappe.get_doc({"doctype": doctype, **values}).insert(ignore_permissions=True)


def execute():
	"""Replace CRM Action Outcome Option rows with the current registry vocabulary.

	The outcome vocabulary is a breaking change (no migration of old
	outcome_code data): rows seeded under a prior vocabulary are stale, not
	just missing new ones, so this clears the doctype before reseeding rather
	than only inserting what's missing.
	"""
	frappe.db.delete("CRM Action Outcome Option")
	sort_order = 0
	for code, _display_name, _category in ACTION_TYPE_CATALOG:
		for outcome_code in sorted(allowed_outcomes(code)):
			for effect in derive_decision_effects(code, outcome_code):
				sort_order += 1
				_insert_if_missing(
					"CRM Action Outcome Option",
					f"{code}-{outcome_code}-{effect.dimension}",
					{
						"action": code,
						"outcome_code": outcome_code,
						"dimension": effect.dimension,
						"effect_value": effect.value,
						"label": OUTCOME_DISPLAY_NAMES.get(outcome_code, outcome_code),
						"sort_order": sort_order,
					},
				)

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
