"""Independent Student rollout gates.

Flags are server-side only.  A disabled flag must make a command unavailable;
turning a flag off never deletes append-only events or mutates projections.
"""

import frappe

DEFAULTS = {
	"routing": False,
	"synchronous_routing": False,
	"sla": False,
	"delivery": False,
	"shared_sla_outbox": False,
	"context_read": False,
	"engagement_write": False,
	"lifecycle_write": False,
	"legacy_read": True,
	"migration": False,
	"conversion_read": False,
	"conversion_write": False,
	"role_workspace_read": False,
	# Director analytics is the primary Director workspace, not an experimental
	# replacement for Sales/Marketing workspaces. Keep its server reader on by
	# default while the broad role-workspace rollout remains opt-in.
	"director_analytics_read": True,
}
ALIASES = {
	"context_read": "context",
	"engagement_write": "engagement",
	"lifecycle_write": "lifecycle",
	"legacy_read": "legacy",
}


def enabled(feature: str, default: bool | None = None) -> bool:
	"""Read one server-side feature flag without accepting client overrides."""
	if feature not in DEFAULTS and default is None:
		default = False
	if default is None:
		default = DEFAULTS.get(feature, False)
	conf = getattr(frappe, "conf", {})
	key = f"crm_student_{feature}_enabled"
	alias_key = f"crm_student_{ALIASES.get(feature, feature)}_enabled"
	value = conf.get(key, conf.get(alias_key, default))
	return value not in (0, "0", False, "false", "False", None)


def writes_enabled() -> bool:
	"""Whether Phase 5 command writes may be accepted."""
	return enabled("engagement_write") and enabled("lifecycle_write")


def context_read_enabled() -> bool:
	return enabled("context_read")


def legacy_read_enabled() -> bool:
	return enabled("legacy_read", default=True)


def role_workspace_read_enabled() -> bool:
	"""Whether the read-only role-workspace facade is available server-side."""
	return enabled("role_workspace_read")


def director_analytics_read_enabled() -> bool:
	"""Whether the Director analytics canary is enabled alongside the workspace reader.

	The caller must still be authorized as an Admissions Director by the
	workspace policy.  This function deliberately only defines the two server
	rollout switches; it never accepts a browser-provided override.
	"""
	return enabled("director_analytics_read")


def ai_staleness_threshold_seconds() -> float | None:
	"""Return the server-owned AI freshness window; invalid values fail safe."""
	# Imported lazily: crm.api.__init__ pulls in crm.api.session, which imports
	# back from this module — a module-level import here would be circular.
	from crm.api._ai_staleness import ai_staleness_threshold_seconds as _threshold

	return _threshold()
