import hashlib
import json
import time
from functools import wraps

import frappe
from frappe import _

from crm.api.session import get_session_role_flags, resolve_copilot_profile
from crm.fcrm.doctype.fields_layout.fields_layout import get_permlevel_access
from crm.fcrm.permissions import FULL_VISIBILITY_ROLES

OPERATIONS = ("read", "write", "create", "delete")
CAPABILITY_CONTRACT_VERSION = "v1"
ROLE_MATRIX_EPOCH = "crm-roles-v1"
AI_EXPOSURE_ADMIN_ROLE = "System Manager"

# CRM Student is never broadly PII-exposed.  The manifest is the server-owned
# projection contract consumed by crm-agents: Sales receives only the approved
# contact PII needed for its self-scoped admissions workflow; every other
# Copilot profile receives operational, non-PII fields only.  Identity,
# academic, parent, and address fields are intentionally absent for everyone.
_STUDENT_OPERATIONAL_FIELDS = frozenset(
	{
		"name", "enrollment_status", "lifecycle_stage", "assigned_to", "owner_staff",
		"owning_team", "latest_score", "branch", "source", "admission_year", "created", "modified",
	}
)
_STUDENT_SALES_APPROVED_PII_FIELDS = frozenset({"student_name", "phone", "email"})
_STUDENT_SELF_SCOPE_SALES_ROLES = frozenset({"Sale"})
_STUDENT_NON_SELF_SCOPE_ROLES = frozenset({
	"Lead Sales", "Admissions Director", "Marketing",
}) | frozenset(FULL_VISIBILITY_ROLES)
_STUDENT_STAGING_ENVIRONMENTS = frozenset({"isolated", "staging"})

# The session contract is the sole authority for Copilot eligibility. Do not
# add a broader local allowlist here: that would let an unsupported role obtain
# a capability manifest even though it has no canonical agent profile.

# Timeout budget for the whole call, not per doctype — a stalled meta lookup on
# one exposed doctype must not block the rest from being reported.
_TIME_BUDGET_S = 8.0


def _is_capability_gateway_user(session_flags: dict) -> bool:
	"""Copilot serves canonical operating roles, never System Manager."""
	return bool(session_flags.get("is_crm_user")) and not session_flags.get("is_system_manager", False)


def _session_rate_limit(*, limit: int, seconds: int):
	"""Rate-limit capability endpoints by the authenticated Frappe session.

	The normal Frappe decorator is IP- or form-key based.  Requests routed
	through crm-agents share one backend IP and do not carry a caller-supplied
	form key, so opting it out with ``ip_based=False`` leaves no identity and
	produces a 417 before the endpoint runs.  This local wrapper keeps the
	boundary per session user without trusting request parameters.
	"""
	def decorator(fn):
		@wraps(fn)
		def wrapper(*args, **kwargs):
			if not frappe.request:
				return fn(*args, **kwargs)

			identity = frappe.session.user or "Guest"
			command = frappe.form_dict.get("cmd") or f"{fn.__module__}.{fn.__name__}"
			cache_key = frappe.cache.make_key(f"crm:rl:{command}:{identity}")
			value = frappe.cache.get(cache_key) or 0
			if not value:
				frappe.cache.setex(cache_key, seconds, 0)
			value = frappe.cache.incrby(cache_key, 1)
			if value > limit:
				frappe.throw(
					_("You hit the rate limit because of too many requests. Please try after sometime."),
					frappe.RateLimitExceededError,
				)
			return fn(*args, **kwargs)

		return wrapper
	return decorator


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


def _project_ai_fields(doctype: str, fields: list[str], roles) -> list[str]:
	"""Apply the server-owned CRM Student projection after DocPerm filtering.

	This is intentionally an intersection: a manifest cannot add a field that
	the caller lacks normal Frappe read access to, and a role cannot regain PII
	by requesting it from the agent.  The generic REST API is not an AI data
	surface because CRM Student remains unexposed until the staged DTO endpoint
	and raw delegated REST gate are complete.
	"""
	if doctype != "CRM Student":
		return fields
	allowed = _STUDENT_OPERATIONAL_FIELDS
	# A Copilot persona may aggregate legacy roles with different row scopes.
	# PII must therefore follow the Frappe role's *scope*, not its persona:
	# Marketing, Lead Sales, and Admissions Director never
	# inherit the self-scoped Sales contact exception.
	if _has_self_scoped_student_pii(roles):
		allowed |= _STUDENT_SALES_APPROVED_PII_FIELDS
	return sorted(set(fields) & allowed)


def _has_self_scoped_student_pii(roles) -> bool:
	"""Grant Student PII only when no role can widen the Sales row scope."""
	role_names = frozenset(roles)
	return bool(role_names & _STUDENT_SELF_SCOPE_SALES_ROLES) and not bool(
		role_names & _STUDENT_NON_SELF_SCOPE_ROLES
	)


def _student_ai_exposure_enabled() -> bool:
	"""Explicit two-key staging gate; production remains dark by default."""
	return (
		frappe.conf.get("ai_student_exposure_environment") in _STUDENT_STAGING_ENVIRONMENTS
		and bool(frappe.db.get_value("DocType", "CRM Student", "custom_ai_exposed"))
	)


def _require_student_ai_exposure() -> None:
	if not _student_ai_exposure_enabled():
		frappe.throw(_("CRM Student AI exposure is not enabled in this environment."), frappe.PermissionError)


def _student_projection_for_current_user() -> list[str]:
	roles = frappe.get_roles()
	if resolve_copilot_profile(roles) is None:
		frappe.throw(_("You are not permitted to access CRM Student data."), frappe.PermissionError)
	meta = frappe.get_meta("CRM Student")
	allowed_permlevels = set(get_permlevel_access("read", "CRM Student")) | {0}
	permlevel_by_field = {df.fieldname: df.permlevel for df in meta.fields}
	readable_columns = [
		fieldname for fieldname in _doctype_columns(meta)
		if permlevel_by_field.get(fieldname, 0) in allowed_permlevels
	]
	return _project_ai_fields("CRM Student", readable_columns, roles)


def _safe_student_filters(raw_filters, allowed_fields: set[str]):
	"""Accept only equality / membership filters over the projected DTO.

	This prevents the dedicated AI endpoint from becoming a general query API
	that can predicate on identity or academic fields which it never returns.
	"""
	if raw_filters in (None, "", []):
		return []
	filters = frappe.parse_json(raw_filters) if isinstance(raw_filters, str) else raw_filters
	if not isinstance(filters, list):
		frappe.throw(_("Student filters must be a list."), frappe.ValidationError)
	validated = []
	for item in filters:
		if not isinstance(item, (list, tuple)) or len(item) != 3:
			frappe.throw(_("Student filter is invalid."), frappe.ValidationError)
		fieldname, operator, value = item
		if fieldname not in allowed_fields or operator not in {"=", "in"}:
			frappe.throw(_("Student filter is not permitted."), frappe.PermissionError)
		if operator == "in" and (not isinstance(value, list) or len(value) > 50):
			frappe.throw(_("Student filter is invalid."), frappe.ValidationError)
		validated.append([fieldname, operator, value])
	return validated


@frappe.whitelist()
@_session_rate_limit(limit=60, seconds=60)
def get_ai_student(name: str):
	"""Return one row-scoped, role-projected CRM Student DTO for Copilot."""
	_require_student_ai_exposure()
	get_session_role_flags()
	fields = _student_projection_for_current_user()
	doc = frappe.get_doc("CRM Student", name)
	# Pass the loaded document—not merely its name—to Frappe's global resolver,
	# so the registered Student ``has_permission`` hook evaluates row scope.
	if not frappe.has_permission("CRM Student", ptype="read", doc=doc):
		frappe.throw(_("You are not permitted to access this CRM Student."), frappe.PermissionError)
	return {fieldname: doc.get(fieldname) for fieldname in fields}


@frappe.whitelist()
@_session_rate_limit(limit=60, seconds=60)
def list_ai_students(filters=None, limit=20, offset=0):
	"""Return only row-scoped, role-projected CRM Student DTOs for Copilot."""
	_require_student_ai_exposure()
	get_session_role_flags()
	fields = _student_projection_for_current_user()
	try:
		limit, offset = int(limit), int(offset)
	except (TypeError, ValueError):
		frappe.throw(_("Student pagination is invalid."), frappe.ValidationError)
	if not 1 <= limit <= 50 or offset < 0:
		frappe.throw(_("Student pagination is invalid."), frappe.ValidationError)
	return {
		"records": frappe.get_list(
			"CRM Student",
			fields=fields,
			filters=_safe_student_filters(filters, set(fields)),
			start=offset,
			page_length=limit,
			order_by="modified desc, name asc",
		),
	}


@frappe.whitelist()
@_session_rate_limit(limit=60, seconds=60)
def search_ai_students(query: str, filters=None, limit=20):
	"""Search projected Student contact fields in the caller's row scope.

	Only Sales has approved contact PII, therefore only Sales may perform this
	text search. Other personas retain aggregate/list workflows without gaining
	an identity-discovery surface.
	"""
	_require_student_ai_exposure()
	roles = frappe.get_roles()
	get_session_role_flags()
	if not _has_self_scoped_student_pii(roles):
		frappe.throw(_("Student search is not permitted."), frappe.PermissionError)
	query = (query or "").strip()
	if not query or len(query) > 100:
		frappe.throw(_("Student search query is invalid."), frappe.ValidationError)
	fields = _student_projection_for_current_user()
	try:
		limit = int(limit)
	except (TypeError, ValueError):
		frappe.throw(_("Student pagination is invalid."), frappe.ValidationError)
	if not 1 <= limit <= 50:
		frappe.throw(_("Student pagination is invalid."), frappe.ValidationError)
	return {
		"records": frappe.get_list(
			"CRM Student",
			fields=fields,
			filters=_safe_student_filters(filters, set(fields)),
			or_filters=[[fieldname, "like", f"%{query}%"] for fieldname in ("student_name", "phone", "email")],
			page_length=limit,
			order_by="modified desc, name asc",
		),
	}


@frappe.whitelist()
@_session_rate_limit(limit=60, seconds=60)
def count_ai_students(filters=None):
	"""Count only rows visible through the current user's Student scope."""
	_require_student_ai_exposure()
	get_session_role_flags()
	fields = _student_projection_for_current_user()
	rows = frappe.get_list(
		"CRM Student",
		fields=["count(name) as count"],
		filters=_safe_student_filters(filters, set(fields)),
		page_length=1,
	)
	return {"count": int(rows[0].get("count", 0)) if rows else 0}


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
		fields = _project_ai_fields(doctype, fields, frappe.get_roles())
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


def _can_manage_ai_exposure(roles) -> bool:
	"""Return whether server-derived roles include the sole exposure authority.

	`Administrator` and legacy `System Manager` do not imply this grant;
	their continued presence during migration cannot retain an authorization path.
	"""
	return AI_EXPOSURE_ADMIN_ROLE in frozenset(roles)


def _require_ai_exposure_administrator() -> None:
	"""Role check without Frappe's Administrator-only bypass in ``only_for``."""
	if not _can_manage_ai_exposure(frappe.get_roles(frappe.session.user)):
		frappe.throw(_("Only a System Manager may manage AI exposure."), frappe.PermissionError)


def validate_ai_exposed_change(doc, method=None):
	"""`DocType.validate` hook: only a `System Manager` may toggle
	`custom_ai_exposed`. Resource exposure is Frappe-owned, deny-by-default —
	this is the sole gate, there is no AI-repo mirror allowlist. Only guards
	the ORM save path — `frappe.db.set_value`/bulk SQL bypass Document hooks
	entirely (a general Frappe behavior, not specific to this hook); there is
	no second, cross-repo backstop if `System Manager` itself is
	over-granted or this path is bypassed — an accepted trade-off of keeping
	resource exposure a single, Frappe-owned source of truth.
	"""
	can_manage = _can_manage_ai_exposure(frappe.get_roles())
	if doc.is_new():
		if doc.get("custom_ai_exposed") and not can_manage:
			frappe.throw(
				_("Only a System Manager may set custom_ai_exposed."), frappe.PermissionError
			)
		return
	before = doc.get_doc_before_save()
	old_value = bool(before.get("custom_ai_exposed")) if before else False
	if bool(doc.get("custom_ai_exposed")) != old_value and not can_manage:
		frappe.throw(
			_("Only a System Manager may change custom_ai_exposed."), frappe.PermissionError
		)


@frappe.whitelist()
@_session_rate_limit(limit=30, seconds=60)
def get_current_roles():
	"""Return only the authenticated user's server-derived roles to crm-agents."""
	if frappe.session.user in ("", "Guest"):
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if not _is_capability_gateway_user(get_session_role_flags()):
		frappe.throw(_("You are not permitted to access CRM resources."), frappe.PermissionError)
	return {"roles": sorted(frappe.get_roles(frappe.session.user))}


@frappe.whitelist()
@_session_rate_limit(limit=30, seconds=60)
def get_capability_manifest():
	"""Return the current session user's Frappe-granted capability manifest:
	roles, per-DocType resource grants (all doctypes with
	`custom_ai_exposed = 1`), semantic-capability/data-scope grants (from
	`Role.custom_ai_capability_grants`), and stable content-hash versions.

	Consumed by crm-agents' FrappeCapabilityGateway — never called with a
	caller-supplied username; always the current session's own grants.
	The rate limit is keyed by the authenticated Frappe session: every
	crm-agents request shares one backend IP, so an IP-keyed limit would
	throttle all users together instead of each caller individually.
	"""
	get_session_role_flags()
	roles = sorted(frappe.get_roles())
	if resolve_copilot_profile(roles) is None:
		frappe.throw(_("You are not permitted to access CRM resources."), frappe.PermissionError)

	start = time.monotonic()
	# The exposure roster is Frappe-admin-published metadata, not any single
	# user's data — every AI-capable caller is meant to see the same list, so
	# this one read is intentionally not gated by the caller's own DocType
	# permissions (ignore_permissions=True), unlike the per-doctype grants below.
	exposed = sorted(
		frappe.get_all("DocType", filters={"custom_ai_exposed": 1}, pluck="name", ignore_permissions=True)
	)
	# Student is additive and staging-only: even an accidental metadata toggle
	# cannot publish it into a production capability manifest.
	exposed = [
		doctype for doctype in exposed
		if doctype != "CRM Student" or _student_ai_exposure_enabled()
	]

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
		"contract_version": CAPABILITY_CONTRACT_VERSION,
		"roles": roles,
		"crm_role": resolve_copilot_profile(roles),
		"role_profile": resolve_copilot_profile(roles),
		"role_matrix_epoch": ROLE_MATRIX_EPOCH,
		"resources": resources,
		"semantic_capabilities": semantic_capabilities,
		"data_scopes": data_scopes,
		"schema_version": schema_version,
		"capability_version": capability_version,
	}


@frappe.whitelist()
def get_exposed_doctypes():
	"""Return the server-published AI schema roster for the crm-agents service.

	DocType custom fields are intentionally not usable as REST resource filters,
	so schema bootstrap must use this narrow server-side read instead.
	"""
	_require_ai_exposure_administrator()
	doctypes = frappe.get_all(
		"DocType", filters={"custom_ai_exposed": 1}, pluck="name", ignore_permissions=True
	)
	return {
		"doctypes": sorted(
			doctype for doctype in doctypes
			if doctype != "CRM Student" or _student_ai_exposure_enabled()
		)
	}
