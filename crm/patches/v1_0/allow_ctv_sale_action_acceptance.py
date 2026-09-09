"""Allow CTV Sale to accept canonical recommendations and create work items.

The action seed is intentionally insert-only, so changing the default policy
does not update existing ``CRM Action`` rows. This patch adds CTV Sale to the
stored actor list for canonical, non-manager actions and refreshes the NBA
definition digest/revision log when the control plane is installed.
"""

from __future__ import annotations

import json

import frappe

from crm.fcrm.action_constraints import MANAGER_ONLY_ACTIONS
from crm.fcrm.action_type_catalog import ACTION_TYPE_CODES

CTV_SALE_ROLE = "CTV Sale"


def execute():
	if not frappe.db.table_exists("CRM Action"):
		return

	changed = _add_ctv_sale_to_canonical_actions()
	if changed:
		# Keep the current Action default in sync with the actor-list change.
		from crm.patches.v1_0.add_nba_control_plane import _backfill_actions

		_backfill_actions()

	if changed and not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
		frappe.clear_cache()


def _add_ctv_sale_to_canonical_actions() -> bool:
	changed = False
	for row in frappe.get_all(
		"CRM Action",
		fields=["name", "code", "allowed_actors"],
		limit_page_length=0,
	):
		if row.get("code") not in ACTION_TYPE_CODES or row.get("code") in MANAGER_ONLY_ACTIONS:
			continue

		actors = _parse_actors(row.get("allowed_actors"))
		if actors is None or CTV_SALE_ROLE in actors:
			continue

		actors.append(CTV_SALE_ROLE)
		frappe.db.set_value(
			"CRM Action",
			row["name"],
			"allowed_actors",
			json.dumps(actors, ensure_ascii=False),
			update_modified=False,
		)
		changed = True
	return changed


def _parse_actors(value) -> list[str] | None:
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except (TypeError, ValueError):
			return None
	if not isinstance(value, (list, tuple)):
		return None
	return [str(actor).strip() for actor in value if str(actor).strip()]
