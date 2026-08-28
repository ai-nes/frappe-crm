import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	"DocType": [
		{
			"fieldname": "custom_ai_exposed",
			"fieldtype": "Check",
			"label": "AI Exposed",
			"default": "0",
			"description": "Whether this DocType is discoverable/servable through the crm-agents "
			"Capability Gateway. Changing this requires the System Manager role.",
			"insert_after": "custom",
		}
	],
	"Role": [
		{
			"fieldname": "custom_ai_capability_grants",
			"fieldtype": "Table",
			"label": "AI Capability Grants",
			"options": "CRM AI Capability Grant",
			"description": "Semantic-capability and data-scope names granted to this role for the "
			"crm-agents Capability Gateway (no DocType-backed permission exists for these).",
			"insert_after": "disabled",
		}
	],
}


def execute():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True, update=True)
	# DocType is a core meta-table whose columns aren't derived from its
	# custom fields the way an ordinary doctype's are, so create_custom_fields()
	# leaves the Custom Field record inserted but `tabDocType` itself still
	# missing the `custom_ai_exposed` column — add it directly, guarded so
	# reruns of this patch stay idempotent.
	if not frappe.db.has_column("DocType", "custom_ai_exposed"):
		frappe.db.sql_ddl(
			"ALTER TABLE `tabDocType` ADD COLUMN `custom_ai_exposed` INT(1) NOT NULL DEFAULT 0"
		)
	_seed_exposed_crm_doctypes()


def _seed_exposed_crm_doctypes():
	# The crm-agents schema fetcher and capability gateway both switched their
	# exposure filter from a `CRM%` name prefix to `custom_ai_exposed = 1` in
	# the same release as this patch — without this seed, every previously
	# CRM%-exposed doctype would silently disappear from both on deploy.
	# Child tables and Single doctypes (including this feature's own `CRM AI
	# Capability Grant` child table) are excluded: the old `CRM%` prefix
	# filter predates the capability manifest and was never meant to publish
	# a doctype's own grant-storage table as an AI-visible resource.
	# `COALESCE` guards against a NULL custom_ai_exposed value, which is
	# distinct from 0 and would otherwise silently skip the row.
	frappe.db.sql(
		"UPDATE `tabDocType` SET custom_ai_exposed = 1 "
		"WHERE name LIKE 'CRM%' AND name NOT IN ('CRM Student', 'CRM Intent', 'CRM Interaction') "
		"AND istable = 0 AND issingle = 0 "
		"AND COALESCE(custom_ai_exposed, 0) != 1"
	)
