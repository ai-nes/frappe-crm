"""Read-only, current-scope data contracts for Lead Sale workspaces.

The browser never chooses a team or staff scope here.  Every reader uses
``frappe.get_list`` so the same CRM Student permission conditions that protect
the list view also protect aggregates and drill-down rows.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from collections import defaultdict
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import get_first_day, getdate, now_datetime
from frappe.utils.password import get_encryption_key

from crm.fcrm.role_policy import capabilities_for_roles


_MAX_PAGE_SIZE = 50
_OPEN_ACTION_STATES = ("pending", "accepted", "in-progress", "requires-review", "deferred")
_ACTION_STATUS_FILTERS = {
	"all": None,
	"open": ("in", _OPEN_ACTION_STATES),
	"completed": ("=", "completed"),
	"exception": ("in", ("rejected", "cancelled", "superseded")),
}


def _require_team_oversee():
	actor = frappe.session.user
	if actor == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	caps = capabilities_for_roles(frappe.get_roles(actor), administrator=actor == "Administrator")
	if "team.oversee" not in caps:
		frappe.throw(_("Lead Sale access is required."), frappe.PermissionError)
	return actor


def _period(value: str | None):
	value = value or "30d"
	today = getdate()
	if value == "7d":
		start = today - timedelta(days=6)
	elif value == "30d":
		start = today - timedelta(days=29)
	elif value == "this_month":
		start = get_first_day(today)
	else:
		frappe.throw(_("period must be one of 7d, 30d, or this_month."), frappe.ValidationError)
	return value, str(start), str(today)


def _definition(period: str | None = None, *, action_status: str | None = None):
	selected, from_date, to_date = _period(period)
	definition = {
		"period": selected,
		"from_date": from_date,
		"to_date": to_date,
		"timezone": frappe.utils.get_system_timezone(),
		"scope": "current_student_permission_scope",
		"student_filters": "CRM Student permission scope derived from the session user",
		"sla_filters": "CRM Student SLA Attempt inheriting the current CRM Student scope",
	}
	if action_status:
		definition["action_status"] = action_status
	return definition


def _snapshot_definition():
	return {
		"period": "current",
		"timezone": frappe.utils.get_system_timezone(),
		"scope": "current_student_permission_scope",
		"student_filters": "Current CRM Student permission scope derived from the session user",
		"sla_filters": "Current CRM Student SLA Attempt scope inherited from CRM Student",
	}


def _generated():
	return str(now_datetime())


def _count(doctype: str, filters=None) -> int:
	rows = frappe.get_list(
		doctype,
		filters=filters or {},
		fields=["count(name) as count"],
		limit_page_length=1,
	)
	return int(rows[0].get("count", 0)) if rows else 0


def _grouped_count(doctype: str, field: str, filters=None):
	"""Aggregate in the database without silently truncating team members."""
	return frappe.get_list(
		doctype,
		filters=filters or {},
		fields=[field, "count(name) as count"],
		group_by=field,
		order_by="count desc",
		limit_page_length=0,
	)


def _date_filters(period: str | None):
	_definition(period)  # validates period in one place
	_, from_date, to_date = _period(period)
	return [["creation", ">=", from_date], ["creation", "<", str(getdate(to_date) + timedelta(days=1))]]


def _completed_action_date_filters(period: str | None):
	"""Use CRM Action's canonical completion time, never record creation."""
	_definition(period)
	_, from_date, to_date = _period(period)
	return [
		["completed_at", ">=", from_date],
		["completed_at", "<", str(getdate(to_date) + timedelta(days=1))],
	]


def _action_filters(status: str):
	if status not in _ACTION_STATUS_FILTERS:
		frappe.throw(_("Unsupported Action status."), frappe.ValidationError)
	operator_and_value = _ACTION_STATUS_FILTERS[status]
	return [["state", operator_and_value[0], operator_and_value[1]]] if operator_and_value else []


@frappe.whitelist()
def get_team_dashboard() -> dict:
	"""Return current-scope workload and SLA aggregates for Lead Sale."""
	_require_team_oversee()
	definition = _snapshot_definition()
	workload = [
		{"owner_staff": row.get("owner_staff") or None, "count": int(row.get("count", 0))}
		for row in _grouped_count("CRM Student", "owner_staff")
	]
	sla_buckets = [
		{"status": row.get("status"), "count": int(row.get("count", 0))}
		for row in _grouped_count("CRM Student SLA Attempt", "status")
	]
	return {
		"definition": definition,
		"generated_at": _generated(),
		"kpis": {
			"active_students": _count("CRM Student", {"lifecycle_stage": ["not in", ["Lost"]]}),
			"unassigned_students": _count("CRM Student", {"owner_staff": ["is", "not set"]}),
			"breached_sla": _count("CRM Student SLA Attempt", {"status": ["in", ["breached", "escalated"]]}),
		},
		"workload": workload,
		"sla_buckets": sla_buckets,
	}


@frappe.whitelist()
def get_member_performance(period: str | None = "30d") -> dict:
	"""Return server-aggregated member measures; no paginated client roll-up."""
	_require_team_oversee()
	definition = _definition(period)
	members = defaultdict(lambda: {"staff": None, "name": None, "students": 0, "current_actions": 0, "completed_actions": 0, "breached_sla": 0})
	for row in _grouped_count("CRM Student", "owner_staff"):
		staff = row.get("owner_staff")
		if staff:
			members[staff]["staff"] = staff
			members[staff]["students"] = int(row.get("count", 0))
	for row in _grouped_count("CRM Action Item", "action_owner", {"state": ["in", list(_OPEN_ACTION_STATES)]}):
		staff = row.get("action_owner")
		if staff:
			members[staff]["staff"] = staff
			members[staff]["current_actions"] = int(row.get("count", 0))
	for row in _grouped_count("CRM Action Item", "action_owner", _completed_action_date_filters(period) + [["state", "=", "completed"]]):
		staff = row.get("action_owner")
		if staff:
			members[staff]["staff"] = staff
			members[staff]["completed_actions"] = int(row.get("count", 0))
	# SLA attempts inherit current Student ownership.  Group in the database so
	# every visible owner is counted rather than truncating after an arbitrary
	# number of attempts.
	for row in _grouped_count("CRM Student SLA Attempt", "owner_staff", {"status": ["in", ["breached", "escalated"]]}):
		staff = row.get("owner_staff")
		if staff:
			members[staff]["staff"] = staff
			members[staff]["breached_sla"] = int(row.get("count", 0))
	if members:
		staff_names = list(members)
		for staff in frappe.get_list("CRM Staff", filters={"name": ["in", staff_names]}, fields=["name", "full_name"], limit_page_length=0):
			members[staff.name]["name"] = staff.get("full_name") or staff.name
	return {"definition": definition, "generated_at": _generated(), "members": sorted(members.values(), key=lambda row: (row["name"] or row["staff"]))}


@frappe.whitelist()
def list_team_actions(status: str = "open", cursor: str | None = None, page_size: int | str = 20) -> dict:
	"""Return a permission-filtered CRM Action queue, never generic Tasks."""
	actor = _require_team_oversee()
	page_size = _parse_page_size(page_size)
	filters = _action_filters(status)
	start = _decode_cursor(cursor, actor, status) if cursor else 0
	rows = frappe.get_list(
		"CRM Action Item",
		filters=filters,
		fields=["name", "student", "action", "action_type", "objective", "state", "execution_status", "priority", "due_at", "action_owner"],
		order_by="due_at asc, creation asc, name asc",
		start=start,
		limit_page_length=page_size + 1,
	)
	has_more = len(rows) > page_size
	page = rows[:page_size]
	student_names = [row.student for row in page if row.get("student")]
	students = {
		row.name: row.get("student_name")
		for row in frappe.get_list("CRM Student", filters={"name": ["in", student_names or ["__none__"]]}, fields=["name", "student_name"], limit_page_length=0)
	}
	return {
		"definition": _definition(action_status=status),
		"generated_at": _generated(),
		"rows": [{**dict(row), "student_name": students.get(row.get("student")), "due_at": str(row.due_at) if row.get("due_at") else None} for row in page],
		"next_cursor": _encode_cursor(start + len(page), actor, status) if has_more else None,
	}


@frappe.whitelist()
def get_team_reports(period: str | None = "30d") -> dict:
	"""Fixed, scoped period cards, defined on the server with their filters."""
	_require_team_oversee()
	definition = _definition(period)
	period_filters = _date_filters(period)
	return {
		"definition": definition,
		"generated_at": _generated(),
		"cards": [
			{"key": "new_students", "label": _("New students"), "value": _count("CRM Student", period_filters), "description": _("Students created in the selected period within your current team scope.")},
			{"key": "completed_actions", "label": _("Completed actions"), "value": _count("CRM Action Item", _completed_action_date_filters(period) + [["state", "=", "completed"]]), "description": _("CRM Actions completed in the selected period within your current team scope.")},
			{"key": "breached_sla", "label": _("Breached SLA"), "value": _count("CRM Student SLA Attempt", period_filters + [["status", "in", ["breached", "escalated"]]]), "description": _("SLA attempts created in the selected period within your current Student scope.")},
		],
	}


@frappe.whitelist()
def get_readonly_sla_policies() -> dict:
	"""Return a deliberately safe projection; no approver or mutation controls."""
	_require_team_oversee()
	# SLA Policy is a control-plane DocType, so Lead Sale intentionally has no
	# raw DocPerm read grant.  This narrowly selected service projection is the
	# authorized read path; it exposes neither approver nor mutation fields.
	visible_scopes = {
		(row.get("branch"), row.get("owning_pool"))
		for row in frappe.get_list(
			"CRM Student",
			fields=["branch", "owning_pool"],
			group_by="branch, owning_pool",
			limit_page_length=0,
		)
	}
	policies = frappe.get_all(
		"CRM Student SLA Policy",
		filters={"status": "active"},
		fields=["name", "policy_key", "policy_version", "status", "campus", "student_pool", "warning_minutes", "breach_minutes", "escalation_minutes", "effective_from", "effective_until"],
		order_by="policy_key asc, policy_version desc",
		limit_page_length=0,
	)
	return {
		"definition": {"scope": "current_readable_student_campus_and_pool", "read_only": True},
		"generated_at": _generated(),
		"policies": [
			dict(policy)
			for policy in policies
			if (policy.get("campus"), policy.get("student_pool")) in visible_scopes
		],
	}


def _parse_page_size(value: int | str) -> int:
	try:
		value = int(value)
	except (TypeError, ValueError):
		frappe.throw(_("page_size must be an integer."), frappe.ValidationError)
	if not 1 <= value <= _MAX_PAGE_SIZE:
		frappe.throw(_("page_size must be between 1 and {0}.").format(_MAX_PAGE_SIZE), frappe.ValidationError)
	return value


def _cursor_secret():
	return f"crm-lead-sales-workspace:{get_encryption_key()}".encode()


def _encode_cursor(start: int, actor: str, status: str) -> str:
	body = json.dumps({"start": start, "actor": actor, "status": status}, sort_keys=True, separators=(",", ":")).encode()
	signature = hmac.new(_cursor_secret(), body, hashlib.sha256).digest()
	return f"{_urlsafe_encode(body)}.{_urlsafe_encode(signature)}"


def _decode_cursor(cursor: str, actor: str, status: str) -> int:
	try:
		body_token, signature_token = cursor.split(".", 1)
		body, signature = _urlsafe_decode(body_token), _urlsafe_decode(signature_token)
		payload = json.loads(body)
		if not hmac.compare_digest(signature, hmac.new(_cursor_secret(), body, hashlib.sha256).digest()):
			raise ValueError
		if payload.get("actor") != actor or payload.get("status") != status or not isinstance(payload.get("start"), int) or payload["start"] < 0:
			raise ValueError
		return payload["start"]
	except (AttributeError, TypeError, ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
		frappe.throw(_("Invalid team Action cursor."), frappe.PermissionError)


def _urlsafe_encode(value: bytes) -> str:
	return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _urlsafe_decode(value: str) -> bytes:
	return base64.urlsafe_b64decode(f"{value}{'=' * (-len(value) % 4)}")
