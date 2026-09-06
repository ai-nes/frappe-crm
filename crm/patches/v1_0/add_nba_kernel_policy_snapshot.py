"""Backfill the complete signed NBA kernel policy snapshot.

Older Decision Policy rows only carried display-oriented knobs.  This patch
adds the immutable compatibility kernel payload and binds ``policy_digest`` to
it so live evaluation never falls back to crm-agents defaults.
"""

import json

import frappe

from crm.fcrm.nba_canonical import canonical_digest


def _default_kernel() -> dict:
	return {
		"revision": "nba-decision-policy-r1",
		"score_threshold": 0.35,
		"confidence_floor": 0.45,
		"top_n_cap": 3,
		"recommendation_ttl_seconds": 604800,
		"component_weights": {
			"opportunity_fit": 0.45,
			"urgency": 0.25,
			"effectiveness_index": 0.30,
		},
		"recent_contact_days": 2,
		"cooling_contact_days": 5,
		"contact_pressure_penalty": 0.15,
		"redundancy_penalty": 0.10,
		"diversity_group_penalty": 0.05,
		"deadline_horizon_days": 30,
	}


def execute():
	if not frappe.db.table_exists("CRM NBA Decision Policy"):
		return
	frappe.reload_doc("fcrm", "doctype", "crm_nba_decision_policy", force=True)
	kernel = _default_kernel()
	payload = json.dumps(kernel, sort_keys=True)
	digest = canonical_digest(kernel)
	rows = frappe.get_all("CRM NBA Decision Policy", fields=["name", "kernel_policy", "policy_digest"])
	for row in rows:
		if row.get("kernel_policy"):
			continue
		frappe.db.set_value(
			"CRM NBA Decision Policy",
			row["name"],
			{"kernel_policy": payload, "policy_digest": digest},
			update_modified=False,
		)
	if not frappe.flags.in_test:
		frappe.db.commit()
