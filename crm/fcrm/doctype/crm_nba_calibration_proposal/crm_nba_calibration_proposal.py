import frappe
from frappe.model.document import Document

# Fields set once at creation by the calibration service. Everything except
# the review outcome below is immutable for the life of the document.
_PROTECTED_FIELDS = (
	"dataset_digest",
	"report_digest",
	"baseline_json",
	"candidate_json",
	"exclusions_json",
	"prior_policy_revision",
)
_REVIEW_STATUSES = {"approved", "rejected"}


def _require_roles(*roles: str) -> None:
	"""Role gate that stays enforced under tests.

	``frappe.only_for`` short-circuits whenever ``frappe.flags.in_test`` is
	set, which is always true inside ``FrappeTestCase`` -- it would make this
	doctype's role boundary untestable. Administrator is still exempt, same
	as ``only_for``.
	"""
	if frappe.session.user == "Administrator":
		return
	if set(roles).isdisjoint(frappe.get_roles()):
		frappe.throw(f"This action is only allowed for {', '.join(roles)}.", frappe.PermissionError)


class CRMNBACalibrationProposal(Document):
	"""Deterministic calibration report awaiting Director review.

	Created only by the calibration service (`create_calibration_proposal`,
	gated on `frappe.flags.nba_calibration_proposal_write`, mirroring
	`CRM NBA Outcome Attribution`'s own write-guard pattern -- this doctype
	defines its own flag rather than reusing that one, since the two guard
	unrelated writers). After creation, the only legal change is the single
	`shadow -> approved | rejected` review transition performed by
	`submit_calibration_review`; every report field stays immutable.
	"""

	def validate(self):
		before = self.get_doc_before_save()
		if before is None:
			if not getattr(frappe.flags, "nba_calibration_proposal_write", False):
				frappe.throw(
					"Calibration proposals are created by the calibration service.",
					frappe.PermissionError,
				)
		else:
			self._validate_review_transition(before)
		if self.status not in {"shadow", "approved", "rejected", "superseded"}:
			frappe.throw("Invalid calibration proposal status.", frappe.ValidationError)
		if self.status == "approved" and not self.approved_by:
			frappe.throw("Approved calibration proposals require an approver.", frappe.ValidationError)

	def _validate_review_transition(self, before):
		for field in _PROTECTED_FIELDS:
			if self.get(field) != before.get(field):
				frappe.throw(
					f"{field} cannot change after a calibration proposal is created.",
					frappe.PermissionError,
				)
		if before.status != "shadow":
			frappe.throw("Only a shadow proposal can be reviewed.", frappe.PermissionError)
		if self.status != before.status and self.status not in _REVIEW_STATUSES:
			frappe.throw("Review must set status to approved or rejected.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Calibration proposals cannot be deleted.", frappe.PermissionError)


@frappe.whitelist()
def create_calibration_proposal(
	dataset_digest: str,
	report_digest: str,
	baseline_json: dict | str,
	candidate_json: dict | str,
	exclusions_json: dict | str | None = None,
	prior_policy_revision: str | None = None,
) -> str:
	"""Persist one calibration report as a `shadow` proposal.

	Restricted to System Manager: this is a system-computed artifact (the
	calibration service runs the golden-corpus comparison and, if ever in
	scope, the real-data metric), not something an end user assembles by
	hand. An Admissions Director can only read and review it, never create
	one directly.
	"""
	_require_roles("System Manager")
	frappe.flags.nba_calibration_proposal_write = True
	try:
		doc = frappe.get_doc(
			{
				"doctype": "CRM NBA Calibration Proposal",
				"dataset_digest": dataset_digest,
				"report_digest": report_digest,
				"baseline_json": baseline_json,
				"candidate_json": candidate_json,
				"exclusions_json": exclusions_json or {},
				"prior_policy_revision": prior_policy_revision or "",
				"status": "shadow",
			}
		)
		doc.insert(ignore_permissions=True)
	finally:
		frappe.flags.nba_calibration_proposal_write = False
	return doc.name


@frappe.whitelist()
def submit_calibration_review(name: str, decision: str, review_note: str | None = None) -> dict:
	"""The one legal post-creation write: move a `shadow` proposal to
	`approved` or `rejected`. Never applies the candidate weights to the live
	`CRM NBA Decision Policy` -- that stays a separate, explicit action."""
	_require_roles("Admissions Director", "System Manager")
	if decision not in _REVIEW_STATUSES:
		frappe.throw("decision must be 'approved' or 'rejected'.", frappe.ValidationError)
	doc = frappe.get_doc("CRM NBA Calibration Proposal", name)
	if doc.status != "shadow":
		frappe.throw("Only a shadow proposal can be reviewed.", frappe.ValidationError)
	doc.status = decision
	if decision == "approved":
		doc.approved_by = frappe.session.user
		doc.approved_at = frappe.utils.now_datetime()
	if review_note:
		doc.review_note = review_note
	doc.save(ignore_permissions=True)
	return {"name": doc.name, "status": doc.status}
