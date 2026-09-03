"""Add idempotency lookup indexes for governed Action Attempts."""
import frappe


def execute():
	if not frappe.db.exists("DocType", "CRM Action Execution Attempt"):
		return
	table = "`tabCRM Action Execution Attempt`"
	for name, columns in {
		"crm_attempt_action_idem_uniq": "(`action`, `idempotency_key`)",
		"crm_attempt_provider_event_idx": "(`provider_event_id`)",
	}.items():
		if not frappe.db.sql("show indexes from " + table + " where Key_name=%s", name):
			frappe.db.sql(f"alter table {table} add {'unique ' if name.endswith('_uniq') else ''}index `{name}` {columns}")
