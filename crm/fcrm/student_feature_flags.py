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
	"migration": False,
	"conversion_read": False,
	"conversion_write": False,
	"role_workspace_read": False,
	# Director analytics is the primary Director workspace, not an experimental
	# replacement for Sales/Marketing workspaces. Keep its server reader on by
	# default while the broad role-workspace rollout remains opt-in.
	"director_analytics_read": True,
}
ASSIGNMENT_MODES = frozenset({"manual_batch", "automatic_on_create"})
ALIASES = {
	"context_read": "context",
	"engagement_write": "engagement",
	"lifecycle_write": "lifecycle",
}


def enabled(feature: str, default: bool | None = None) -> bool:
	"""Read one server-side feature flag without accepting client overrides."""
	if feature not in DEFAULTS and default is None:
		default = False
	if default is None:
		default = DEFAULTS.get(feature, False)
	# The assignment workspace owns the routing switch once its singleton has
	# been changed from the UI.  Keep the site-config fallback so existing
	# fixtures and sites remain compatible until an administrator saves the
	# first workspace setting.
	if feature == "routing":
		try:
			if frappe.db.exists("DocType", "CRM Assignment Control"):
				stored = frappe.db.get_single_value("CRM Assignment Control", "routing_enabled")
				if stored is not None:
					return stored not in (0, "0", False, "false", "False", None)
		except Exception:
			pass
	conf = getattr(frappe, "conf", {})
	key = f"crm_student_{feature}_enabled"
	alias_key = f"crm_student_{ALIASES.get(feature, feature)}_enabled"
	value = conf.get(key, conf.get(alias_key, default))
	return value not in (0, "0", False, "false", "False", None)


def assignment_mode() -> str:
	"""Return the server-owned assignment execution mode.

	The core Lead refactor defaults to explicit batches.  The automatic-on-create
	value is retained only as a controlled compatibility option while old intake
	callers are migrated; it is not a background-worker switch.
	"""
	default = "manual_batch"
	try:
		if frappe.db.exists("DocType", "CRM Assignment Control"):
			stored = frappe.db.get_single_value("CRM Assignment Control", "assignment_mode")
			if stored in ASSIGNMENT_MODES:
				return stored
	except Exception:
		pass
	conf = getattr(frappe, "conf", {})
	value = conf.get("crm_assignment_mode", default)
	return value if value in ASSIGNMENT_MODES else default


def automatic_assignment_on_create_enabled() -> bool:
	"""Whether a compatibility intake path may route immediately."""
	return enabled("routing") and assignment_mode() == "automatic_on_create"


def context_read_enabled() -> bool:
	return enabled("context_read")


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
