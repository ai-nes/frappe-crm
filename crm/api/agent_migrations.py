"""Idempotent expand/backfill work for the local agent integration."""
import frappe


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
	"""Seed the least-privilege read capability for verified Sales roles."""
	if not frappe.db.has_column("Role", "custom_ai_capability_grants"):
		return
	for role_name in ("Sale", "CTV-Sale", "Counseller", "Team Leader"):
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
