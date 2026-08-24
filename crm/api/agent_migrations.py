"""Idempotent expand/backfill work for the local agent integration."""
import frappe


SALES_WORKLIST_ROLE_NAMES = ("Sale", "Lead Sales", "CTV-Sale", "Counseller", "Team Leader")


def after_migrate() -> None:
	"""Backfill sortable projections and add the hot-path composite indexes."""
	frappe.db.sql(
		"""
		UPDATE `tabCRM Recommendation`
		SET worklist_priority_rank = CASE priority
			WHEN 'high' THEN 0 WHEN 'medium' THEN 1 WHEN 'low' THEN 2 ELSE 99 END,
			worklist_timing_sort = COALESCE(recommended_timing, '9999-12-31 23:59:59.999999')
		WHERE worklist_priority_rank IS NULL OR worklist_priority_rank = 99
			OR worklist_timing_sort IS NULL OR worklist_timing_sort = '9999-12-31 23:59:59'
		"""
	)
	frappe.db.add_index(
		"CRM Recommendation",
		["worklist_priority_rank", "worklist_timing_sort", "creation", "name"],
		"crm_recommendation_worklist_idx",
	)
	frappe.db.add_index(
		"CRM Agent Event", ["status", "next_attempt_at", "creation"], "crm_agent_event_retry_idx"
	)
	_grant_sales_worklist_capability()


def _grant_sales_worklist_capability() -> None:
	"""Seed least-privilege read capabilities for verified CRM copilot roles."""
	# This is a Table field, stored in its child DocType rather than as a
	# column on tabRole.  `db.has_column` would therefore always return False.
	if not frappe.get_meta("Role").has_field("custom_ai_capability_grants"):
		return
	changed = False
	for role_name in SALES_WORKLIST_ROLE_NAMES:
		if not frappe.db.exists("Role", role_name):
			continue
		role = frappe.get_doc("Role", role_name)
		if any(
			row.grant_type == "semantic_capability" and row.value == "sales_intelligence.worklist.read"
			for row in role.custom_ai_capability_grants
		):
			continue
		role.append(
			"custom_ai_capability_grants",
			{"grant_type": "semantic_capability", "value": "sales_intelligence.worklist.read"},
		)
		role.save(ignore_permissions=True)
		changed = True
	for role_name in ("Promoter-PR", "Team Leader", "Admissions Director"):
		if not frappe.db.exists("Role", role_name):
			continue
		role = frappe.get_doc("Role", role_name)
		if any(
			row.grant_type == "semantic_capability" and row.value == "admissions_analytics.pipeline_summary.read"
			for row in role.custom_ai_capability_grants
		):
			continue
		role.append(
			"custom_ai_capability_grants",
			{"grant_type": "semantic_capability", "value": "admissions_analytics.pipeline_summary.read"},
		)
		role.save(ignore_permissions=True)
		changed = True
	if changed:
		# This helper is invoked by a one-shot migration command as well as
		# hooks.  Persist the grant before the command returns, otherwise a
		# fresh worker sees an unchanged manifest after the implicit rollback.
		frappe.db.commit()
		frappe.clear_cache()
