"""Forward-only schema/index guard for score_input_revision + CAS write.

Also backfills `student_context_revision`, `sla_evidence_state`, and
`sla_evidence_observed_at` -- these were referenced throughout the earlier
outbox/SLA code but were never actually defined on the CRM Student DocType,
so every raw-SQL read/write against them would have failed at runtime on any
real site. Fixed here, in the same additive-schema patch that adds this
patch's own new fields, rather than as a silent separate fix.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "CRM Score Input Change"):
		return {"status": "revision_journal_pending"}
	for doctype in ("CRM Student", "CRM Score History", "CRM Score Input Change"):
		frappe.reload_doc("fcrm", "doctype", frappe.scrub(doctype))
	frappe.db.add_index(
		"CRM Student", ["score_input_revision"], index_name="score_input_revision_idx"
	)
	frappe.db.add_index(
		"CRM Score History",
		["source_score_input_revision", "policy_revision"],
		index_name="score_history_revision_idx",
	)
	frappe.db.add_index(
		"CRM Score Input Change", ["global_sequence"], index_name="score_input_change_seq_idx"
	)
	for student in frappe.get_all("CRM Student", pluck="name"):
		updates = {}
		for field, default in (
			("student_context_revision", 0),
			("score_input_revision", 0),
			("applied_score_input_revision", 0),
			("applied_policy_revision", 0),
			("sla_evidence_state", "unknown"),
		):
			if frappe.db.get_value("CRM Student", student, field) is None:
				updates[field] = default
		if updates:
			frappe.db.set_value("CRM Student", student, updates, update_modified=False)
