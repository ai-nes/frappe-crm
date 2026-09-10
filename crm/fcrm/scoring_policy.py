"""Score policy resolution and versioning. Resolves an Active
`CRM Score Template`'s discriminated CRM Score Rule child rows against
their linked `CRM Score Signal` content, and computes
the `policy_hash`/`policy_revision` pair from exactly that resolved structure.

Shared by the `CRM Score Template` controller (`before_save` recomputes its own
policy_hash/revision) and `CRM Score Signal` (`on_update` re-saves every Active
template referencing it, since the signal's own content — not the template's
rows — is what changed) so both compute policy_hash from the same function,
never a second ad hoc copy. Frappe's local scoring engine consumes the already-
resolved, already-versioned result directly.
"""

import hashlib
import json

import frappe

# Bump when the internal resolved rule/negative-rule shape changes.
POLICY_CONTRACT_VERSION = 1

_SIGNAL_FIELDS = [
	"name",
	"label",
	"category",
	"signal_type",
	"is_active",
	"condition_field",
	"condition_operator",
	"condition_value",
	"interaction_term",
	"intent_type",
	"intent_role",
	"intent_polarity",
	"min_confidence",
	"intent_max_age_days",
	"inactivity_days",
]


def _signal_docs(signal_names: set) -> dict:
	"""Read signal content regardless of the calling session's own CRM Score
	Signal row permission. This is internal policy-resolution plumbing, not a
	user-facing read — the caller (the versioned endpoint, gated by
	`_require_agent_identity`, or a CRM Score Template save the form layer
	already permission-checked) is already authorized to see the resolved
	policy. Without this, a signal invisible to the current session silently
	drops every rule that references it (a fail-open, not fail-closed, scoring
	regression) instead of raising.
	"""
	if not signal_names:
		return {}
	rows = frappe.get_all(
		"CRM Score Signal",
		filters={"name": ["in", list(signal_names)], "is_active": 1},
		fields=_SIGNAL_FIELDS,
		ignore_permissions=True,
	)
	return {r["name"]: r for r in rows}


def resolve_policy_rules(template_doc) -> tuple[list[dict], list[dict], list[dict]]:
	"""Return (rules, negative_rules, time_decay_config) resolved from
	`template_doc`'s discriminated child rows joined with their current, active signal
	content — the exact shape both the versioning hash and the crm-agents
	endpoint consume."""
	signal_names = {row.signal for row in template_doc.rules if row.signal and row.rule_kind != "time_decay"}
	signals = _signal_docs(signal_names)

	rules = []
	for row in template_doc.rules:
		if (row.rule_kind or "positive") != "positive":
			continue
		sig = signals.get(row.signal)
		if not sig:
			frappe.logger("crm").warning(
				f"CRM Score Template {template_doc.name!r}: score rule signal "
				f"{row.signal!r} is missing/inactive; rule dropped from resolved policy."
			)
			continue
		rules.append(
			{
				"signal_key": sig["name"],
				"signal_label": sig.get("label") or sig["name"],
				"category": sig.get("category") or "",
				"signal_type": sig.get("signal_type") or "",
				"base_points": float(row.base_points or 0),
				"max_points": float(row.max_points or 0),
				"is_active": bool(row.is_active),
				"condition_field": sig.get("condition_field"),
				"condition_operator": sig.get("condition_operator"),
				"condition_value": sig.get("condition_value"),
				"interaction_semantic_key": sig.get("interaction_term") or None,
				"intent_semantic_key": sig.get("intent_type") or None,
				"intent_role": sig.get("intent_role"),
				"intent_polarity": sig.get("intent_polarity"),
				"min_confidence": float(sig.get("min_confidence") or 0),
				"intent_max_age_days": int(sig.get("intent_max_age_days") or 0),
				"inactivity_days": int(sig.get("inactivity_days") or 30),
			}
		)

	negative_rules = []
	for row in template_doc.rules:
		if row.rule_kind != "negative":
			continue
		sig = signals.get(row.signal)
		if not sig:
			frappe.logger("crm").warning(
				f"CRM Score Template {template_doc.name!r}: negative rule signal "
				f"{row.signal!r} is missing/inactive; rule dropped from resolved policy."
			)
			continue
		negative_rules.append(
			{
				"signal_key": sig["name"],
				"signal_label": sig.get("label") or sig["name"],
				"signal_type": sig.get("signal_type") or "",
				"is_active": bool(row.is_active),
				"penalty_amount": float(row.penalty_amount or 0),
				"cooldown_days": int(row.cooldown_days or 0),
				"max_penalties": int(row.max_penalties or 0),
				"interaction_semantic_key": sig.get("interaction_term") or None,
				"inactivity_days": int(sig.get("inactivity_days") or 30),
			}
		)

	time_decay_config = [
		{
			"max_days": int(row.max_days or 0),
			"multiplier": float(row.multiplier or 1.0),
			"tier_label": row.get("tier_label") or "",
		}
		for row in template_doc.rules
		if row.rule_kind == "time_decay"
	]
	return rules, negative_rules, time_decay_config


def _canonical_json(value) -> str:
	return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def compute_policy_hash(
	template_doc, rules: list[dict], negative_rules: list[dict], time_decay_config: list[dict]
) -> str:
	body = {
		"contract_version": POLICY_CONTRACT_VERSION,
		"template_name": template_doc.template_name,
		"fit_weight": float(template_doc.fit_weight or 0),
		"engagement_weight": float(template_doc.engagement_weight or 0),
		"intent_weight": float(template_doc.intent_weight or 0),
		"effective_from": str(template_doc.start_time or ""),
		"effective_until": str(template_doc.end_time or ""),
		"rules": rules,
		"negative_rules": negative_rules,
		"time_decay_config": time_decay_config,
	}
	return hashlib.sha256(_canonical_json(body).encode()).hexdigest()


def sync_policy_revision(template_doc) -> None:
	"""Recompute this template's policy_hash from its currently resolved
	content and bump policy_revision only when the hash actually changed.
	Called from `CRMScoreTemplate.before_save` (covers direct edits to the
	template or its child rows) and, via `bump_active_templates_for_signal`'s
	re-save, when a linked `CRM Score Signal`'s own fields change instead.
	"""
	rules, negative_rules, time_decay_config = resolve_policy_rules(template_doc)
	new_hash = compute_policy_hash(template_doc, rules, negative_rules, time_decay_config)
	if new_hash != template_doc.policy_hash:
		template_doc.policy_hash = new_hash
		template_doc.policy_revision = int(template_doc.policy_revision or 0) + 1


def bump_active_templates_for_signal(signal_name: str) -> None:
	"""A `CRM Score Signal` save changes rule *content* without touching any
	`CRM Score Template`'s own rows — every Active template that references
	this signal (in either rule table) must recompute its policy_hash, so
	crm-agents observes the change without waiting for an unrelated template
	edit."""
	template_names: set = set()
	parents = frappe.get_all(
		"CRM Score Rule",
		filters={"signal": signal_name, "parenttype": "CRM Score Template"},
		fields=["parent"],
		distinct=True,
	)
	template_names.update(p.parent for p in parents)
	if not template_names:
		return
	active = frappe.get_all(
		"CRM Score Template",
		filters={"name": ["in", list(template_names)], "status": "Active"},
		pluck="name",
	)
	for name in active:
		frappe.get_doc("CRM Score Template", name).save(ignore_permissions=True)


def get_active_policy(*, as_of=None) -> dict | None:
	"""Return the fully resolved, versioned policy for the single Active
	`CRM Score Template`, or None if none is Active."""
	current = as_of or frappe.utils.now_datetime()
	template_name = frappe.db.get_value("CRM Score Template", {"status": "Active"}, "name")
	if not template_name:
		return None
	template_doc = frappe.get_doc("CRM Score Template", template_name)
	if template_doc.start_time and frappe.utils.get_datetime(
		template_doc.start_time
	) > frappe.utils.get_datetime(current):
		return None
	if template_doc.end_time and frappe.utils.get_datetime(
		template_doc.end_time
	) <= frappe.utils.get_datetime(current):
		return None
	rules, negative_rules, time_decay_config = resolve_policy_rules(template_doc)
	return {
		"contract_version": POLICY_CONTRACT_VERSION,
		"template_id": template_doc.name,
		"template_name": template_doc.template_name,
		"policy_revision": int(template_doc.policy_revision or 0),
		"policy_hash": template_doc.policy_hash or "",
		"fit_weight": float(template_doc.fit_weight or 0),
		"engagement_weight": float(template_doc.engagement_weight or 0),
		"intent_weight": float(template_doc.intent_weight or 0),
		"effective_from": str(template_doc.start_time or "") or None,
		"effective_until": str(template_doc.end_time or "") or None,
		"rules": rules,
		"negative_rules": negative_rules,
		"time_decay_config": time_decay_config,
	}
