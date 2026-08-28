"""Read-only facade for role workspaces.

All providers are intentionally conservative until their upstream DTO contracts
are released.  A missing contract returns ``migration_required`` rather than
deriving an operational aggregate from legacy CRM Contact records.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time

import frappe
from frappe import _
from frappe.utils.password import get_encryption_key

from crm.api.workspace_policy import (
	WORKSPACE_POLICY_REVISION,
	authorize_workspace,
	authorize_director_view,
	badge_workspaces,
	derive_workspace_policy,
	normalize_filters,
	route_for_menu_id,
)
from crm.fcrm.student_feature_flags import director_analytics_read_enabled, role_workspace_read_enabled

_SNAPSHOT_TTL_SECONDS = 300
_DEFINITION_VERSION = "role-workspace-read-v1"


def _workspace_reader_enabled() -> bool:
	"""Keep the broad rollout gated while making Director analytics usable by default."""
	if role_workspace_read_enabled():
		return True
	try:
		return (
			derive_workspace_policy().profile == "admissions_director"
			and director_analytics_read_enabled()
		)
	except frappe.PermissionError:
		return False


def _unavailable(kind: str) -> dict:
	response = {"contractStatus": "unavailable", "snapshot": None, "explanation": "Role workspace reader is disabled."}
	if kind == "summary":
		response.update({"title": None, "filterSchema": {}, "kpis": [], "actions": [], "drillDown": []})
	elif kind == "rows":
		response.update({"rows": [], "cursor": None, "total": None})
	elif kind == "series":
		response.update({"series": [], "definitionVersion": _DEFINITION_VERSION})
	elif kind == "badges":
		response.update({"badges": {}})
	else:
		response.update({"download": None, "oneUse": True})
	return response


def _migration_required(kind: str, snapshot: str) -> dict:
	response = {"contractStatus": "migration_required", "snapshot": snapshot, "explanation": "The upstream Student read contract is not released."}
	if kind == "summary":
		response.update({"title": None, "filterSchema": {}, "kpis": [], "actions": [], "drillDown": []})
	elif kind == "rows":
		response.update({"rows": [], "cursor": None, "total": None})
	else:
		response.update({"series": [], "definitionVersion": _DEFINITION_VERSION, "dateCoverage": None})
	return response


def _secret() -> bytes:
	return f"crm-role-workspace-snapshot:{get_encryption_key()}".encode()


def _encode(value: bytes) -> str:
	return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
	return base64.urlsafe_b64decode(f"{value}{'=' * (-len(value) % 4)}")


def _mint_snapshot(policy, workspace: str, view: str, filters: dict, *, watermark: str | None = None, context: dict | None = None) -> str:
	if context is None:
		context = {"definitionVersion": _DEFINITION_VERSION, "timezone": None, "asOf": None, "watermarks": {"default": watermark or "unreleased"}}
	if getattr(policy, "profile", None) == "admissions_director":
		from crm.api.director_analytics import DIRECTOR_DEFINITION_VERSION, DIRECTOR_VIEW_DEFINITIONS
		definition = DIRECTOR_VIEW_DEFINITIONS.get((workspace, view))
		if definition:
			context = context or {"definitionVersion": DIRECTOR_DEFINITION_VERSION, "timezone": definition["definition"]["businessTimezone"], "asOf": None, "watermarks": {source: "unreleased" for source in definition["definition"]["sources"]}}
	payload = {"actor": policy.actor, "policy": policy.revision, "scope": getattr(policy, "scope_version", None), "workspace": workspace, "view": view, "filters": filters, **context, "expiresAt": int(time.time()) + _SNAPSHOT_TTL_SECONDS}
	body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
	return f"{_encode(body)}.{_encode(hmac.new(_secret(), body, hashlib.sha256).digest())}"


def _validate_snapshot(snapshot: str, policy, workspace: str, view: str, filters: dict) -> dict:
	try:
		body_token, signature_token = snapshot.split(".", 1)
		body, signature = _decode(body_token), _decode(signature_token)
		if _encode(body) != body_token or _encode(signature) != signature_token:
			raise ValueError
		if not hmac.compare_digest(signature, hmac.new(_secret(), body, hashlib.sha256).digest()):
			raise ValueError
		payload = json.loads(body)
		if payload.get("expiresAt", 0) < time.time() or any((payload.get("actor") != policy.actor, payload.get("policy") != policy.revision, payload.get("scope") != getattr(policy, "scope_version", None), payload.get("workspace") != workspace, payload.get("view") != view, payload.get("filters") != filters)):
			raise ValueError
		if getattr(policy, "profile", None) == "admissions_director":
			from crm.api.director_analytics import DIRECTOR_DEFINITION_VERSION, DIRECTOR_VIEW_DEFINITIONS
			definition = DIRECTOR_VIEW_DEFINITIONS.get((workspace, view))
			if not definition or payload.get("definitionVersion") != DIRECTOR_DEFINITION_VERSION or payload.get("timezone") != definition["definition"]["businessTimezone"] or not payload.get("asOf") or not payload.get("watermarks") or "unreleased" in payload["watermarks"].values():
				raise ValueError
		return payload
	except (AttributeError, TypeError, ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
		frappe.throw(_("Workspace snapshot is invalid or expired; reload and retry."), frappe.PermissionError)


def _request(workspace, view, filters, snapshot):
	policy = derive_workspace_policy()
	view = authorize_workspace(policy, workspace, view)
	authorize_director_view(policy, workspace, view)
	filters = normalize_filters(workspace, filters, view=view, policy=policy)
	if snapshot:
		_validate_snapshot(snapshot, policy, workspace, view, filters)
	else:
		if policy.profile == "admissions_director":
			from crm.api.director_analytics import snapshot_context
			context = snapshot_context(policy, workspace, view, filters)
			snapshot = _mint_snapshot(policy, workspace, view, filters, context=context) if context else None
		else:
			snapshot = _mint_snapshot(policy, workspace, view, filters)
	return policy, view, filters, snapshot


def _director_response(kind, policy, workspace, view, filters, snapshot, **kwargs):
	from crm.api import director_analytics
	if policy.profile != "admissions_director" or not director_analytics.is_director_view(workspace, view):
		return None
	if not director_analytics_read_enabled():
		return _unavailable(kind)
	return getattr(director_analytics, f"get_{kind}")(policy, workspace, view, filters, snapshot, **kwargs)


@frappe.whitelist()
def get_workspace_summary(workspace: str, view: str | None = None, filters=None, snapshot: str | None = None) -> dict:
	if not _workspace_reader_enabled():
		return _unavailable("summary")
	policy, resolved_view, normalized, snapshot = _request(workspace, view, filters, snapshot)
	if response := _director_response("summary", policy, workspace, resolved_view, normalized, snapshot):
		return response
	return _migration_required("summary", snapshot)


@frappe.whitelist()
def get_workspace_rows(workspace: str, view: str | None = None, filters=None, cursor: str | None = None, snapshot: str | None = None) -> dict:
	if not _workspace_reader_enabled():
		return _unavailable("rows")
	policy, resolved_view, normalized, snapshot = _request(workspace, view, filters, snapshot)
	if response := _director_response("rows", policy, workspace, resolved_view, normalized, snapshot, cursor=cursor):
		return response
	if cursor:
		frappe.throw(_("Workspace row cursors are unavailable until a provider is released."), frappe.ValidationError)
	return _migration_required("rows", snapshot)


@frappe.whitelist()
def get_workspace_series(workspace: str, view: str | None = None, filters=None, snapshot: str | None = None) -> dict:
	if not _workspace_reader_enabled():
		return _unavailable("series")
	policy, resolved_view, normalized, snapshot = _request(workspace, view, filters, snapshot)
	if response := _director_response("series", policy, workspace, resolved_view, normalized, snapshot):
		return response
	return _migration_required("series", snapshot)


@frappe.whitelist()
def get_workspace_export(workspace: str, view: str | None = None, filters=None, snapshot: str | None = None, export_id: str | None = None) -> dict:
	if not _workspace_reader_enabled():
		return _unavailable("export")
	policy, resolved_view, normalized, snapshot = _request(workspace, view, filters, snapshot)
	if response := _director_response("export", policy, workspace, resolved_view, normalized, snapshot, export_id=export_id):
		return response
	return {"contractStatus": "migration_required", "snapshot": snapshot, "download": None, "oneUse": True}


@frappe.whitelist()
def resolve_workspace_row_detail(workspace: str, view: str, filters=None, snapshot: str | None = None, token: str | None = None) -> dict:
	"""Resolve an opaque Director row token to the canonical Student route."""
	policy, resolved_view, normalized, validated_snapshot = _request(workspace, view, filters, snapshot)
	if policy.profile != "admissions_director" or not token:
		frappe.throw(_("Workspace row detail is not available."), frappe.PermissionError)
	from crm.api.director_analytics import validate_row_detail_token
	student = validate_row_detail_token(token, policy, validated_snapshot)
	# Tokens bind the scope revision, but ownership/campus can change after a
	# token was issued. Recheck the current campus before disclosing a route.
	if frappe.db.get_value("CRM Student", student, "branch") not in policy.campuses:
		frappe.throw(_("Workspace row detail is not available."), frappe.PermissionError)
	if not frappe.has_permission("CRM Student", "read", student):
		frappe.throw(_("Workspace row detail is not available."), frappe.PermissionError)
	return {"route": {"name": "Student", "params": {"doctype": "CRM Student", "name": student}}}


@frappe.whitelist()
def get_workspace_badges() -> dict:
	if not _workspace_reader_enabled():
		return _unavailable("badges")
	policy = derive_workspace_policy()
	if policy.profile == "admissions_director":
		if not director_analytics_read_enabled():
			return _unavailable("badges")
		from crm.api import director_analytics
		return {"contractStatus": "ready", "badges": director_analytics.get_badges(policy, _mint_snapshot), "policyVersion": WORKSPACE_POLICY_REVISION}
	badges = {}
	for menu_id in badge_workspaces(policy.profile):
		workspace, view = route_for_menu_id(policy.profile, menu_id)
		filters = normalize_filters(workspace, {})
		badges[menu_id] = {
			"contractStatus": "migration_required",
			"count": None,
			"snapshot": _mint_snapshot(policy, workspace, view, filters),
			"definitionVersion": _DEFINITION_VERSION,
		}
	return {"contractStatus": "ready", "badges": badges, "policyVersion": WORKSPACE_POLICY_REVISION}
