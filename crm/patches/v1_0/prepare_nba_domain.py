"""Backfill the CRM recommendation and action-item projections."""

import frappe

from crm.fcrm.action_type_catalog import action_category, canonicalize_action_type
from crm.fcrm.nba import ACTION_ITEM_DOCTYPE, ensure_nba_action, ensure_nba_execution_for_attempt


def execute():
	"""Make the explicit NBA contract available without changing old identity."""
	if not frappe.db.exists("DocType", ACTION_ITEM_DOCTYPE):
		return

	_backfill_action_items()
	_backfill_recommendation_metadata()
	_backfill_execution_links()
	if not frappe.flags.in_test:
		frappe.db.commit()


def _backfill_action_items():
	if not frappe.db.exists("DocType", ACTION_ITEM_DOCTYPE):
		return
	for row in frappe.get_all(
		ACTION_ITEM_DOCTYPE,
		fields=["name", "action", "action_type"],
		limit_page_length=0,
	):
		action_name = ensure_nba_action(row.action or row.action_type)
		if action_name:
			frappe.db.set_value(
				ACTION_ITEM_DOCTYPE,
				row.name,
				{"action": action_name, "action_type": action_category(action_name)},
				update_modified=False,
			)


def _backfill_recommendation_metadata():
	if not frappe.db.exists("DocType", "CRM Recommendation"):
		return
	for row in frappe.get_all(
		"CRM Recommendation",
		fields=[
			"name",
			"student",
			"created_at",
			"recommended_action",
			"status",
			"target_type",
			"target_id",
			"recommendation_id",
			"recommended_at",
			"lifecycle_status",
			"decision_status",
			"execution_status",
			"action",
		],
		limit_page_length=0,
	):
		values = {
			"recommendation_id": row.recommendation_id or row.name,
			"target_type": row.target_type or "CRM Student",
			"target_id": row.target_id or row.student,
			"recommended_at": row.recommended_at or row.created_at,
			"lifecycle_status": row.lifecycle_status or "proposed",
			"decision_status": row.decision_status or _decision_status(row.status),
			"execution_status": row.execution_status or "not_started",
		}
		action_name = row.action if frappe.db.exists("CRM Action", row.action) else None
		if not action_name:
			action_name = ensure_nba_action(row.recommended_action)
		if action_name:
			values["action"] = action_name
		frappe.db.set_value("CRM Recommendation", row.name, values, update_modified=False)


def _backfill_execution_links():
	if not frappe.db.exists("DocType", "CRM Action Execution Attempt"):
		return
	for row in frappe.get_all(
		"CRM Action Execution Attempt",
		filters={"nba_execution": ["is", "not set"]},
		fields=["name", "action"],
		limit_page_length=0,
	):
		action = frappe.get_doc(ACTION_ITEM_DOCTYPE, row.action)
		if not action.get("recommendation"):
			continue
		attempt = frappe.get_doc("CRM Action Execution Attempt", row.name)
		execution = ensure_nba_execution_for_attempt(attempt, action=action)
		if execution:
			frappe.db.set_value(
				"CRM Action Execution Attempt", row.name, "nba_execution", execution.name, update_modified=False
			)


def _decision_status(status):
	return {
		"new": "pending",
		"acknowledged": "pending",
		"accepted": "accepted",
		"rejected": "rejected",
		"deferred": "deferred",
		"expired": "rejected",
	}.get(status, "pending")
