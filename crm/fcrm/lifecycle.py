"""Shared lifecycle-stage logic for CRM Contact and CRM Student.

Implements Phase 3 of plans/260822-admissions-crm-alignment: a long-term
lifecycle track (Lead -> MQL -> Applicant -> Enrolled, with Lost as a
separate terminal branch) derived from the existing CRM Enrollment Status
master (its `lifecycle_stage` field — see
crm.fcrm.doctype.crm_enrollment_status), rather than from the day-to-day
enrollment_status/lead_status working values directly. This keeps the two
tracks from drifting: lifecycle_stage is a pure, read-only function of
enrollment_status, recomputed on every save.
"""

import frappe

from crm.fcrm.permissions import FULL_VISIBILITY_ROLES, _cached

# Forward order of the main track. "Lost" is a separate branch reachable
# from any stage and is deliberately excluded from this ordering — entering
# Lost is not a "backward move", only *leaving* Lost (reopening) is gated.
LIFECYCLE_ORDER = ["Lead", "MQL", "Applicant", "Enrolled"]
LOST_STAGE = "Lost"

# Roles allowed to move a lead backward in its lifecycle or reopen it from
# Lost — locked in Phase 3 planning as "Team Lead or GĐ Tuyển sinh
# equivalent". Reuses the existing full-visibility bypass roles (System
# Manager/Administrator always need an override path) plus Lead Sales.
LIFECYCLE_OVERRIDE_ROLES = FULL_VISIBILITY_ROLES | {"Lead Sales"}


def get_lifecycle_stage(enrollment_status):
	if not enrollment_status:
		return None
	return _cached(
		f"crm_enrollment_status_lifecycle_stage::{enrollment_status}",
		lambda: frappe.db.get_value("CRM Enrollment Status", enrollment_status, "lifecycle_stage") or "",
	) or None


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


def enforce_lifecycle_change_policy(doc, before_enrollment_status):
	"""Requires a reason and the right role whenever a save moves
	lifecycle_stage backward, or reopens a lead that was previously Lost."""
	before_stage = get_lifecycle_stage(before_enrollment_status)
	after_stage = doc.lifecycle_stage
	if not is_backward_or_reopen(before_stage, after_stage):
		return

	if not user_can_override_lifecycle(frappe.session.user):
		frappe.throw(
			frappe._(
			"Only a Lead Sales user or Admissions Director may move a lead backward "
				"in its lifecycle or reopen it from Lost."
			),
			frappe.PermissionError,
		)
	if not doc.status_change_reason:
		frappe.throw(
			frappe._("Please provide a reason for moving this lead backward or reopening it from Lost."),
			title=frappe._("Reason required"),
		)
