"""Server-side rollout gates for Phase 9 governance and audit surfaces."""

from __future__ import annotations

import frappe


DEFAULTS = {
	"audit_read": False,
	"governance_write": False,
	"governance_migration": False,
}


def enabled(feature: str, default: bool | None = None) -> bool:
	"""Read a site-config flag; callers cannot override it through request data."""
	if feature not in DEFAULTS and default is None:
		default = False
	if default is None:
		default = DEFAULTS.get(feature, False)
	conf = getattr(frappe, "conf", {}) or {}
	value = conf.get(f"crm_phase9_{feature}_enabled", default)
	return value not in (0, "0", False, "false", "False", None)


def audit_read_enabled() -> bool:
	return enabled("audit_read")


def governance_write_enabled() -> bool:
	return enabled("governance_write")


def migration_enabled() -> bool:
	return enabled("governance_migration")
