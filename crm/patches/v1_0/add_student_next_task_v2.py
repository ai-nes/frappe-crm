"""Forward-only schema/index guard for Student next-task v2."""

import frappe


def execute():
	for doctype in (
		"CRM Student",
		"CRM Agent Event",
		"CRM Student Context Change",
		"CRM Parent Contact Authority",
	):
		frappe.reload_doc("fcrm", "doctype", frappe.scrub(doctype))
	# Student Task was an intermediate admissions aggregate.  Upgrades from
	# older sites may still have its table, but fresh installs must not require
	# the deleted DocType to complete migration.
	# Do not reload the deleted DocType.  If an upgrade still has its table,
	# the dedicated migration patch below reads it with SQL/API only.
	# Frappe creates DocType indexes during model sync; these explicit indexes
	# make existing sites converge without rewriting any evidence rows.
	frappe.db.add_index(
		"CRM Student", ["student_context_revision"], index_name="student_context_revision_idx"
	)
	frappe.db.add_index(
		"CRM Agent Event",
		["aggregate_doctype", "aggregate_name", "contract_version", "source_revision_bigint"],
		index_name="agent_event_v2_revision_idx",
	)
	if frappe.db.table_exists("CRM Student Task"):
		_ensure_unique_index("CRM Student Task", "student_task_current_slot_idx", ["student", "current_slot"])
		_ensure_unique_index(
			"CRM Student Task",
			"student_task_idempotency_idx",
			["producer_identity", "student", "generation_idempotency_key"],
		)
	for student in frappe.get_all("CRM Student", pluck="name"):
		if frappe.db.get_value("CRM Student", student, "student_context_revision") is None:
			frappe.db.set_value("CRM Student", student, "student_context_revision", 0, update_modified=False)


def _ensure_unique_index(doctype, index_name, fields):
	"""MariaDB-safe idempotent unique index creation."""
	if frappe.db.sql(
		"SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s LIMIT 1",
		(f"tab{doctype}", index_name),
	):
		return
	columns = ", ".join(f"`{field}`" for field in fields)
	frappe.db.sql(f"ALTER TABLE `tab{doctype}` ADD UNIQUE KEY `{index_name}` ({columns})")
