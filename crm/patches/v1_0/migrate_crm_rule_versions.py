"""Backfill legacy CRM Rules into the versioned rule registry."""

from __future__ import annotations

import frappe

from crm.fcrm.rule_engine import active_rule_catalog


LEGACY_VERSION_ID = "LEGACY-V1"


def execute():
	if not frappe.db.exists("DocType", "CRM Rule Version"):
		return

	rows = frappe.db.sql(
		"""
		SELECT name FROM `tabCRM Rule`
		WHERE rule_version IS NULL OR rule_version = ''
		ORDER BY creation, name
		""",
		as_dict=True,
	)
	if not rows:
		return

	version = frappe.db.exists("CRM Rule Version", LEGACY_VERSION_ID)
	if not version:
		version = frappe.new_doc("CRM Rule Version")
		version.version_id = LEGACY_VERSION_ID
		version.version_name = "Legacy CRM Rules"
		version.description = "Rules migrated from the pre-versioned CRM Rule registry."
		version.status = "draft"
		version.is_active = 0
		version.revision = 0
		version.insert(ignore_permissions=True)
		version = version.name

	for row in rows:
		frappe.db.set_value("CRM Rule", row.name, "rule_version", version, update_modified=False)

	rule_rows = frappe.get_all(
		"CRM Rule",
		filters={"rule_version": version},
		fields=[
			"rule_id",
			"rule_group",
			"rule_name",
			"description",
			"feature_scope",
			"rule_type",
			"gate_outcome",
			"priority",
			"action",
			"target_actions",
			"condition",
			"revision",
			"schema_version",
			"status",
			"enabled",
		],
		limit_page_length=1000,
	)
	has_published_rules = any(row.status == "published" and row.enabled for row in rule_rows)
	active_version = frappe.db.get_value("CRM Rule Version", {"is_active": 1}, "name")
	set_active = bool(has_published_rules and not active_version)
	status = "published" if has_published_rules else "draft"
	metadata = active_rule_catalog(rule_rows)
	frappe.db.set_value(
		"CRM Rule Version",
		version,
		{
			"status": status,
			"is_active": int(set_active),
			"ruleset_revision": metadata["ruleset_revision"],
			"ruleset_digest": metadata["ruleset_digest"],
		},
		update_modified=False,
	)
