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
	badge_workspaces,
	derive_workspace_policy,
	normalize_filters,
	route_for_menu_id,
)
from crm.fcrm.student_feature_flags import role_workspace_read_enabled

_SNAPSHOT_TTL_SECONDS = 300
_DEFINITION_VERSION = "role-workspace-read-v1"


def _unavailable(kind: str) -> dict:
	response = {"contractStatus": "unavailable", "snapshot": None, "explanation": "Role workspace reader is disabled."}
	if kind == "summary":
		response.update({"title": None, "filterSchema": {}, "kpis": [], "actions": [], "drillDown": []})
	elif kind == "rows":
		response.update({"rows": [], "cursor": None, "total": None})
	elif kind == "series":
		response.update({"series": [], "definitionVersion": _DEFINITION_VERSION})
	else:
		response.update({"badges": {}})
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


def _mint_snapshot(policy, workspace: str, view: str, filters: dict, *, watermark: str | None = None) -> str:
	payload = {"actor": policy.actor, "policy": policy.revision, "scope": getattr(policy, "scope_version", None), "workspace": workspace, "view": view, "filters": filters, "watermark": watermark or "unreleased", "expiresAt": int(time.time()) + _SNAPSHOT_TTL_SECONDS}
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
		return payload
	except (AttributeError, TypeError, ValueError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
		frappe.throw(_("Workspace snapshot is invalid or expired; reload and retry."), frappe.PermissionError)


def _request(workspace, view, filters, snapshot):
	policy = derive_workspace_policy()
	view = authorize_workspace(policy, workspace, view)
	filters = normalize_filters(workspace, filters)
	if snapshot:
		_validate_snapshot(snapshot, policy, workspace, view, filters)
	else:
		snapshot = _mint_snapshot(policy, workspace, view, filters)
	return policy, view, filters, snapshot


@frappe.whitelist()
def get_workspace_summary(workspace: str, view: str | None = None, filters=None, snapshot: str | None = None) -> dict:
	if not role_workspace_read_enabled():
		return _unavailable("summary")
	_, _, _, snapshot = _request(workspace, view, filters, snapshot)
	return _migration_required("summary", snapshot)


@frappe.whitelist()
def get_workspace_rows(workspace: str, view: str | None = None, filters=None, cursor: str | None = None, snapshot: str | None = None) -> dict:
	if not role_workspace_read_enabled():
		return _unavailable("rows")
	if cursor:
		frappe.throw(_("Workspace row cursors are unavailable until a provider is released."), frappe.ValidationError)
	_, _, _, snapshot = _request(workspace, view, filters, snapshot)
	return _migration_required("rows", snapshot)


@frappe.whitelist()
def get_workspace_series(workspace: str, view: str | None = None, filters=None, snapshot: str | None = None) -> dict:
	if not role_workspace_read_enabled():
		return _unavailable("series")
	_, _, _, snapshot = _request(workspace, view, filters, snapshot)
	return _migration_required("series", snapshot)


@frappe.whitelist()
def get_workspace_badges() -> dict:
	if not role_workspace_read_enabled():
		return _unavailable("badges")
	policy = derive_workspace_policy()
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
