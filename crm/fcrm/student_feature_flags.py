"""Independent Student rollout gates.

Flags are server-side only.  A disabled flag must make a command unavailable;
turning a flag off never deletes append-only events or mutates projections.
"""

import frappe

DEFAULTS = {
	"routing": False,
	"sla": False,
	"delivery": False,
	"context_read": False,
	"engagement_write": False,
	"lifecycle_write": False,
	"legacy_read": True,
	"migration": False,
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
