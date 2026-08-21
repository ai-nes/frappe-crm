import hashlib
import json
import time

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from crm.api.session import CRM_ALLOWED_ROLES
from crm.fcrm.doctype.fields_layout.fields_layout import get_permlevel_access

OPERATIONS = ("read", "write", "create", "delete")

# This whitelisted method serves the crm-agents AI copilot, whose real staff
# roles (Sale, CTV-Sale, Counseller, Team Leader, Promoter-PR — see
# app/config.json / app/prompts/domain/sales.md in crm-agents) are broader
# than crm.api.session's desk-CRM-only CRM_ALLOWED_ROLES. Union both rather
# than reusing CRM_ALLOWED_ROLES verbatim, or every AI-copilot staff member
# would be rejected by this gate.
CRM_AI_ALLOWED_ROLES = frozenset(CRM_ALLOWED_ROLES) | {
	"Sale",
	"CTV-Sale",
	"Counseller",
	"Team Leader",
	"Promoter-PR",
}

# Timeout budget for the whole call, not per doctype — a stalled meta lookup on
# one exposed doctype must not block the rest from being reported.
_TIME_BUDGET_S = 8.0


def _canonical_json(value) -> str:
	return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256_hex(value) -> str:
	return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _row_scoped(doctype: str) -> bool:
	return bool(
		frappe.get_hooks("permission_query_conditions").get(doctype)
		or frappe.get_hooks("has_permission").get(doctype)
	)


_NO_GRANT = object()  # caller has zero operations on this doctype — omit, not an error
_COMPUTE_ERROR = object()  # computing the grant raised — report "unknown", don't abort


def _doctype_columns(meta) -> list[str]:
	"""Real, queryable DB columns for a doctype — `meta.get_valid_columns()`,
	not `frappe.model.default_fields`. The latter includes pseudo-fields like
	`doctype`/`parent`/`parentfield` that are not actual columns on every
	table and would make a published `fields` list unusable for a REST
	`fields=[...]` query on a non-child doctype.
	"""
	return list(meta.get_valid_columns())


def _resource_grant(doctype: str, meta, columns: list[str]):
	"""Return one doctype's grant dict, `_NO_GRANT`, or `_COMPUTE_ERROR`.

	Distinguishing "no permission" from "failed to compute" matters: the
	former is a normal, silent omission from `resources`; the latter must
	surface as `"unknown"` so a caller doesn't mistake a computation failure
	for "not granted." A per-doctype failure must not abort the whole
	manifest either way. Takes an already-fetched `meta`/`columns` so the
	caller's single per-doctype pass (resource grant + schema entry) never
	fetches meta twice or applies mismatched error/timeout handling between
	the two.
	"""
	try:
		ops = {op: bool(frappe.has_permission(doctype, op)) for op in OPERATIONS}
		if not any(ops.values()):
			return _NO_GRANT
		# get_permlevel_access can legitimately return [] for a caller whose
		# access comes from ownership/sharing rather than a permlevel-0 DocPerm
		# row — permlevel 0 is always implicitly readable once `has_permission`
		# is true, so it is never omitted from the allowed set.
		allowed_permlevels = set(get_permlevel_access("read", doctype)) | {0}
		permlevel_by_field = {df.fieldname: df.permlevel for df in meta.fields}
		fields = sorted(col for col in columns if permlevel_by_field.get(col, 0) in allowed_permlevels)
		return {
			"operations": ops,
			"fields": fields,
			"row_scoped": _row_scoped(doctype),
		}
	except Exception:
		frappe.log_error(message=frappe.get_traceback(), title=f"capability_gateway: resource grant failed for {doctype}")
		return _COMPUTE_ERROR


def _capability_grants(roles: list[str]) -> tuple[list[str], list[str]]:
	"""Union `custom_ai_capability_grants` rows across the caller's OWN roles
	only — `roles` is always `frappe.get_roles()`'s own result, never
	caller-supplied, so this is a self-scoped read, not a privilege
	escalation. `ignore_permissions=True` is required because Frappe's child
	table permission check is normally derived from the parent `Role`
	document, which core Frappe restricts to System Manager — the same
	self-scoping guarantee is enforced here instead, in the hard `parent in
	roles` filter.
	"""
	semantic_capabilities: set[str] = set()
	data_scopes: set[str] = set()
	if not roles:
		return [], []
	rows = frappe.get_all(
		"CRM AI Capability Grant",
		filters={
			"parenttype": "Role",
			"parent": ["in", roles],
			"parentfield": "custom_ai_capability_grants",
		},
		fields=["grant_type", "value"],
		ignore_permissions=True,
	)
	for row in rows:
		if row.grant_type == "semantic_capability" and row.value:
			semantic_capabilities.add(row.value)
		elif row.grant_type == "data_scope" and row.value:
			data_scopes.add(row.value)
	return sorted(semantic_capabilities), sorted(data_scopes)


def validate_ai_exposed_change(doc, method=None):
	"""`DocType.validate` hook: only an `AI Capability Admin` may toggle
	`custom_ai_exposed`. Resource exposure is Frappe-owned, deny-by-default —
	this is the sole gate, there is no AI-repo mirror allowlist. Only guards
	the ORM save path — `frappe.db.set_value`/bulk SQL bypass Document hooks
	entirely (a general Frappe behavior, not specific to this hook); there is
	no second, cross-repo backstop if `AI Capability Admin` itself is
	over-granted or this path is bypassed — an accepted trade-off of keeping
	resource exposure a single, Frappe-owned source of truth.
	"""
	if doc.is_new():
		if doc.get("custom_ai_exposed") and "AI Capability Admin" not in frappe.get_roles():
			frappe.throw(
				_("Only an AI Capability Admin may set custom_ai_exposed."), frappe.PermissionError
			)
		return
	before = doc.get_doc_before_save()
	old_value = bool(before.get("custom_ai_exposed")) if before else False
	if bool(doc.get("custom_ai_exposed")) != old_value and "AI Capability Admin" not in frappe.get_roles():
		frappe.throw(
			_("Only an AI Capability Admin may change custom_ai_exposed."), frappe.PermissionError
		)


@frappe.whitelist()
@rate_limit(limit=30, seconds=60, ip_based=True)
def get_capability_manifest():
	"""Return the current session user's Frappe-granted capability manifest:
	roles, per-DocType resource grants (all doctypes with
	`custom_ai_exposed = 1`), semantic-capability/data-scope grants (from
	`Role.custom_ai_capability_grants`), and stable content-hash versions.

	Consumed by crm-agents' FrappeCapabilityGateway — never called with a
	caller-supplied username; always the current session's own grants.
	`ip_based=False` on the rate limit: every crm-agents request shares one
	backend IP, so an IP-keyed limit would throttle all users together
	instead of each caller individually.
	"""
	roles = sorted(frappe.get_roles())
	if not set(roles) & CRM_AI_ALLOWED_ROLES:
		frappe.throw(_("You are not permitted to access CRM resources."), frappe.PermissionError)

	start = time.monotonic()
	# The exposure roster is Frappe-admin-published metadata, not any single
	# user's data — every AI-capable caller is meant to see the same list, so
	# this one read is intentionally not gated by the caller's own DocType
	# permissions (ignore_permissions=True), unlike the per-doctype grants below.
	exposed = sorted(
		frappe.get_all("DocType", filters={"custom_ai_exposed": 1}, pluck="name", ignore_permissions=True)
	)

	# One pass over `exposed` computes both the caller-scoped resource grant
	# and the caller-independent schema entry together, under the same time
	# budget and per-doctype error handling — a meta lookup that's too slow
	# or raises must degrade both consistently, not just one of them (a
	# split loop previously let the schema pass ignore the time budget
	# entirely and crash the whole request on a single bad doctype).
	resources: dict[str, dict] = {}
	version_entries = []
	schema_entries = []
	for doctype in exposed:
		if time.monotonic() - start > _TIME_BUDGET_S:
			resources[doctype] = "unknown"
			continue
		try:
			meta = frappe.get_meta(doctype)
			columns = _doctype_columns(meta)
		except Exception:
			frappe.log_error(
				message=frappe.get_traceback(), title=f"capability_gateway: meta lookup failed for {doctype}"
			)
			resources[doctype] = "unknown"
			continue

		# schema_version hashes the GLOBAL exposed-doctype field-shape
		# catalog — every real column on every exposed doctype, independent
		# of the caller's own permlevel access — so it is comparable across
		# different callers and genuinely reflects "what Frappe is capable
		# of exposing," distinct from capability_version's caller-scoped
		# meaning. Schema metadata is not permission-gated data, so no
		# ignore_permissions is needed for the meta lookup itself.
		schema_entries.append((doctype, sorted(columns)))

		grant = _resource_grant(doctype, meta, columns)
		if grant is _NO_GRANT:
			continue
		if grant is _COMPUTE_ERROR:
			resources[doctype] = "unknown"
			continue
		resources[doctype] = {
			"read": grant["operations"]["read"],
			"write": grant["operations"]["write"],
			"create": grant["operations"]["create"],
			"delete": grant["operations"]["delete"],
			"fields": grant["fields"],
			"row_scoped": grant["row_scoped"],
		}
		version_entries.append(
			(
				doctype,
				sorted(op for op, granted in grant["operations"].items() if granted),
				grant["fields"],
				grant["row_scoped"],
			)
		)

	semantic_capabilities, data_scopes = _capability_grants(roles)

	schema_version = _sha256_hex(sorted(schema_entries))
	capability_version = _sha256_hex(
		{
			"roles": roles,
			"resources": sorted(version_entries),
			"semantic_capabilities": semantic_capabilities,
			"data_scopes": data_scopes,
		}
	)

	return {
		"roles": roles,
		"resources": resources,
		"semantic_capabilities": semantic_capabilities,
		"data_scopes": data_scopes,
		"schema_version": schema_version,
		"capability_version": capability_version,
	}
