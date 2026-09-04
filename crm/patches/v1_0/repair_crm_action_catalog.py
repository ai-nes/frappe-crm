"""Repair partially migrated action data and install the canonical catalog."""

import frappe

from crm.fcrm.action_type_catalog import (
	ACTION_TYPE_CODES,
	action_category,
	canonicalize_action_type,
)
from crm.patches.v1_0.seed_crm_action_type import execute as seed_action_catalog

ACTION_ITEM_DOCTYPE = "CRM Action Item"
ACTION_REFERENCE_DOCTYPES = (
	"CRM Action Execution Attempt",
	"CRM Action Execution",
	"CRM Action Revision",
	"CRM Action Outcome",
	"CRM Student Dispatch Receipt",
	"CRM Student Decision Event",
)


def execute():
	"""Make the patch safe for sites that ran an earlier action seed."""
	if not frappe.db.exists("DocType", ACTION_ITEM_DOCTYPE):
		return

	seed_action_catalog()
	legacy_actions, action_codes = _migrate_legacy_action_rows()
	_update_action_references(legacy_actions)
	_backfill_recommendation_actions(legacy_actions, action_codes)
	_delete_legacy_action_rows(legacy_actions)

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()


def _migrate_legacy_action_rows():
	rows = frappe.db.sql(
		"select * from `tabCRM Action` where code is null or code = ''",
		as_dict=True,
	)
	valid_item_fields = {field.fieldname for field in frappe.get_meta(ACTION_ITEM_DOCTYPE).fields}
	legacy_actions = {}
	action_codes = {}

	for row in rows:
		legacy_name = row.name
		legacy_code = row.get("action_type")
		if not legacy_code and row.get("nba_action") and frappe.db.exists("CRM Action Definition", row.nba_action):
			legacy_code = frappe.db.get_value("CRM Action Definition", row.nba_action, "code")
		canonical_code = canonicalize_action_type(legacy_code)
		if canonical_code not in ACTION_TYPE_CODES:
			canonical_code = None
		if row.get("disposition") != "ACT":
			canonical_code = None

		payload = {"doctype": ACTION_ITEM_DOCTYPE, "name": legacy_name}
		for fieldname in valid_item_fields - {"action", "action_type"}:
			if fieldname in row:
				payload[fieldname] = row[fieldname]
		payload["action"] = canonical_code
		payload["action_type"] = action_category(canonical_code)

		item_name = frappe.db.exists(ACTION_ITEM_DOCTYPE, legacy_name)
		if not item_name:
			item_name = frappe.get_doc(payload).insert(ignore_permissions=True).name
		else:
			frappe.db.set_value(
				ACTION_ITEM_DOCTYPE,
				item_name,
				{"action": canonical_code, "action_type": action_category(canonical_code)},
				update_modified=False,
			)
		legacy_actions[legacy_name] = item_name
		action_codes[legacy_name] = canonical_code

	return legacy_actions, action_codes


def _update_action_references(legacy_actions):
	for doctype in ACTION_REFERENCE_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		for old_name, new_name in legacy_actions.items():
			if old_name != new_name:
				frappe.db.set_value(doctype, {"action": old_name}, "action", new_name, update_modified=False)


def _backfill_recommendation_actions(legacy_actions, action_codes):
	if not frappe.db.exists("DocType", "CRM Recommendation"):
		return
	for row in frappe.get_all(
			"CRM Recommendation",
			fields=["name", "action", "recommended_action"],
			limit_page_length=0,
		):
		candidate = action_codes.get(row.action) or canonicalize_action_type(row.action)
		if candidate not in ACTION_TYPE_CODES:
			candidate = canonicalize_action_type(row.recommended_action)
		if candidate in ACTION_TYPE_CODES and frappe.db.exists("CRM Action", candidate):
			frappe.db.set_value("CRM Recommendation", row.name, "action", candidate, update_modified=False)


def _delete_legacy_action_rows(legacy_actions):
	for legacy_name in legacy_actions:
		frappe.db.delete("CRM Action", legacy_name)
