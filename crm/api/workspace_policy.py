"""Authoritative, session-derived policy for role workspace readers.

This module deliberately contains no report-builder or generic SQL surface.
Workspace and filter names are an allowlist; identity, capabilities and scope
come from the active Frappe session only.
"""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _

from crm.fcrm.role_policy import (
	POLICY_VERSION,
	capabilities_for_roles,
	classify_role_set,
	resolve_crm_profile,
)

WORKSPACE_POLICY_REVISION = "role-workspace-v1"

# Backend copy of the label-free registry route contract.  The menu ID remains
# the authorization source: a route is allowed only when one of this role's
# menu entries owns that exact workspace/view pair.  A parent menu entry's
# default view is represented explicitly, so omitted route params are stable.
_MENU_ROUTES = {
	"sales": "sales_immediate_contact:sales-urgent:queue sales_my_records:sales-records:new sales_records_new:sales-records:new sales_records_counseling:sales-records:counseling sales_records_awaiting_docs:sales-records:awaiting-documents sales_records_cold:sales-records:cold sales_records_won:sales-records:closed sales_unassigned_pool:sales-pool:available sales_my_tasks:sales-tasks:mine sales_appointments:sales-appointments:calendar sales_my_results:sales-results:overview sales_lookups:admissions-reference:programs sales_lookup_majors:admissions-reference:programs sales_lookup_tuition:admissions-reference:tuition-aid sales_lookup_quota:admissions-reference:quota sales_lookup_high_schools:admissions-reference:schools".split(),
	"lead_sales": "lead_team_dashboard:team-dashboard:overview lead_team_sla:team-sla:running lead_sla_running:team-sla:running lead_sla_near_breach:team-sla:near-breach lead_sla_breached:team-sla:breached lead_sla_violations:team-sla:history lead_team_records:team-records:stage lead_records_by_stage:team-records:stage lead_records_by_agent:team-records:owner lead_records_unassigned:team-records:unowned lead_assignment:team-assignment:queue lead_member_performance:team-performance:members lead_team_tasks:team-tasks:open lead_team_reports:team-reports:overview lead_lookups:admissions-reference:home lead_lookup_majors:admissions-reference:programs lead_lookup_tuition:admissions-reference:tuition-aid lead_lookup_quota:admissions-reference:quota lead_lookup_high_schools:admissions-reference:schools lead_sla_policy_readonly:sla-policy:read".split(),
	"marketing": "mkt_overview:marketing-overview:overview mkt_cpl:marketing-overview:cpl mkt_cpa:marketing-overview:cpa mkt_trends:marketing-overview:weekly-trend mkt_campaigns:campaigns:active mkt_campaigns_running:campaigns:active mkt_campaigns_ended:campaigns:completed mkt_campaigns_draft:campaigns:draft mkt_costs:campaign-spend:mine mkt_events:events:upcoming mkt_events_upcoming:events:upcoming mkt_events_past:events:past mkt_events_registrations:events:registrations mkt_sources_attribution:attribution:sources mkt_funnel:marketing-funnel:overview mkt_segments_consent:consent-segments:eligible mkt_lookups:admissions-reference:home".split(),
	"admissions_director": "mgr_overview:director-overview:overview mgr_progress_quota:director-overview:quota-progress mgr_by_campus:director-overview:campus mgr_by_major:director-overview:program mgr_funnel_forecast:director-forecast:funnel mgr_sla_system:director-sla:team mgr_sla_by_team:director-sla:team mgr_sla_by_campus:director-sla:campus mgr_sla_ranking:director-sla:ranking mgr_all_records:director-records:all mgr_teams_staff:director-people:team-performance mgr_team_perf:director-people:team-performance mgr_workload:director-people:workload mgr_rebalance:director-people:rebalance mgr_marketing_roi:marketing-roi:overview mgr_approvals:approvals:all mgr_appr_spend:approvals:spend mgr_appr_master_data:approvals:master-data mgr_appr_break_glass:approvals:break-glass mgr_quota_tuition:admissions-reference:quota-tuition mgr_business_config:business-policy:sla mgr_cfg_sla:business-policy:sla mgr_cfg_distribution:business-policy:distribution mgr_cfg_scoring:business-policy:scoring mgr_reports:embedded-reports:catalog".split(),
	"system_manager": "adm_users_perms:system-identity:accounts adm_accounts:system-identity:accounts adm_roles:system-identity:roles adm_access_scopes:system-identity:scopes adm_org_structure:system-organization:campuses adm_campus:system-organization:campuses adm_teams:system-organization:teams adm_staff:system-organization:staff adm_integrations:system-integrations:telephony adm_telephony:system-integrations:telephony adm_zalo_oa:system-integrations:zalo adm_email:system-integrations:email adm_webhook:system-integrations:webhooks adm_api_keys:system-api-keys:inventory adm_data_model:system-data-model:catalog adm_system_logs:system-operations:errors adm_logs_errors:system-operations:errors adm_logs_jobs:system-operations:jobs adm_logs_emails:system-operations:email-queue adm_backups:system-backup:status adm_break_glass:system-break-glass:requests adm_access_logs:system-access-audit:events".split(),
}


def _route_map(entries):
	return {menu_id: (workspace, view) for menu_id, workspace, view in (entry.split(":", 2) for entry in entries)}


_ROUTES_BY_ROLE = {profile: _route_map(entries) for profile, entries in _MENU_ROUTES.items()}
_DEFAULT_VIEWS = {
	"sales": {"sales-records": "new", "admissions-reference": "programs"},
	"lead_sales": {"team-sla": "running", "team-records": "stage", "admissions-reference": "home"},
	"marketing": {"campaigns": "active", "events": "upcoming"},
	"admissions_director": {
		"director-sla": "team",
		"director-people": "team-performance",
		"approvals": "all",
		"business-policy": "sla",
	},
	"system_manager": {
		"system-identity": "accounts",
		"system-organization": "campuses",
		"system-integrations": "telephony",
		"system-operations": "errors",
	},
}

# Filter names and values are a closed contract shared by registry presets and
# future providers. Unknown keys/values are rejected; this is not a generic
# report-builder or SQL filter surface.
_FILTER_VALUES = {
	"lifecycle": frozenset({"MQL", "Applicant", "Cold", "Won", "Abandoned"}),
	"ownership": frozenset({"mine", "unassigned"}),
	"urgency": frozenset({"immediate"}),
	"documents": frozenset({"awaiting"}),
	"status": frozenset({"active", "completed", "draft", "upcoming", "past"}),
}


class WorkspacePolicyError(frappe.PermissionError):
	"""One fail-closed error type for an invalid workspace reader request."""


def authorize_director_view(policy, workspace: str, view: str) -> None:
	"""Apply the separately granted entitlement for sensitive Director views."""
	if policy.profile == "admissions_director" and (workspace, view) == ("approvals", "break-glass"):
		if "governance.break_glass.read" not in policy.capabilities:
			raise WorkspacePolicyError(_("Break-glass approvals are not available for your role."))


def derive_workspace_policy() -> frappe._dict:
	"""Build a policy snapshot from the current session, never browser inputs."""
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor or actor == "Guest":
		raise WorkspacePolicyError(_("Authentication is required."))
	roles = frozenset(frappe.get_roles(actor))
	is_administrator = actor == "Administrator"
	state = classify_role_set(roles, administrator=is_administrator)
	if state == "system_manager" or is_administrator:
		profile = "system_manager"
	else:
		profile = resolve_crm_profile(roles)
	if not profile:
		raise WorkspacePolicyError(_("Your role is not authorized for role workspaces."))

	staff = None
	teams: tuple[str, ...] = ()
	campuses: tuple[str, ...] = ()
	if profile != "system_manager":
		staff = frappe.db.get_value("CRM Staff", {"user": actor, "is_active": 1}, ["name", "campus"], as_dict=True)
		if not staff:
			raise WorkspacePolicyError(_("An active CRM Staff record is required."))
		teams = tuple(
			sorted(
				frappe.get_all(
					"CRM Team Membership", filters={"parent": staff.name, "parenttype": "CRM Staff"}, pluck="team"
				)
			)
		)
	# System-manager policies have no CRM Staff row; keep the scope empty
	# instead of dereferencing ``None`` while building the policy snapshot.
	campuses = tuple(sorted({value for value in [staff.get("campus") if staff else None] if value}))
	scope_material = {
		"staff": staff.get("name") if staff else None,
		"teams": teams,
		"campuses": campuses,
	}
	scope_version = hashlib.sha256(
		json.dumps(scope_material, sort_keys=True, separators=(",", ":")).encode()
	).hexdigest()
	return frappe._dict(
		actor=actor,
		profile=profile,
		capabilities=capabilities_for_roles(roles, administrator=is_administrator),
		staff=staff.get("name") if staff else None,
		teams=teams,
		campuses=campuses,
		scope_version=scope_version,
		revision=f"{WORKSPACE_POLICY_REVISION}:{POLICY_VERSION}",
	)


def authorize_workspace(policy: frappe._dict, workspace: str, view: str | None) -> str:
	if not isinstance(workspace, str):
		raise WorkspacePolicyError(_("This workspace is not available for your role."))
	routes = _ROUTES_BY_ROLE.get(policy.profile, {})
	matching_views = {route_view for route_workspace, route_view in routes.values() if route_workspace == workspace}
	if not matching_views:
		raise WorkspacePolicyError(_("This workspace is not available for your role."))
	if view is None or view == "":
		default_view = _DEFAULT_VIEWS.get(policy.profile, {}).get(workspace)
		if default_view:
			return default_view
		if len(matching_views) == 1:
			return next(iter(matching_views))
		raise WorkspacePolicyError(_("This workspace requires an explicit view."))
	if not isinstance(view, str) or view not in matching_views:
		raise WorkspacePolicyError(_("This workspace view is not available."))
	return view


def normalize_filters(workspace: str, filters, *, view: str | None = None, policy=None) -> dict:
	"""Parse only schema-owned filters and produce a stable token payload."""
	if filters in (None, "", {}):
		return {}
	if isinstance(filters, str):
		try:
			filters = json.loads(filters)
		except (TypeError, ValueError) as exc:
			raise WorkspacePolicyError(_("filters must be a JSON object.")) from exc
	if not isinstance(filters, dict):
		raise WorkspacePolicyError(_("filters must be an object."))
	if policy and policy.profile == "admissions_director":
		from crm.api.director_analytics import filter_keys
		allowed = set(filter_keys(workspace, view))
		if set(filters) - allowed:
			raise WorkspacePolicyError(_("One or more filters are not supported."))
		# Campus is a scope ceiling, never a browser-selectable expansion.
		if "campus" in filters and filters["campus"] not in policy.campuses:
			raise WorkspacePolicyError(_("This campus is not available for your role."))
		# Date predicates are deliberately rejected until the provider has a
		# released half-open UTC range implementation; accepting and ignoring one
		# would be a misleading reporting surface.
		if "dateRange" in filters or "period" in filters:
			raise WorkspacePolicyError(_("Date filters are not released for this Director view."))
		for key in {"campus", "program", "team", "slaBucket", "attributionMethod", "approvalState", "sort", "page"} & set(filters):
			if not isinstance(filters[key], str) or not filters[key].strip() or len(filters[key]) > 140:
				raise WorkspacePolicyError(_("A workspace filter is invalid."))
		if "lifecycle" in filters and (not isinstance(filters["lifecycle"], list) or not filters["lifecycle"] or any(item not in _FILTER_VALUES["lifecycle"] | {"Lead", "Enrolled", "Lost"} for item in filters["lifecycle"])):
			raise WorkspacePolicyError(_("A workspace filter is invalid."))
		return {key: filters[key] for key in sorted(filters)}
	if set(filters) - set(_FILTER_VALUES):
		raise WorkspacePolicyError(_("One or more filters are not supported."))
	normalized = {}
	for key in sorted(filters):
		value = filters[key]
		if isinstance(value, list):
			if key != "lifecycle" or not value or any(item not in _FILTER_VALUES[key] for item in value):
				raise WorkspacePolicyError(_("A workspace filter is invalid."))
			normalized[key] = list(dict.fromkeys(value))
		elif isinstance(value, str) and value in _FILTER_VALUES[key]:
			normalized[key] = value
		else:
			raise WorkspacePolicyError(_("A workspace filter is invalid."))
	return normalized


def badge_workspaces(profile: str) -> tuple[str, ...]:
	return {
		"sales": ("sales_immediate_contact", "sales_unassigned_pool", "sales_my_tasks"),
		"lead_sales": ("lead_team_sla", "lead_assignment"),
		"marketing": ("mkt_costs",),
		"admissions_director": ("mgr_approvals",),
	}.get(profile, ())


def route_for_menu_id(profile: str, menu_id: str) -> tuple[str, str]:
	"""Return one role-owned canonical route for sidebar badge landing tokens."""
	try:
		return _ROUTES_BY_ROLE[profile][menu_id]
	except KeyError as exc:
		raise WorkspacePolicyError(_("This menu entry is not available for your role.")) from exc
