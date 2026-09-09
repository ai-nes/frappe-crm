"""Compatibility helpers for the canonical Student stage workflow.

The authoritative record fields are ``CRM Student.student_stage`` and
``CRM Lead.processing_status``/``resolution``.  This module remains importable
for older integrations, but it no longer reads or writes retired status fields.
"""

import frappe

from crm.fcrm.permissions import FULL_VISIBILITY_ROLES
from crm.fcrm.student_stage import lifecycle_label_for_stage, stage_from_enrollment_status

# Forward order of the main track. "Lost" is a separate branch reachable
# from any stage and is deliberately excluded from this ordering — entering
# Lost is not a "backward move", only *leaving* Lost (reopening) is gated.
LIFECYCLE_ORDER = ["Lead", "MQL", "Applicant", "Enrolled"]
LOST_STAGE = "Lost"

# Roles allowed to move a lead backward in its lifecycle or reopen it from
# Lost — locked in Phase 3 planning as "Team Lead or GĐ Tuyển sinh
# equivalent". Reuses the existing full-visibility bypass roles (System
# Manager/Administrator always need an override path) plus Lead Sale.
LIFECYCLE_OVERRIDE_ROLES = FULL_VISIBILITY_ROLES | {"Lead Sale"}


def get_lifecycle_stage(value):
	"""Return the historical lifecycle label for a canonical or legacy value."""
	value = str(value or "").strip()
	if value in LIFECYCLE_ORDER or value == LOST_STAGE:
		return value
	stage = stage_from_enrollment_status(value)
	return lifecycle_label_for_stage(stage)


def lifecycle_rank(stage):
	"""Position in the main track, or None for Lost/unmapped values."""
	if stage not in LIFECYCLE_ORDER:
		return None
	return LIFECYCLE_ORDER.index(stage)


def is_backward_or_reopen(before_stage, after_stage):
	if not before_stage or not after_stage or before_stage == after_stage:
		return False
	if before_stage == LOST_STAGE and after_stage != LOST_STAGE:
		return True
	before_rank = lifecycle_rank(before_stage)
	after_rank = lifecycle_rank(after_stage)
	if before_rank is None or after_rank is None:
		return False
	return after_rank < before_rank


def user_can_override_lifecycle(user):
	roles = set(frappe.get_roles(user))
	return bool(roles & LIFECYCLE_OVERRIDE_ROLES)


def enforce_lifecycle_change_policy(doc, before_stage):
	"""Require a reason and an override role for a backward stage change."""
	before_stage = get_lifecycle_stage(before_stage)
	after_stage = lifecycle_label_for_stage(doc.get("student_stage")) or doc.get("student_stage")
	if not is_backward_or_reopen(before_stage, after_stage):
		return

	if not user_can_override_lifecycle(frappe.session.user):
		frappe.throw(
			frappe._(
				"Only a Lead Sale user or Admissions Director may move a Student backward "
				"in its lifecycle or reopen it from Lost."
			),
			frappe.PermissionError,
		)
	if not doc.get("status_change_reason"):
		frappe.throw(
			frappe._(
				"Please provide a reason for moving this Student backward or reopening it from Lost."
			),
			title=frappe._("Reason required"),
		)
