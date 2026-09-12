"""Idempotent expand/backfill work for the local agent integration."""

import frappe

SALES_WORKLIST_ROLE_NAMES = ("Sale", "CTV Sale", "Lead Sale")
SCHOOL360_READ_ROLE_NAMES = (
	"Sale",
	"CTV Sale",
	"Lead Sale",
	"Marketing",
	"Promoter",
	"Lead Promoter",
	"Admissions Director",
)
SCHOOL360_CAPABILITY_ID = "school360.overview.read:v1"
SCHOOL360_ROLLOUT_CONFIG_KEY = "crm_agents_school360_contract"
STUDENT360_CAPABILITY_ID = "student360.overview.read:v1"
STUDENT360_ROLLOUT_CONFIG_KEY = "crm_agents_student360_contract"
SCHOOL360_RECOMMENDATION_CAPABILITY_ID = "school360.recommendation.context.read:v1"
SCHOOL360_RECOMMENDATION_ROLLOUT_CONFIG_KEY = "crm_agents_school360_recommendation_contract"
# Retired semantic grants must not remain advertised by Frappe after the
# corresponding crm-agents tool is removed.  Keep this list explicit so a
# future capability cannot disappear silently through a broad cleanup query.
RETIRED_SEMANTIC_CAPABILITIES = ("readmodel.analytics_query",)


def after_migrate() -> None:
	"""Add indexes and grants for the active agent integration."""
	frappe.db.add_index(
		"CRM Agent Event", ["status", "next_attempt_at", "creation"], "crm_agent_event_retry_idx"
	)
	_grant_sales_worklist_capability()
	_remove_retired_capabilities()


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
	for role_name in ("Promoter", "Lead Promoter", "Admissions Director"):
		if not frappe.db.exists("Role", role_name):
			continue
		role = frappe.get_doc("Role", role_name)
		if any(
			row.grant_type == "semantic_capability"
			and row.value == "admissions_analytics.pipeline_summary.read"
			for row in role.custom_ai_capability_grants
		):
			continue
		role.append(
			"custom_ai_capability_grants",
			{"grant_type": "semantic_capability", "value": "admissions_analytics.pipeline_summary.read"},
		)
		role.save(ignore_permissions=True)
		changed = True
	# crm-agents uses the shared advisory graph for every business Copilot
	# persona. Keep this grant additive to the remote phase capabilities.
	for role_name in ("Sale", "Marketing", "Lead Sale", "Admissions Director"):
		if not frappe.db.exists("Role", role_name):
			continue
		role = frappe.get_doc("Role", role_name)
		if any(
			row.grant_type == "semantic_capability" and row.value == "knowledge_graph.query"
			for row in role.custom_ai_capability_grants
		):
			continue
		role.append(
			"custom_ai_capability_grants",
			{"grant_type": "semantic_capability", "value": "knowledge_graph.query"},
		)
		role.save(ignore_permissions=True)
		changed = True
	# Quiescence gate: operators set this site-config marker only after the
	# matching crm-agents registry/client has been deployed. This prevents a
	# Frappe-only rollout from advertising a capability the consumer cannot use.
	consumer_ready = (
		getattr(getattr(frappe, "conf", None), "get", lambda *_args: None)(SCHOOL360_ROLLOUT_CONFIG_KEY)
		== SCHOOL360_CAPABILITY_ID
	)
	student_consumer_ready = (
		getattr(getattr(frappe, "conf", None), "get", lambda *_args: None)(STUDENT360_ROLLOUT_CONFIG_KEY)
		== STUDENT360_CAPABILITY_ID
	)
	for role_name in SCHOOL360_READ_ROLE_NAMES if student_consumer_ready else ():
		if not frappe.db.exists("Role", role_name):
			continue
		role = frappe.get_doc("Role", role_name)
		if any(
			row.grant_type == "semantic_capability" and row.value == STUDENT360_CAPABILITY_ID
			for row in role.custom_ai_capability_grants
		):
			continue
		role.append(
			"custom_ai_capability_grants",
			{"grant_type": "semantic_capability", "value": STUDENT360_CAPABILITY_ID},
		)
		role.save(ignore_permissions=True)
		changed = True
	for role_name in SCHOOL360_READ_ROLE_NAMES if consumer_ready else ():
		if not frappe.db.exists("Role", role_name):
			continue
		role = frappe.get_doc("Role", role_name)
		if any(
			row.grant_type == "semantic_capability" and row.value == SCHOOL360_CAPABILITY_ID
			for row in role.custom_ai_capability_grants
		):
			continue
		role.append(
			"custom_ai_capability_grants",
			{"grant_type": "semantic_capability", "value": SCHOOL360_CAPABILITY_ID},
		)
		role.save(ignore_permissions=True)
		changed = True
	# Recommendation context is a separate, later rollout.  It is never implied
	# by the School 360 facts grant; operators must deploy and opt in explicitly.
	recommendation_ready = (
		getattr(getattr(frappe, "conf", None), "get", lambda *_args: None)(
			SCHOOL360_RECOMMENDATION_ROLLOUT_CONFIG_KEY
		)
		== SCHOOL360_RECOMMENDATION_CAPABILITY_ID
	)
	for role_name in ("Admissions Director",) if recommendation_ready else ():
		if not frappe.db.exists("Role", role_name):
			continue
		role = frappe.get_doc("Role", role_name)
		if any(
			row.grant_type == "semantic_capability" and row.value == SCHOOL360_RECOMMENDATION_CAPABILITY_ID
			for row in role.custom_ai_capability_grants
		):
			continue
		role.append(
			"custom_ai_capability_grants",
			{"grant_type": "semantic_capability", "value": SCHOOL360_RECOMMENDATION_CAPABILITY_ID},
		)
		role.save(ignore_permissions=True)
		changed = True
	if changed:
		# This helper is invoked by a one-shot migration command as well as
		# hooks.  Persist the grant before the command returns, otherwise a
		# fresh worker sees an unchanged manifest after the implicit rollback.
		frappe.db.commit()
		frappe.clear_cache()


def _remove_retired_capabilities() -> None:
	"""Remove grants for semantic capabilities with no active tool binding."""
	if not RETIRED_SEMANTIC_CAPABILITIES:
		return
	if not frappe.get_meta("Role").has_field("custom_ai_capability_grants"):
		return
	frappe.db.delete(
		"CRM AI Capability Grant",
		{
			"parenttype": "Role",
			"grant_type": "semantic_capability",
			"value": ["in", list(RETIRED_SEMANTIC_CAPABILITIES)],
		},
	)
	frappe.db.commit()
	frappe.clear_cache()
