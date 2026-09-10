"""Server-only publication guard for Phase 4 operational policies."""

from __future__ import annotations

import frappe

from crm.fcrm.role_policy import capabilities_for_roles


def _has_capability(user: str, capability: str) -> bool:
	return capability in capabilities_for_roles(
		frappe.get_roles(user), administrator=user == "Administrator"
	)


def validate_policy_publication(doc, locked_fields: tuple[str, ...]) -> None:
	"""Reject direct policy writes and enforce separate author/approver roles."""
	if not getattr(frappe.flags, "student_policy_service", False):
		frappe.throw("Student operational policies can only be changed by the policy service.")

	actor = frappe.session.user or "Guest"
	previous = doc.get_doc_before_save() if not doc.is_new() else None
	is_approver = bool(
		doc.status == "active"
		and doc.approved_by
		and doc.approved_by == actor
		and _has_capability(actor, "student.policy.approve")
	)
	is_policy_author = actor == "Administrator" or _has_capability(actor, "student.policy.manage")
	if not doc.authored_by:
		if not is_policy_author:
			frappe.throw("Only a System Manager may author a Student operational policy.")
		doc.authored_by = actor
	elif doc.authored_by != actor and not is_approver:
		frappe.throw("Policy author must be the authenticated actor.")
	if previous and previous.status == "retired":
		frappe.throw("Retired policy versions are immutable; create a new version.")
	if previous and previous.status == "active":
		if doc.status == "retired" and not is_policy_author:
			frappe.throw("Only a System Manager may retire an active policy.")
		if doc.status not in {"active", "retired"}:
			frappe.throw("An active policy can only be retired.")
		for fieldname in locked_fields:
			if doc.get(fieldname) != previous.get(fieldname):
				frappe.throw(f"{fieldname} is locked on an active policy")

	if doc.status != "active":
		return
	if not doc.effective_from:
		frappe.throw("An active policy requires an effective start.")
	if doc.effective_until and doc.effective_until <= doc.effective_from:
		frappe.throw("Policy effective end must be after its start.")
	if not doc.approved_by or not doc.approved_at:
		frappe.throw("An active policy requires a separate approval.")
	if actor != doc.approved_by and actor != "Administrator":
		frappe.throw("The authenticated actor must be the policy approver.")
	if doc.approved_by == doc.authored_by:
		if actor != "Administrator" or not doc.break_glass_reason:
			frappe.throw("Policy author and approver must be different users.")
	elif not _has_capability(doc.approved_by, "student.policy.approve"):
		frappe.throw("Policy approver lacks the Admissions Director capability.")

	if not frappe.db.table_exists("CRM Student Pool"):
		frappe.throw("Student Pool is required before publishing an operational policy.")
	# A pool row is the deterministic lock for the policy scope.  Every active
	# policy for the same Campus/Pool serializes on this row before overlap check.
	pool_lock = frappe.db.sql(
		"select name from `tabCRM Student Pool` where name = %s for update",
		(doc.student_pool,),
	)
	if not pool_lock:
		frappe.throw("Policy Student Pool does not exist.")
	pool_campus = frappe.db.get_value("CRM Student Pool", doc.student_pool, "campus")
	if pool_campus != doc.campus:
		frappe.throw("Policy Campus must match the Student Pool Campus.")
	end = doc.effective_until or "9999-12-31 23:59:59"
	existing = frappe.db.sql(
		f"""
		select name from `tab{doc.doctype}`
		where name != %s and status = 'active'
		  and campus = %s and student_pool = %s
		  and effective_from < %s
		  and coalesce(effective_until, '9999-12-31 23:59:59') > %s
		for update
		""",
		(doc.name or "", doc.campus, doc.student_pool, end, doc.effective_from),
	)
	if existing:
		frappe.throw("An active policy already covers this Campus and Student Pool window.")
