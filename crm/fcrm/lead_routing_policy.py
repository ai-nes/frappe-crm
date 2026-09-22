"""Configurable Lead routing policy and scope resolution.

The policy deliberately contains a small, governed rule catalogue instead of
arbitrary expressions.  This keeps the assignment decision explainable while
allowing operators to enable/disable layers, reorder them and choose the
distribution strategy.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from crm.fcrm.team_routing import (
	_active_teams_for_campus,
	_active_teams_for_group,
	_active_teams_for_province,
	select_recipient_for_teams,
)

CONTROL_DOCTYPE = "CRM Assignment Control"
LAYER_KEYS = ("campaign", "group", "global")
LAYER_LABELS = {
	"campaign": "Theo chiến dịch",
	"group": "Theo Team Group/tỉnh",
	"global": "Chia đều trong campus",
}
STRATEGIES = ("least_load", "round_robin")
DEFAULT_LAYER_ORDER = list(LAYER_KEYS)


def _as_bool(value: Any, default: bool = False) -> bool:
	if value is None:
		return default
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "on"}
	return bool(value)


def _control_values() -> dict[str, Any]:
	if not frappe.db.exists("DocType", CONTROL_DOCTYPE):
		return {}
	try:
		doc = frappe.get_single(CONTROL_DOCTYPE)
		return {fieldname: doc.get(fieldname) for fieldname in (
			"routing_enabled",
			"capacity_required",
			"lead_campaign_layer_enabled",
			"lead_group_layer_enabled",
			"lead_global_layer_enabled",
			"lead_layer_order",
			"lead_distribution_strategy",
			"revision",
			"last_changed_by",
			"last_change_reason",
		)}
	except Exception:
		return {}


def normalize_layer_order(value: Any) -> list[str]:
	"""Normalize a stored comma-separated/JSON order without losing defaults."""
	if isinstance(value, (list, tuple)):
		values = list(value)
	else:
		text = str(value or "").strip()
		if text.startswith("["):
			try:
				parsed = frappe.parse_json(text)
			except (TypeError, ValueError):
				parsed = []
			values = parsed if isinstance(parsed, list) else []
		else:
			values = text.split(",") if text else []

	result: list[str] = []
	for value in values:
		key = str(value or "").strip().casefold()
		if key in LAYER_KEYS and key not in result:
			result.append(key)
	for key in DEFAULT_LAYER_ORDER:
		if key not in result:
			result.append(key)
	return result


def normalize_strategy(value: Any) -> str:
	value = str(value or "").strip().casefold()
	return value if value in STRATEGIES else "least_load"


def get_lead_routing_policy(control: dict[str, Any] | None = None) -> dict[str, Any]:
	control = control or _control_values()
	order = normalize_layer_order(control.get("lead_layer_order"))
	# Existing singletons predate the governed Lead policy fields. Frappe adds
	# new Check columns as 0 on those rows even though the DocType defaults are
	# enabled; an empty order/strategy is the unambiguous legacy signature.
	legacy_defaults = not str(control.get("lead_layer_order") or "").strip() and not str(
		control.get("lead_distribution_strategy") or ""
	).strip()
	layer_enabled = {
		"campaign": True if legacy_defaults else _as_bool(control.get("lead_campaign_layer_enabled"), True),
		"group": True if legacy_defaults else _as_bool(control.get("lead_group_layer_enabled"), True),
		"global": True if legacy_defaults else _as_bool(control.get("lead_global_layer_enabled"), True),
	}
	revision = int(control.get("revision") or 0)
	return {
		"enabled": _as_bool(control.get("routing_enabled"), False),
		"layers": [
			{
				"key": key,
				"label": LAYER_LABELS[key],
				"enabled": layer_enabled[key],
				"priority": index + 1,
			}
			for index, key in enumerate(order)
		],
		"layerOrder": order,
		"distributionStrategy": normalize_strategy(control.get("lead_distribution_strategy")),
		"capacityRequired": _as_bool(control.get("capacity_required"), True),
		"revision": revision,
		"version": f"lead-routing-v{revision}",
		"applyScope": "new_decisions",
		"sameCampus": True,
		"teamLeadFallback": False,
		"lastChangedBy": control.get("last_changed_by"),
		"lastChangeReason": control.get("last_change_reason"),
	}


def validate_policy_payload(
	*,
	enabled: Any = None,
	layer_order: Any = None,
	campaign_layer_enabled: Any = None,
	group_layer_enabled: Any = None,
	global_layer_enabled: Any = None,
	distribution_strategy: Any = None,
	capacity_required: Any = None,
) -> dict[str, Any]:
	"""Return normalized update values and reject unsupported rule shapes."""
	order = None if layer_order is None else normalize_layer_order(layer_order)
	strategy = None if distribution_strategy in (None, "") else normalize_strategy(distribution_strategy)
	if distribution_strategy not in (None, "") and str(distribution_strategy).strip().casefold() not in STRATEGIES:
		frappe.throw(_("Thuật toán phân bổ không được hỗ trợ."), frappe.ValidationError)
	return {
		"routing_enabled": None if enabled is None else int(_as_bool(enabled)),
		"lead_layer_order": None if order is None else ",".join(order),
		"lead_campaign_layer_enabled": (
			None if campaign_layer_enabled is None else int(_as_bool(campaign_layer_enabled))
		),
		"lead_group_layer_enabled": None if group_layer_enabled is None else int(_as_bool(group_layer_enabled)),
		"lead_global_layer_enabled": None if global_layer_enabled is None else int(_as_bool(global_layer_enabled)),
		"lead_distribution_strategy": strategy,
		"capacity_required": None if capacity_required is None else int(_as_bool(capacity_required)),
	}


def _routing_error(code: str, message: str):
	exception = frappe.ValidationError(message)
	exception.code = code
	exception.error_code = code
	raise exception


def _campaign_scope(lead, campus: str | None, *, team_id: str | None = None) -> tuple[list[dict[str, Any]], str] | None:
	campaign = str(lead.get("campaign") or "").strip()
	if not campaign:
		return None
	if not frappe.db.exists("CRM Campaign", campaign):
		return None
	row = frappe.db.get_value(
		"CRM Campaign",
		campaign,
		[
			"name",
			"title",
			"campus",
			"lead_routing_enabled",
			"lead_routing_target_type",
			"lead_routing_target_team",
			"lead_routing_target_group",
		],
		as_dict=True,
	)
	if not row or not _as_bool(row.get("lead_routing_enabled"), False):
		return None
	if row.get("campus") and campus and row.get("campus") != campus:
		_routing_error("CAMPAIGN_TARGET_UNAVAILABLE", "Campaign không cùng cơ sở với Lead.")
	target_type = str(row.get("lead_routing_target_type") or "").strip()
	if target_type == "Team":
		target = row.get("lead_routing_target_team")
		if not target:
			_routing_error("CAMPAIGN_MAPPING_INVALID", "Campaign đang bật phân bổ nhưng chưa chọn Team.")
		teams = _active_teams_for_campus(campus, team_id=target)
		if not teams:
			_routing_error("CAMPAIGN_TARGET_UNAVAILABLE", "Team phân bổ của Campaign không còn hoạt động.")
		return teams, f"CAMPAIGN:{campaign}"
	if target_type == "Team Group":
		target = row.get("lead_routing_target_group")
		if not target:
			_routing_error("CAMPAIGN_MAPPING_INVALID", "Campaign đang bật phân bổ nhưng chưa chọn Team Group.")
		teams = _active_teams_for_group(target, campus=campus, team_id=team_id)
		if not teams:
			_routing_error("CAMPAIGN_TARGET_UNAVAILABLE", "Team Group phân bổ của Campaign không còn hoạt động.")
		return teams, f"CAMPAIGN:{campaign}"
	_routing_error("CAMPAIGN_MAPPING_INVALID", "Campaign đang bật phân bổ nhưng loại đích không hợp lệ.")


def resolve_lead_recipient(
	lead,
	*,
	policy: dict[str, Any] | None = None,
	province: str | None = None,
	campus: str | None = None,
	team_id: str | None = None,
	load_overrides: dict[str, int] | None = None,
) -> dict[str, Any]:
	"""Resolve one Lead according to the active ordered policy layers."""
	policy = policy or get_lead_routing_policy()
	if not policy.get("enabled"):
		_routing_error("LEAD_ROUTING_DISABLED", "Cơ chế phân bổ Lead đang được tắt.")
	campus = str(campus or lead.get("branch") or "").strip() or None
	if not campus:
		_routing_error("MISSING_CAMPUS", "Lead chưa xác định cơ sở để phân bổ an toàn.")

	for layer in policy.get("layers") or []:
		if not layer.get("enabled"):
			continue
		key = layer.get("key")
		teams: list[dict[str, Any]] = []
		scope_key = ""
		if key == "campaign":
			campaign_scope = _campaign_scope(lead, campus, team_id=team_id)
			if campaign_scope is None:
				continue
			teams, scope_key = campaign_scope
		elif key == "group":
			if not province:
				continue
			teams = _active_teams_for_province(province, campus=campus, team_id=team_id)
			if not teams:
				_routing_error(
					"GROUP_TARGET_UNAVAILABLE",
					"Chưa có Team Sales đang hoạt động trong phạm vi tỉnh của Lead.",
				)
			scope_key = f"GROUP:{province}"
		elif key == "global":
			teams = _active_teams_for_campus(campus, team_id=team_id)
			scope_key = f"GLOBAL:{campus}"
		if not teams:
			_routing_error("NO_ELIGIBLE_RECIPIENT", "Không có Team đang hoạt động trong phạm vi phân bổ.")
		return select_recipient_for_teams(
			teams,
			scope_key=scope_key,
			policy_version=policy["version"],
			strategy=policy.get("distributionStrategy") or "least_load",
			require_capacity=bool(policy.get("capacityRequired", True)),
			load_overrides=load_overrides,
		)

	_routing_error(
		"NO_ROUTING_LAYER",
		"Không có lớp phân bổ nào đang bật và phù hợp với Lead này.",
	)
