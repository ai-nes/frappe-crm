"""Phase 7: propose -> check impact -> approve -> effective date/version ->
audit log for the 5 governed shared lookup doctypes (lead source, platform,
intent type, lost reason, campus), per section 8 of
docs/admissions-crm-operating-model.md.

Simple additive value creation (a brand-new CRM Lead Source row, etc.) does
NOT go through this module -- it's inserted directly with approval_state
defaulted to "Approved" (see set_governance_defaults, called from each
governed doctype's before_insert). Only STRUCTURAL changes to an existing
value -- rename, retire, reactivate -- go through propose_change /
approve_change / reject_change below, gated by the owning/approving role for
that lookup type.
"""

import json

import frappe
from frappe.model.rename_doc import rename_doc
from frappe.utils import now_datetime, nowdate

# Ownership per docs/admissions-crm-operating-model.md section 8. CRM Intent
# Type isn't named explicitly in that table -- it's treated as part of the
# "Source, platform, UTM, campaign/event type" marketing-owned group, same as
# Lead Source/Platform, since intent signals are a marketing-scored construct
# (see CRM Intent doctype). CRM Lost Reason's row ("Interaction type, outcome,
# lost reason") names two approvers ("Sales + Marketing cùng duyệt") --
# modeled as approver_roles requiring BOTH roles to sign off, not either.
GOVERNED_DOCTYPES = {
	"CRM Lead Source": {
		"name_field": "source_name",
		"owner_role": "Marketing",
		"approver_roles": {"Marketing"},
		"usage_checks": [("CRM Contact", "source"), ("CRM Platform", "lead_source")],
	},
	"CRM Platform": {
		"name_field": "platform_name",
		"owner_role": "Marketing",
		"approver_roles": {"Marketing"},
		"usage_checks": [("CRM Contact", "platform")],
	},
	"CRM Intent Type": {
		"name_field": "intent_type_name",
		"owner_role": "Marketing",
		"approver_roles": {"Marketing"},
		"usage_checks": [("CRM Intent", "intent_type")],
	},
	"CRM Lost Reason": {
		"name_field": "lost_reason",
		"owner_role": "Marketing",
		"approver_roles": {"Lead Sales", "Marketing"},
		# No doctype in this fork currently links to CRM Lost Reason (verified
		# by grep across crm/fcrm/doctype/*/*.json) -- the impact check below
		# will always report 0 usage for this type until something wires it
		# up. That's an accurate reflection of current schema state, not a
		# bug in the impact check itself.
		"usage_checks": [],
	},
	"CRM Campus": {
		"name_field": "campus_name",
		"owner_role": "Admissions Director",
		"approver_roles": {"Admissions Director"},
		"usage_checks": [
			("CRM Contact", "branch"),
			("CRM Student", "branch"),
			("CRM Staff", "campus"),
			("CRM Campaign", "campus"),
			("CRM Campaign Spend", "campus"),
			("CRM Team", "campus"),
		],
	},
}


def _governed_config(doctype):
	config = GOVERNED_DOCTYPES.get(doctype)
	if not config:
		frappe.throw(f"{doctype} is not a governed master data type")
	return config


def _require_role(role, user=None):
	user = user or frappe.session.user
	if role not in frappe.get_roles(user):
		frappe.throw(f"Only {role} can do this for this lookup type", frappe.PermissionError)


def _require_owner_or_approver(config, user=None):
	user = user or frappe.session.user
	user_roles = set(frappe.get_roles(user))
	allowed_roles = {config["owner_role"]} | config["approver_roles"]
	if not (user_roles & allowed_roles):
		frappe.throw(
			"You do not have access to this lookup type's governance data", frappe.PermissionError
		)


def set_governance_defaults(doc):
	"""Called from each governed doctype's before_insert. New rows are
	inserted as already-approved (additive creation stays lightweight, per
	Phase 7 Success Criteria) -- only later structural changes to an
	existing row require the propose/approve flow below."""
	config = GOVERNED_DOCTYPES.get(doc.doctype)
	if not config:
		return
	if not doc.get("owner_role"):
		doc.owner_role = config["owner_role"]
	# The DocType field's default is "Proposed", but additive rows bypass the
	# governed structural-change flow and are intentionally approved on insert.
	if not doc.get("approval_state") or doc.approval_state == "Proposed":
		doc.approval_state = "Approved"
	if not doc.get("version"):
		doc.version = 1
	if not doc.get("effective_date"):
		doc.effective_date = nowdate()


@frappe.whitelist()
def check_impact(doctype, docname):
	"""How many records in other doctypes currently reference this lookup
	value -- surfaced to the approver before a rename/retire is approved.
	Gated to that lookup type's owner/approver roles since frappe.db.count
	bypasses doctype read permissions on the referencing doctypes."""
	config = _governed_config(doctype)
	_require_owner_or_approver(config)
	usage = {}
	for ref_doctype, fieldname in config["usage_checks"]:
		usage[f"{ref_doctype}.{fieldname}"] = frappe.db.count(ref_doctype, filters={fieldname: docname})
	return usage


@frappe.whitelist()
def propose_change(doctype, docname, action, new_value=None, reason=None):
	"""Propose a structural change (Rename/Retire/Reactivate) to an existing
	governed lookup value. Gated to that lookup type's owning role. Records
	the impact-check snapshot at proposal time so the approver sees it
	without re-running the query themselves."""
	config = _governed_config(doctype)
	_require_role(config["owner_role"])

	if action not in ("Rename", "Retire", "Reactivate"):
		frappe.throw("action must be one of Rename, Retire, Reactivate")
	if action == "Rename" and not new_value:
		frappe.throw("new_value is required for a Rename proposal")
	if not reason:
		frappe.throw("A reason is required to propose a master data change")
	if not frappe.db.exists(doctype, docname):
		frappe.throw(f"{doctype} {docname} does not exist")

	change = frappe.get_doc(
		{
			"doctype": "CRM Master Data Change Log",
			"reference_doctype": doctype,
			"reference_docname": docname,
			"action": action,
			"old_value": docname,
			"new_value": new_value,
			"reason": reason,
			"status": "Proposed",
			"proposed_by": frappe.session.user,
			"proposed_at": now_datetime(),
			"required_approver_roles": ",".join(sorted(config["approver_roles"])),
			"impact_summary": json.dumps(check_impact(doctype, docname)),
		}
	)
	change.insert(ignore_permissions=True)
	return change.name


def _apply_change(change):
	if change.action == "Rename":
		# Approval has already been authorized above.  The approver may not hold
		# ordinary write permission on the lookup DocType, so do not make that
		# unrelated permission a second, inconsistent approval gate.
		rename_doc(
			change.reference_doctype,
			change.reference_docname,
			change.new_value,
			ignore_permissions=True,
		)
		doc = frappe.get_doc(change.reference_doctype, change.new_value)
	else:
		doc = frappe.get_doc(change.reference_doctype, change.reference_docname)
		doc.approval_state = "Retired" if change.action == "Retire" else "Approved"
	doc.version = (doc.version or 1) + 1
	doc.effective_date = nowdate()
	doc.save(ignore_permissions=True)


@frappe.whitelist()
def approve_change(change_log_name):
	"""Records this user's approval. The change is only actually applied once
	every role in required_approver_roles has signed off (CRM Lost Reason
	requires both Lead Sales and Marketing; every other governed type
	has a single required approver).

	Retries once on a concurrent-write conflict: two approvers signing off on
	the same dual-sign-off change at nearly the same time would otherwise hit
	frappe.TimestampMismatchError on the second save (Frappe's optimistic
	locking correctly prevents a lost update, but without a retry that just
	surfaces as an error to the second approver instead of re-applying their
	approval against the now-current state)."""
	for attempt in range(2):
		change = frappe.get_doc("CRM Master Data Change Log", change_log_name)
		if change.status != "Proposed":
			frappe.throw(f"Change {change_log_name} is not pending approval")

		config = _governed_config(change.reference_doctype)
		if change.proposed_by == frappe.session.user:
			frappe.throw("A proposer cannot approve their own governed change", frappe.PermissionError)
		user_roles = set(frappe.get_roles(frappe.session.user))
		matching_roles = user_roles & config["approver_roles"]
		if not matching_roles:
			frappe.throw("You are not an approver for this lookup type", frappe.PermissionError)
		if len(matching_roles) > 1:
			# One account must never self-satisfy both sides of a dual approval.
			# Canonical role assignment normally prevents this; keep the gate here
			# as a defense for pre-cutover or manually edited users.
			frappe.throw(
				"Dual approval requires a single-role approver account",
				frappe.PermissionError,
			)

		already_approved = set(filter(None, (change.approved_by_roles or "").split(",")))
		already_approved |= matching_roles
		change.approved_by_roles = ",".join(sorted(already_approved))
		change.approved_by = frappe.session.user

		required_roles = set(filter(None, (change.required_approver_roles or "").split(",")))
		if required_roles <= already_approved:
			_apply_change(change)
			change.status = "Approved"
			change.approved_at = now_datetime()

		try:
			change.save(ignore_permissions=True)
			return change.status
		except frappe.TimestampMismatchError:
			if attempt == 1:
				raise
			frappe.db.rollback()


@frappe.whitelist()
def reject_change(change_log_name, reason=None):
	change = frappe.get_doc("CRM Master Data Change Log", change_log_name)
	if change.status != "Proposed":
		frappe.throw(f"Change {change_log_name} is not pending approval")

	config = _governed_config(change.reference_doctype)
	user_roles = set(frappe.get_roles(frappe.session.user))
	if not (user_roles & config["approver_roles"]):
		frappe.throw("You are not an approver for this lookup type", frappe.PermissionError)

	change.status = "Rejected"
	if reason:
		change.reason = f"{change.reason}\n\nRejected: {reason}"
	change.save(ignore_permissions=True)
	return change.status
