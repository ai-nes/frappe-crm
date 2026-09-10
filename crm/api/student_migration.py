"""Admin-only Phase 5 migration verification and rollback-safe controls."""

from __future__ import annotations

import frappe
from frappe import _

from crm.fcrm.student_feature_flags import enabled
from crm.patches.v1_0.backfill_student_engagement import (
	apply_deterministic_lifecycle_projection,
)
from crm.patches.v1_0.backfill_student_engagement import (
	execute as dry_run_migration,
)


def _require_admin() -> None:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if frappe.session.user != "Administrator":
		frappe.throw(_("Only the Administrator may run the Student migration."), frappe.PermissionError)


@frappe.whitelist()
def verify_student_migration(apply: int | str | bool = 0, reason: str | None = None) -> dict:
	"""Return a deterministic report, or apply only reviewed projections.

	Applying requires the explicit server-side migration flag.  Disabling the
	flag later is the rollback operation: events and projections remain intact,
	while new command writes are rejected by their own flags.
	"""
	_require_admin()
	if not apply or str(apply).lower() in {"0", "false", "no"}:
		return dry_run_migration()
	if not enabled("migration"):
		frappe.throw(_("Student migration apply is disabled by rollout policy."), frappe.PermissionError)
	if not str(reason or "").strip():
		frappe.throw(_("A reason is required to apply the Student migration."), frappe.ValidationError)
	frappe.log_error(
		title="Phase 5 Student migration applied",
		message=frappe.as_json({"actor": frappe.session.user, "reason": str(reason).strip()[:500]}),
	)
	return apply_deterministic_lifecycle_projection()
