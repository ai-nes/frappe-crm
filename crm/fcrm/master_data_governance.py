"""Phase 9 command boundary for governed reference data.

It protects public Frappe document APIs; direct SQL/privileged server writes
remain deployment exceptions that must be reconciled during release operations.
"""

from __future__ import annotations

import json
import hashlib
import secrets
from contextlib import contextmanager
from datetime import timedelta

import frappe
from frappe.utils import get_datetime, now_datetime, nowdate

from crm.fcrm.governed_reference_registry import GOVERNED_REFERENCE_REGISTRY, REGISTRY_REVISION
from crm.fcrm.role_policy import PROFILE_LABELS, classify_role_set, resolve_crm_profile

GOVERNED_DOCTYPES = GOVERNED_REFERENCE_REGISTRY  # compatibility for existing callers
PUBLIC_ACTIONS = frozenset({"Retire", "Reactivate", "Supersede"})
BREAK_GLASS_MAX_MINUTES = 15


def _require_write_enabled():
	"""Keep rollout disabled outside tests until the Phase 9 canary is approved."""
	if getattr(frappe.flags, "in_test", False):
		return
	from crm.fcrm.governance_audit_flags import governance_write_enabled

	if not governance_write_enabled():
		frappe.throw("Phase 9 governance writes are not enabled.", frappe.PermissionError)


@contextmanager
def _internal_flag(name):
	previous = frappe.flags.get(name)
	setattr(frappe.flags, name, True)
	try:
		yield
	finally:
		setattr(frappe.flags, name, previous)


def _governed_config(doctype):
	config = GOVERNED_REFERENCE_REGISTRY.get(doctype)
	if not config:
		frappe.throw(f"{doctype} is not a governed master data type")
	return config


def _governance_roles_for_user(user):
	"""Return only canonical business identities; System Manager never signs."""
	if user == "Administrator":
		return frozenset()
	roles = frozenset(frappe.get_roles(user))
	if classify_role_set(roles) == "system_manager":
		return frozenset()
	profile = resolve_crm_profile(roles)
	return frozenset({PROFILE_LABELS[profile]}) if profile else frozenset()


def _require_role(role, user=None):
	# Administrator is permitted to submit a request for controlled recovery,
	# but cannot approve it and cannot mutate the governed record directly.
	if (user or frappe.session.user) == "Administrator":
		return
	if role not in _governance_roles_for_user(user or frappe.session.user):
		frappe.throw(f"Only {role} can do this for this lookup type", frappe.PermissionError)


def _require_owner_or_approver(config, user=None):
	if (user or frappe.session.user) == "Administrator":
		return
	roles = _governance_roles_for_user(user or frappe.session.user)
	if not roles & ({config["owner_role"]} | set(config["approver_roles"])):
		frappe.throw("You do not have access to this lookup type's governance data", frappe.PermissionError)


def _require_break_glass_role(role, user=None):
	user = user or frappe.session.user
	if user == "Administrator" or role not in frappe.get_roles(user):
		frappe.throw(f"Only a distinct {role} user can perform this break-glass step.", frappe.PermissionError)


def _nonce_digest(nonce):
	return hashlib.sha256(str(nonce or "").encode()).hexdigest()


def _locked_break_glass(request_name):
	frappe.db.sql("SELECT name FROM `tabCRM Master Data Break Glass` WHERE name=%s FOR UPDATE", (request_name,))
	return frappe.get_doc("CRM Master Data Break Glass", request_name)


def validate_governed_mutation(doc, method=None):
	if doc.doctype not in GOVERNED_REFERENCE_REGISTRY or frappe.flags.get("crm_governance_change"):
		return
	if doc.is_new():
		if frappe.flags.get("crm_governance_additive") or getattr(frappe.flags, "in_test", False):
			return
		frappe.throw("Governed master data must be created through the additive governance command.", frappe.PermissionError)
	frappe.throw("Governed master data must be changed through the proposal and approval workflow.", frappe.PermissionError)


def prevent_governed_delete(doc, method=None):
	if (
		doc.doctype in GOVERNED_REFERENCE_REGISTRY
		and not frappe.flags.get("crm_governance_change")
		and not getattr(frappe.flags, "in_test", False)
	):
		frappe.throw("Governed master data must be retired through the proposal and approval workflow.", frappe.PermissionError)


def prevent_governed_rename(doc, method=None, *args, **kwargs):
	if doc.doctype in GOVERNED_REFERENCE_REGISTRY and not frappe.flags.get("crm_governance_change") and not getattr(frappe.flags, "in_test", False):
		frappe.throw("Governed master data cannot be renamed; use an approved supersession.", frappe.PermissionError)


def set_governance_defaults(doc):
	"""Compatibility defaults for the five legacy doctypes with metadata."""
	config = GOVERNED_REFERENCE_REGISTRY.get(doc.doctype)
	if not config:
		return
	if hasattr(doc, "owner_role") and not doc.get("owner_role"):
		doc.owner_role = config["owner_role"]
	if hasattr(doc, "approval_state") and doc.get("approval_state") in (None, "", "Proposed"):
		doc.approval_state = "Approved"
	if hasattr(doc, "version") and not doc.get("version"):
		doc.version = 1
	if hasattr(doc, "effective_date") and not doc.get("effective_date"):
		doc.effective_date = nowdate()


def effective_reference_filters(doctype):
	_governed_config(doctype)
	return {"approval_state": "Approved"} if frappe.get_meta(doctype).has_field("approval_state") else {}


def assert_reference_effective(doctype, docname, *, as_of=None):
	"""Reject new references to retired/future values, never historical reads."""
	if not docname or doctype not in GOVERNED_REFERENCE_REGISTRY:
		return
	if not frappe.db.exists(doctype, docname):
		frappe.throw(f"{doctype} {docname} does not exist")
	if not frappe.get_meta(doctype).has_field("approval_state"):
		return
	state, effective_date = frappe.db.get_value(doctype, docname, ["approval_state", "effective_date"])
	if state != "Approved":
		frappe.throw(f"{doctype} {docname} is retired and cannot receive new references.", frappe.ValidationError)
	if effective_date and get_datetime(effective_date) > get_datetime(as_of or nowdate()):
		frappe.throw(f"{doctype} {docname} is not effective yet.", frappe.ValidationError)


def validate_governed_references(doc, method=None):
	"""Reject new writes that point at retired/future governed values."""
	for governed_doctype, config in GOVERNED_REFERENCE_REGISTRY.items():
		for reference in config.get("consumers", ()):
			if reference["doctype"] == doc.doctype:
				value = doc.get(reference["fieldname"])
				if value:
					assert_reference_effective(governed_doctype, value)


@frappe.whitelist()
def create_additive_value(doctype, value, reason=None, idempotency_key=None, correlation_id=None, lead_source=None):
	"""Create a policy-approved additive lookup through one server boundary."""
	_require_write_enabled()
	config = _governed_config(doctype)
	if config.get("additive_requires_approval"):
		frappe.throw("This lookup requires a proposal and independent approval.", frappe.ValidationError)
	_require_role(config["owner_role"])
	value = (value or "").strip()
	if not value:
		frappe.throw("value is required", frappe.ValidationError)
	name_field = config["name_field"]
	for required_field in config.get("required_fields", ()):
		if not locals().get(required_field):
			frappe.throw(f"{required_field} is required for this lookup type.", frappe.ValidationError)
	if idempotency_key:
		existing = frappe.db.get_value("CRM Master Data Change Log", {"idempotency_key": idempotency_key}, "name")
		if existing:
			return {"name": existing, "status": "replayed"}
	if frappe.db.exists(doctype, value):
		return {"name": value, "status": "existing"}
	payload = {"doctype": doctype, name_field: value}
	if "lead_source" in config.get("required_fields", ()):
		payload["lead_source"] = lead_source
	if reason and config.get("description_field"):
		payload[config["description_field"]] = reason
	with _internal_flag("crm_governance_additive"):
		doc = frappe.get_doc(payload).insert(ignore_permissions=True)
	with _internal_flag("crm_governance_log_insert"):
		frappe.get_doc({
			"doctype": "CRM Master Data Change Log", "reference_doctype": doctype,
			"reference_docname": doc.name, "action": "Create", "status": "Applied",
			"old_value": None, "new_value": doc.name, "reason": reason or "Policy-approved additive value",
			"impact_summary": json.dumps({}, sort_keys=True), "proposed_by": frappe.session.user,
			"proposed_at": now_datetime(), "required_approver_roles": "",
			"approved_by_roles": config["owner_role"], "approved_by": frappe.session.user,
			"approved_at": now_datetime(), "registry_revision": REGISTRY_REVISION,
			"idempotency_key": idempotency_key, "correlation_id": correlation_id or idempotency_key,
			"target_version": 1, "effective_at": now_datetime(), "before_snapshot": "{}",
		}).insert(ignore_permissions=True)
	return {"name": doc.name, "status": "created", "correlation_id": correlation_id or idempotency_key}


@frappe.whitelist()
def check_impact(doctype, docname):
	config = _governed_config(doctype)
	_require_owner_or_approver(config)
	return {f"{ref['doctype']}.{ref['fieldname']}": frappe.db.count(ref["doctype"], {ref["fieldname"]: docname}) for ref in config["consumers"]}


@frappe.whitelist()
def get_pending_change(doctype, docname):
	"""Return the latest pending request for the bounded operator panel."""
	config = _governed_config(doctype)
	_require_owner_or_approver(config)
	return frappe.db.get_value(
		"CRM Master Data Change Log",
		{"reference_doctype": doctype, "reference_docname": docname, "status": ["in", ["Proposed", "Pending Effective"]]},
		["name", "status", "action", "reason", "new_value", "required_approver_roles", "approved_by_roles", "proposed_by", "target_version"],
		as_dict=True,
	) or {}


@frappe.whitelist()
def list_pending_changes(doctype):
	config = _governed_config(doctype)
	_require_owner_or_approver(config)
	return frappe.get_all(
		"CRM Master Data Change Log",
		filters={"reference_doctype": doctype, "status": ["in", ["Proposed", "Pending Effective"]]},
		fields=["name", "reference_docname", "status", "action", "new_value", "reason", "required_approver_roles", "approved_by_roles", "proposed_by", "target_version"],
		order_by="creation desc",
		limit_page_length=50,
	)


@frappe.whitelist()
def propose_additive_value(doctype, value, reason=None, idempotency_key=None, correlation_id=None):
	"""Open an approval-backed creation request for non-additive-safe lookups."""
	_require_write_enabled()
	config = _governed_config(doctype)
	if not config.get("additive_requires_approval"):
		frappe.throw("This lookup uses the additive governance command.", frappe.ValidationError)
	_require_role(config["owner_role"])
	value = (value or "").strip()
	if not value or frappe.db.exists(doctype, value):
		frappe.throw("value must be a new, non-empty lookup value", frappe.ValidationError)
	if idempotency_key:
		existing = frappe.db.get_value("CRM Master Data Change Log", {"idempotency_key": idempotency_key}, "name")
		if existing:
			return {"name": existing, "status": "replayed"}
	with _internal_flag("crm_governance_log_insert"):
		name = frappe.get_doc({
			"doctype": "CRM Master Data Change Log", "reference_doctype": doctype,
			"reference_docname": value, "action": "Create", "status": "Proposed",
			"old_value": None, "new_value": value, "reason": reason or "New governed lost reason",
			"impact_summary": json.dumps({}, sort_keys=True), "proposed_by": frappe.session.user,
			"proposed_at": now_datetime(), "required_approver_roles": ",".join(sorted(config["approver_roles"])),
			"registry_revision": REGISTRY_REVISION, "idempotency_key": idempotency_key,
			"correlation_id": correlation_id or idempotency_key, "target_version": 1,
			"effective_at": now_datetime(), "before_snapshot": "{}",
		}).insert(ignore_permissions=True, ignore_links=True).name
	return {"name": name, "status": "Proposed"}


@frappe.whitelist()
def request_break_glass(doctype, docname, action, reason, evidence_reference=None, correlation_id=None, new_value=None):
	"""Issue a one-use nonce to a System Manager for independent authorization."""
	_require_write_enabled()
	_require_break_glass_role("System Manager")
	config = _governed_config(doctype)
	if action not in PUBLIC_ACTIONS:
		frappe.throw("Break-glass only supports Retire, Reactivate or Supersede.", frappe.ValidationError)
	if not reason or not frappe.db.exists(doctype, docname):
		frappe.throw("A governed target and reason are required.", frappe.ValidationError)
	if action == "Supersede" and not new_value:
		frappe.throw("new_value is required for a break-glass supersession.", frappe.ValidationError)
	version = frappe.db.get_value(doctype, docname, "version") or 1
	nonce = secrets.token_urlsafe(32)
	expires_at = now_datetime() + timedelta(minutes=BREAK_GLASS_MAX_MINUTES)
	with _internal_flag("crm_break_glass_insert"):
		request = frappe.get_doc({
			"doctype": "CRM Master Data Break Glass", "target_doctype": doctype, "target_docname": docname,
			"action": action, "new_value": new_value, "before_version": version,
			"initiated_by": frappe.session.user, "initiated_at": now_datetime(), "expires_at": expires_at,
			"status": "Requested", "nonce_hash": _nonce_digest(nonce), "reason": reason,
			"evidence_reference": evidence_reference, "correlation_id": correlation_id or secrets.token_hex(12),
		}).insert(ignore_permissions=True)
	return {"name": request.name, "status": request.status, "nonce": nonce, "expires_at": expires_at}


@frappe.whitelist()
def authorize_break_glass(request_name, nonce):
	"""Record the separately authenticated Admissions Director authorization."""
	_require_write_enabled()
	_require_break_glass_role("Admissions Director")
	request = _locked_break_glass(request_name)
	if request.status != "Requested" or get_datetime(request.expires_at) <= now_datetime():
		frappe.throw("This break-glass request is expired or already authorized.", frappe.ValidationError)
	if request.nonce_hash != _nonce_digest(nonce):
		frappe.throw("Invalid break-glass nonce.", frappe.PermissionError)
	if request.initiated_by == frappe.session.user:
		frappe.throw("The initiator and authorizer must be distinct users.", frappe.PermissionError)
	current_version = frappe.db.get_value(request.target_doctype, request.target_docname, "version") or 1
	if int(current_version) != int(request.before_version):
		frappe.throw("The break-glass target changed after the request was issued.", frappe.ValidationError)
	request.authorized_by, request.authorized_at, request.status = frappe.session.user, now_datetime(), "Authorized"
	with _internal_flag("crm_break_glass_update"):
		request.save(ignore_permissions=True)
	return request.status


@frappe.whitelist()
def use_break_glass(request_name, nonce):
	"""Atomically consume the authorized nonce and apply its bounded mutation."""
	_require_write_enabled()
	_require_break_glass_role("System Manager")
	request = _locked_break_glass(request_name)
	if request.initiated_by != frappe.session.user or request.status != "Authorized":
		frappe.throw("Only the initiating System Manager may consume an authorized request.", frappe.PermissionError)
	if get_datetime(request.expires_at) <= now_datetime():
		request.status = "Expired"
		with _internal_flag("crm_break_glass_update"):
			request.save(ignore_permissions=True)
		frappe.throw("Break-glass authorization has expired.", frappe.ValidationError)
	if request.nonce_hash != _nonce_digest(nonce):
		frappe.throw("Invalid break-glass nonce.", frappe.PermissionError)
	row = frappe.db.sql(
		f"SELECT version FROM `tab{request.target_doctype}` WHERE name=%s FOR UPDATE",
		(request.target_docname,), as_dict=True,
	)
	if not row or int(row[0].get("version") or 1) != int(request.before_version):
		frappe.throw("The break-glass target changed before use.", frappe.ValidationError)
	with _internal_flag("crm_governance_change"):
		_apply_approved_change(frappe._dict({
			"action": request.action, "reference_doctype": request.target_doctype,
			"reference_docname": request.target_docname, "new_value": request.new_value,
		}))
	request.used_at, request.status = now_datetime(), "Used"
	request.reconciliation_id = request.correlation_id or f"break-glass:{request.name}"
	with _internal_flag("crm_break_glass_update"):
		request.save(ignore_permissions=True)
	return {"status": request.status, "reconciliation_id": request.reconciliation_id}


def _snapshot(doctype, docname):
	return json.dumps(frappe.get_doc(doctype, docname).as_dict(), default=str, sort_keys=True)


@frappe.whitelist()
def propose_change(doctype, docname, action, new_value=None, reason=None, effective_at=None, idempotency_key=None, correlation_id=None, expected_version=None):
	_require_write_enabled()
	config = _governed_config(doctype)
	_require_role(config["owner_role"])
	if action not in PUBLIC_ACTIONS and not (action == "Rename" and getattr(frappe.flags, "in_test", False)):
		frappe.throw("action must be Retire, Reactivate, Supersede or Rename")
	if action in {"Supersede", "Rename"} and not new_value:
		frappe.throw("new_value is required for a supersession proposal")
	if not reason:
		frappe.throw("A reason is required to propose a master data change")
	if not frappe.db.exists(doctype, docname):
		frappe.throw(f"{doctype} {docname} does not exist")
	current_version = frappe.db.get_value(doctype, docname, "version") or 1
	if expected_version not in (None, "") and int(expected_version) != int(current_version):
		frappe.throw("The governed value changed; reload before proposing a new command.", frappe.ValidationError)
	if action == "Supersede" and frappe.db.exists(doctype, new_value):
		assert_reference_effective(doctype, new_value)
	if idempotency_key:
		existing = frappe.db.get_value("CRM Master Data Change Log", {"idempotency_key": idempotency_key}, "name")
		if existing:
			return existing
	payload = {"doctype": "CRM Master Data Change Log", "reference_doctype": doctype, "reference_docname": docname,
			"action": action, "old_value": docname, "new_value": new_value, "reason": reason, "status": "Proposed",
			"proposed_by": frappe.session.user, "proposed_at": now_datetime(), "required_approver_roles": ",".join(sorted(config["approver_roles"])),
			"impact_summary": json.dumps(check_impact(doctype, docname), sort_keys=True), "before_snapshot": _snapshot(doctype, docname),
			"registry_revision": REGISTRY_REVISION, "idempotency_key": idempotency_key, "correlation_id": correlation_id,
			"target_version": current_version, "effective_at": get_datetime(effective_at) if effective_at else now_datetime()}
	with _internal_flag("crm_governance_log_insert"):
		return frappe.get_doc(payload).insert(ignore_permissions=True).name


def _approval_roles(change):
	return set(filter(None, (change.required_approver_roles or "").split(",")))


def _locked_change(change_log_name):
	frappe.db.sql("SELECT name FROM `tabCRM Master Data Change Log` WHERE name=%s FOR UPDATE", (change_log_name,))
	return frappe.get_doc("CRM Master Data Change Log", change_log_name)


def _record_approval(change, role, decision, reason=None):
	if frappe.db.exists("CRM Master Data Change Approval", {"change_log": change.name, "approval_role": role}):
		frappe.throw(f"{role} has already recorded a decision", frappe.ValidationError)
	with _internal_flag("crm_governance_approval_insert"):
		frappe.get_doc({"doctype": "CRM Master Data Change Approval", "change_log": change.name, "approval_role": role, "decision": decision,
			"approved_by": frappe.session.user, "approved_at": now_datetime(), "reason": reason}).insert(ignore_permissions=True)


def _approved_roles(change):
	return set(frappe.get_all("CRM Master Data Change Approval", filters={"change_log": change.name, "decision": "Approved"}, pluck="approval_role"))


def _apply_approved_change(change):
	if change.action == "Create":
		config = _governed_config(change.reference_doctype)
		if frappe.db.exists(change.reference_doctype, change.new_value):
			return frappe.get_doc(change.reference_doctype, change.new_value)
		return frappe.get_doc({"doctype": change.reference_doctype, config["name_field"]: change.new_value}).insert(
			ignore_permissions=True
		)
	if change.action == "Rename":  # legacy test/migration compatibility; public callers use Supersede
		from frappe.model.rename_doc import rename_doc
		rename_doc(change.reference_doctype, change.reference_docname, change.new_value, ignore_permissions=True)
		doc = frappe.get_doc(change.reference_doctype, change.new_value)
	elif change.action == "Supersede":
		config = _governed_config(change.reference_doctype)
		if not frappe.db.exists(change.reference_doctype, change.new_value):
			with _internal_flag("crm_governance_change"):
				successor = frappe.get_doc({"doctype": change.reference_doctype, config["name_field"]: change.new_value}).insert(ignore_permissions=True)
		else:
			successor = frappe.get_doc(change.reference_doctype, change.new_value)
		doc = frappe.get_doc(change.reference_doctype, change.reference_docname)
		if hasattr(doc, "approval_state"):
			doc.approval_state = "Retired"
		doc.version = (doc.version or 1) + 1
		doc.save(ignore_permissions=True)
		return successor
	else:
		doc = frappe.get_doc(change.reference_doctype, change.reference_docname)
		if hasattr(doc, "approval_state"):
			doc.approval_state = "Approved" if change.action == "Reactivate" else "Retired"
	if hasattr(doc, "version"):
		doc.version = (doc.version or 1) + 1
	if hasattr(doc, "effective_date"):
		doc.effective_date = nowdate()
	doc.save(ignore_permissions=True)


def _apply_if_due(change):
	if get_datetime(change.effective_at or now_datetime()) > now_datetime():
		change.status = "Pending Effective"
		return change.status
	if change.action != "Create":
		row = frappe.db.sql(
			f"SELECT version FROM `tab{change.reference_doctype}` WHERE name=%s FOR UPDATE",
			(change.reference_docname,), as_dict=True,
		)
		if not row or int(row[0].get("version") or 1) != int(change.target_version or 1):
			frappe.throw("The governed value changed after proposal; approval is stale.", frappe.ValidationError)
	with _internal_flag("crm_governance_change"):
		_apply_approved_change(change)
	change.status, change.approved_at = "Applied", now_datetime()
	return change.status


@frappe.whitelist()
def approve_change(change_log_name):
	_require_write_enabled()
	change = _locked_change(change_log_name)
	if change.status not in {"Proposed", "Pending Effective"}:
		frappe.throw(f"Change {change_log_name} is not pending approval")
	if change.proposed_by == frappe.session.user:
		frappe.throw("A proposer cannot approve their own request.", frappe.PermissionError)
	roles = _governance_roles_for_user(frappe.session.user) & set(_governed_config(change.reference_doctype)["approver_roles"])
	if len(roles) != 1:
		frappe.throw("You must hold exactly one required approval role.", frappe.PermissionError)
	_record_approval(change, next(iter(roles)), "Approved")
	approved = _approved_roles(change)
	change.approved_by_roles, change.approved_by = ",".join(sorted(approved)), frappe.session.user
	if _approval_roles(change) <= approved:
		_apply_if_due(change)
	with _internal_flag("crm_governance_log_update"):
		change.save(ignore_permissions=True)
	return change.status


@frappe.whitelist()
def reject_change(change_log_name, reason=None):
	_require_write_enabled()
	change = _locked_change(change_log_name)
	if change.status != "Proposed" or change.proposed_by == frappe.session.user:
		frappe.throw("Only an independent approver may reject a pending request.", frappe.PermissionError)
	roles = _governance_roles_for_user(frappe.session.user) & set(_governed_config(change.reference_doctype)["approver_roles"])
	if len(roles) != 1:
		frappe.throw("You are not an approver for this lookup type", frappe.PermissionError)
	_record_approval(change, next(iter(roles)), "Rejected", reason)
	if reason:
		change.reason = f"{change.reason}\nRejection: {reason}"
	change.status = "Rejected"
	with _internal_flag("crm_governance_log_update"):
		change.save(ignore_permissions=True)
	return change.status


def apply_effective_changes():
	"""Idempotent scheduler entry point; hook registration is Phase 9.5-owned."""
	from crm.fcrm.governance_audit_flags import governance_write_enabled
	if not governance_write_enabled() and not getattr(frappe.flags, "in_test", False):
		return {"status": "disabled", "applied": 0}
	applied = 0
	for name in frappe.get_all("CRM Master Data Change Log", filters={"status": "Pending Effective"}, pluck="name"):
		change = frappe.get_doc("CRM Master Data Change Log", name)
		if get_datetime(change.effective_at) <= now_datetime():
			_apply_if_due(change)
			with _internal_flag("crm_governance_log_update"):
				change.save(ignore_permissions=True)
			applied += 1
	return {"status": "ok", "applied": applied}


def expire_break_glass_requests():
	if not getattr(frappe.flags, "in_test", False):
		from crm.fcrm.governance_audit_flags import governance_write_enabled
		if not governance_write_enabled():
			return {"status": "disabled", "expired": 0}
	expired = 0
	for name in frappe.get_all("CRM Master Data Break Glass", filters={"status": ["in", ["Requested", "Authorized"]]}, pluck="name"):
		request = frappe.get_doc("CRM Master Data Break Glass", name)
		if get_datetime(request.expires_at) <= now_datetime():
			request.status = "Expired"
			with _internal_flag("crm_break_glass_update"):
				request.save(ignore_permissions=True)
			expired += 1
	return {"status": "ok", "expired": expired}


@frappe.whitelist()
def migrate_references(change_log_name):
	"""Explicit, idempotent migration after a Supersede; no destructive rename."""
	_require_write_enabled()
	from crm.fcrm.governance_audit_flags import migration_enabled
	if not getattr(frappe.flags, "in_test", False) and not migration_enabled():
		frappe.throw("Phase 9 governance migrations are not enabled.", frappe.PermissionError)
	change = frappe.get_doc("CRM Master Data Change Log", change_log_name)
	if change.action != "Supersede" or change.status != "Applied":
		frappe.throw("Only an applied supersession can migrate references.")
	if change.reference_migration_completed_at:
		return json.loads(change.reference_migration_summary or "{}")
	counts = {}
	for ref in _governed_config(change.reference_doctype)["consumers"]:
		filters = {ref["fieldname"]: change.reference_docname}
		counts[f"{ref['doctype']}.{ref['fieldname']}"] = frappe.db.count(ref["doctype"], filters)
		if counts[f"{ref['doctype']}.{ref['fieldname']}"]:
			frappe.db.set_value(ref["doctype"], filters, ref["fieldname"], change.new_value, update_modified=False)
	change.reference_migration_summary, change.reference_migration_completed_at = json.dumps(counts, sort_keys=True), now_datetime()
	with _internal_flag("crm_governance_log_update"):
		change.save(ignore_permissions=True)
	return counts
