"""One-way backfill to the four canonical CRM business roles.

The mapping below is migration input only.  It is never imported by request
handlers: after this patch has run, Frappe runtime authorization sees only the
four canonical business roles plus the System Manager control-plane role.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import frappe

from crm.patches.v1_0.setup_crm_roles import create_roles

CANONICAL_BUSINESS_ROLES = frozenset({"Sale", "Lead Sale", "Marketing", "Promoter", "Admissions Director"})
CONTROL_ROLES = frozenset({"System Manager"})
CANONICAL_ROLES = CANONICAL_BUSINESS_ROLES | CONTROL_ROLES

# Keep the rollback snapshot narrow and lossless. These are the complete
# scalar fields that affect role identity/authorization in the deployed
# Frappe version; unrelated built-in roles are intentionally out of scope.
ROLE_FIELDS = [
	"name",
	"role_name",
	"home_page",
	"restrict_to_domain",
	"disabled",
	"is_custom",
	"desk_access",
	"two_factor_auth",
]
PERMISSION_FIELDS = [
	"name",
	"parent",
	"parenttype",
	"parentfield",
	"idx",
	"role",
	"permlevel",
	"read",
	"write",
	"create",
	"submit",
	"cancel",
	"delete",
	"amend",
	"report",
	"export",
	"import",
	"share",
	"print",
	"email",
	"if_owner",
	"select",
]
CUSTOM_PERMISSION_FIELDS = [
	"name",
	"parent",
	"idx",
	"role",
	"permlevel",
	"read",
	"write",
	"create",
	"submit",
	"cancel",
	"delete",
	"amend",
	"report",
	"export",
	"import",
	"share",
	"print",
	"email",
	"if_owner",
	"select",
]
USER_PERMISSION_FIELDS = [
	"name",
	"user",
	"allow",
	"for_value",
	"is_default",
	"apply_to_all_doctypes",
	"applicable_for",
	"hide_descendants",
]
INVITATION_FIELDS = [
	"name",
	"email",
	"role",
	"key",
	"invited_by",
	"status",
	"email_sent_at",
	"accepted_at",
]

# Frappe stores role references outside Has Role/DocPerm as well.  These are
# authorization/configuration tables; business fields such as CRM Person.role
# are deliberately excluded because they are domain data, not auth grants.
ROLE_REFERENCE_SPECS = (
	("OAuth Client Role", "role"),
	("Onboarding Permission", "role"),
	("Portal Menu Item", "role"),
	("Review Level", "role"),
	("ToDo", "role"),
	("User Role", "role"),
	("User Type", "role"),
	("Workflow Action Permitted Role", "role"),
	("Workflow Document State", "allowed"),
	("Workflow Transition", "allowed"),
	("Role Permission for Page and Report", "role"),
)


def _has_role_reference_table(table: str, field: str) -> bool:
	"""Return true only when both the doctype table and role-bearing column exist."""
	return frappe.db.table_exists(table) and frappe.db.has_column(table, field)


# Historical input for this patch only. Do not reuse this table at runtime.
BACKFILL_ROLE_MAP = {
	"CTV-Sale": "Sale",
	"Counseller": "Sale",
	"Sales User": "Sale",
	"Sales Manager": "Lead Sale",
	"Team Leader": "Lead Sale",
	"Promoter-PR": "Marketing",
	"Marketing Operator": "Marketing",
	"Marketing Lead": "Marketing",
	"CRM Data Steward": "Marketing",
	"Admissions Operations": "Admissions Director",
	"Giám đốc Tuyển sinh": "Admissions Director",
	"AI Capability Admin": "System Manager",
}

ROLE_SCOPE = frozenset(CANONICAL_ROLES | set(BACKFILL_ROLE_MAP))


def _snapshot_path() -> Path:
	# v4 is a new immutable artifact; earlier snapshots are intentionally never
	# overwritten because they did not contain the complete role-reference
	# inventory required for a safe rollback.
	return Path(frappe.get_site_path("private", "backups", "canonical-crm-roles-v4.json"))


def _checksum(payload: dict) -> str:
	return hashlib.sha256(
		json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
	).hexdigest()


def _snapshot(*, capture_mode: str = "pre_cutover") -> dict:
	role_names = sorted(ROLE_SCOPE)
	role_assignments = frappe.get_all(
		"Has Role",
		filters={"role": ["in", role_names], "parenttype": ["in", ["User", "Role Profile"]]},
		fields=["name", "parent", "parenttype", "parentfield", "role"],
		order_by="parenttype, parent, role",
	)
	affected_users = sorted({row.parent for row in role_assignments if row.parenttype == "User"})
	assignments = [row for row in role_assignments if row.parenttype == "User"]
	role_profile_assignments = [row for row in role_assignments if row.parenttype == "Role Profile"]
	docperm_filters = {"role": ["in", role_names]}
	docperms = frappe.get_all("DocPerm", filters=docperm_filters, fields=PERMISSION_FIELDS)
	custom_docperms = [
		{
			**dict(row),
			# Custom DocPerm stores `parent` but not the standard child-row
			# parenttype/parentfield columns. Persist the logical relation in the
			# snapshot so restore remains explicit and version-stable.
			"parenttype": "Customize Form",
			"parentfield": "permissions",
		}
		for row in frappe.get_all("Custom DocPerm", filters=docperm_filters, fields=CUSTOM_PERMISSION_FIELDS)
	]
	grants = frappe.get_all(
		"CRM AI Capability Grant",
		filters={"parent": ["in", role_names], "parenttype": "Role"},
		fields=["name", "parent", "parenttype", "parentfield", "idx", "grant_type", "value"],
	)
	user_filters = {"user": ["in", sorted(set(affected_users))]} if affected_users else {"user": "__none__"}
	user_permissions = frappe.get_all("User Permission", filters=user_filters, fields=USER_PERMISSION_FIELDS)
	invitations = frappe.get_all("Invitation", filters={"role": ["in", role_names]}, fields=INVITATION_FIELDS)
	role_references = []
	for table, field in ROLE_REFERENCE_SPECS:
		if _has_role_reference_table(table, field):
			role_references.append(
				{
					"table": table,
					"field": field,
					"rows": [
						dict(row)
						for row in frappe.get_all(table, filters={field: ["in", role_names]}, fields=["*"])
					],
				}
			)
	manifest_hashes = {
		role: hashlib.sha256(
			json.dumps(
				{
					"docperms": [dict(row) for row in docperms if row.role == role],
					"grants": [dict(row) for row in grants if row.parent == role],
				},
				sort_keys=True,
				separators=(",", ":"),
				default=str,
			).encode()
		).hexdigest()
		for role in role_names
	}
	return {
		"version": 4,
		"capture_mode": capture_mode,
		"scope_roles": role_names,
		"affected_users": sorted(set(affected_users)),
		"roles": frappe.get_all("Role", filters={"name": ["in", role_names]}, fields=ROLE_FIELDS),
		"assignments": assignments,
		"role_profile_assignments": role_profile_assignments,
		"docperms": docperms,
		"custom_docperms": custom_docperms,
		"capability_grants": grants,
		"user_permissions": user_permissions,
		"invitations": invitations,
		"role_references": role_references,
		# There is no runtime role-alias table. Preserve the migration-only
		# source/target inventory as auditable data, never as an auth input.
		"aliases": [
			{"source_role": source, "canonical_role": target}
			for source, target in sorted(BACKFILL_ROLE_MAP.items())
		],
		"manifest_hashes": manifest_hashes,
	}


def _write_snapshot_once(*, capture_mode: str = "pre_cutover") -> None:
	path = _snapshot_path()
	if path.exists():
		try:
			existing = json.loads(path.read_text(encoding="utf-8"))
			expected = existing.get("checksum") if isinstance(existing, dict) else None
			if (
				not isinstance(existing, dict)
				or existing.get("version") != 4
				or not isinstance(existing.get("role_references"), list)
				or not isinstance(existing.get("capture_mode"), str)
			):
				raise frappe.ValidationError("canonical CRM role snapshot schema is incomplete")
			payload = {key: value for key, value in existing.items() if key != "checksum"}
			if not expected or expected != _checksum(payload):
				raise frappe.ValidationError("canonical CRM role snapshot checksum is invalid")
		except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
			raise frappe.ValidationError("canonical CRM role snapshot cannot be trusted") from exc
		return
	payload = _snapshot(capture_mode=capture_mode)
	payload["checksum"] = _checksum(payload)
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def restore_from_snapshot(snapshot: dict) -> None:
	"""Restore role records, assignments, permissions, and AI grants.

	This is an explicit rollback drill primitive; it never runs automatically
	from request code and does not accept an unchecksummed payload.
	"""
	if not isinstance(snapshot, dict) or snapshot.get("checksum") != _checksum(
		{key: value for key, value in snapshot.items() if key != "checksum"}
	):
		raise ValueError("invalid canonical-role migration snapshot checksum")
	if snapshot.get("version") != 4:
		raise ValueError(
			"unsupported canonical-role migration snapshot version; legacy snapshots cannot be used for rollback"
		)
	assignments = snapshot.get("assignments")
	if not isinstance(assignments, list):
		raise ValueError("migration snapshot has no assignments")
	role_profile_assignments = snapshot.get("role_profile_assignments", [])
	if not isinstance(role_profile_assignments, list):
		raise ValueError("migration snapshot has invalid role profile assignments")
	for section in (
		"scope_roles",
		"affected_users",
		"roles",
		"docperms",
		"custom_docperms",
		"capability_grants",
		"user_permissions",
		"invitations",
		"aliases",
		"manifest_hashes",
	):
		if not isinstance(snapshot.get(section), list):
			if section == "manifest_hashes":
				if not isinstance(snapshot.get(section), dict):
					raise ValueError(f"migration snapshot has no {section}")
			else:
				raise ValueError(f"migration snapshot has no {section}")
	if "role_references" not in snapshot or not isinstance(snapshot["role_references"], list):
		raise ValueError("migration snapshot has no complete role-reference inventory")
	role_references = snapshot["role_references"]
	scope_roles = set(snapshot["scope_roles"])
	if not scope_roles or not scope_roles <= set(ROLE_SCOPE):
		raise ValueError("migration snapshot role scope is invalid")
	if set(snapshot["manifest_hashes"]) != scope_roles:
		raise ValueError("migration snapshot manifest hash scope is invalid")

	def _role_names() -> set[str]:
		names = {
			row.get("name") for row in snapshot.get("roles", []) if isinstance(row, dict) and row.get("name")
		}
		names.update(
			row.get("role")
			for section in (
				assignments,
				role_profile_assignments,
				snapshot["docperms"],
				snapshot["custom_docperms"],
			)
			for row in section
			if isinstance(row, dict) and row.get("role")
		)
		names.update(
			row.get("parent")
			for row in snapshot["capability_grants"]
			if isinstance(row, dict) and row.get("parent") and row.get("parenttype") == "Role"
		)
		return names

	# Recreate role records before restoring child rows, preserving metadata.
	role_rows = {
		(row.get("role_name") or row.get("name")): row
		for row in snapshot["roles"]
		if isinstance(row, dict) and (row.get("role_name") or row.get("name"))
	}
	for role in sorted(scope_roles - set(role_rows)):
		# A role created after the snapshot must not survive rollback. Remove
		# only its scoped references first so Role deletion remains deterministic.
		if frappe.db.exists("Role", role):
			frappe.db.delete("Has Role", {"role": role})
			frappe.db.delete("DocPerm", {"role": role})
			frappe.db.delete("Custom DocPerm", {"role": role})
			frappe.db.delete("CRM AI Capability Grant", {"parent": role})
			frappe.db.delete("Invitation", {"role": role})
			frappe.delete_doc("Role", role, ignore_permissions=True, force=True)
	for role in sorted(_role_names() & scope_roles):
		row = role_rows.get(role, {"role_name": role, "desk_access": 1})
		payload = {"doctype": "Role", **row, "role_name": role}
		if not frappe.db.exists("Role", role):
			frappe.get_doc(payload).insert(ignore_permissions=True)
		else:
			for field in ROLE_FIELDS:
				if field not in {"name", "role_name"} and field in row:
					frappe.db.set_value("Role", role, field, row[field], update_modified=False)

	for row in assignments:
		if not isinstance(row, dict) or not row.get("parent") or not row.get("role"):
			continue
		frappe.db.delete(
			"Has Role",
			{"name": row["name"]} if row.get("name") else {"parent": row["parent"], "role": row["role"]},
		)
	for row in assignments:
		if not isinstance(row, dict) or not row.get("parent") or not row.get("role"):
			continue
		frappe.get_doc(
			{
				"doctype": "Has Role",
				"parent": row["parent"],
				"parenttype": "User",
				"parentfield": row.get("parentfield") or "roles",
				"role": row["role"],
			}
		).insert(ignore_permissions=True)
	for row in role_profile_assignments:
		if not isinstance(row, dict) or not row.get("parent") or not row.get("role"):
			continue
		frappe.get_doc(
			{
				"doctype": "Has Role",
				"parent": row["parent"],
				"parenttype": "Role Profile",
				"parentfield": row.get("parentfield") or "roles",
				"role": row["role"],
			}
		).insert(ignore_permissions=True)

	def _restore_child_rows(
		doctype: str,
		rows: list[dict],
		role_field: str,
		defaults: dict,
		*,
		drop_fields: frozenset[str] = frozenset(),
	) -> None:
		# Only rows represented by the snapshot are part of this rollback.  Rows
		# added after the snapshot are not authorization data created by this cutover.
		for row in rows:
			if isinstance(row, dict) and row.get("name"):
				frappe.db.delete(doctype, {"name": row["name"]})
		for row in rows:
			if not isinstance(row, dict) or not row.get("parent") or not row.get(role_field):
				continue
			payload = {"doctype": doctype, **defaults, **row}
			for field in drop_fields:
				payload.pop(field, None)
			frappe.get_doc(payload).insert(ignore_permissions=True)

	_restore_child_rows(
		"DocPerm",
		snapshot["docperms"],
		"role",
		{"parenttype": "DocType", "parentfield": "permissions"},
	)
	_restore_child_rows(
		"Custom DocPerm",
		snapshot["custom_docperms"],
		"role",
		{},
		drop_fields=frozenset({"parenttype", "parentfield"}),
	)
	# CRM AI Capability Grant is itself a Role child table.
	grant_rows = [row for row in snapshot["capability_grants"] if isinstance(row, dict)]
	for row in grant_rows:
		if row.get("name"):
			frappe.db.delete("CRM AI Capability Grant", {"name": row["name"]})
	for row in grant_rows:
		if not row.get("parent") or not row.get("grant_type") or not row.get("value"):
			continue
		frappe.get_doc(
			{
				"doctype": "CRM AI Capability Grant",
				"parent": row["parent"],
				"parenttype": row.get("parenttype") or "Role",
				"parentfield": row.get("parentfield") or "ai_capability_grants",
				"grant_type": row["grant_type"],
				"value": row["value"],
			}
		).insert(ignore_permissions=True)

	# The cutover does not mutate User Permission rows.  Restore missing
	# snapshot grants without deleting unrelated grants added afterwards.
	for row in snapshot["user_permissions"]:
		if row.get("user") and row.get("allow") and row.get("for_value"):
			if not frappe.db.exists(
				"User Permission",
				{"user": row["user"], "allow": row["allow"], "for_value": row["for_value"]},
			):
				frappe.get_doc({"doctype": "User Permission", **row}).insert(ignore_permissions=True)
	for row in snapshot["invitations"]:
		if row.get("name"):
			frappe.db.delete("Invitation", {"name": row["name"]})
	for row in snapshot["invitations"]:
		if row.get("email") and row.get("role"):
			frappe.get_doc({"doctype": "Invitation", **row}).insert(ignore_permissions=True)
	# Restore the additional role-bearing tables captured by the snapshot.  Only
	# exact snapshot names are replaced; rows created after the cutover remain
	# untouched.
	for reference in role_references:
		if (
			not isinstance(reference, dict)
			or not reference.get("table")
			or not isinstance(reference.get("rows"), list)
		):
			continue
		table = reference["table"]
		field = reference.get("field")
		if not isinstance(field, str) or not _has_role_reference_table(table, field):
			continue
		rows = reference["rows"]
		for row in rows:
			if isinstance(row, dict) and row.get("name"):
				frappe.db.delete(table, {"name": row["name"]})
		for row in rows:
			if isinstance(row, dict):
				frappe.get_doc({"doctype": table, **row}).insert(ignore_permissions=True)
	frappe.db.commit()
	frappe.clear_cache()


def _canonical_targets(role_names: set[str]) -> set[str]:
	"""Return safe canonical targets; manager wins over a legacy sales pair."""
	targets = {
		BACKFILL_ROLE_MAP.get(role, role)
		for role in role_names
		if role in CANONICAL_ROLES or role in BACKFILL_ROLE_MAP
	}
	if "Lead Sale" in targets:
		targets.discard("Sale")
	return targets


def _backfill_user_roles() -> list[dict]:
	quarantine = []
	for user in frappe.get_all("User", pluck="name"):
		roles = set(frappe.get_all("Has Role", filters={"parent": user}, pluck="role"))
		targets = _canonical_targets(roles)
		business_targets = targets & CANONICAL_BUSINESS_ROLES
		if len(business_targets) > 1:
			quarantine.append({"user": user, "targets": sorted(business_targets)})
			continue
		for old_role in roles & set(BACKFILL_ROLE_MAP):
			frappe.db.delete("Has Role", {"parent": user, "role": old_role})
		for role in targets:
			if role not in roles:
				frappe.get_doc(
					{
						"doctype": "Has Role",
						"parent": user,
						"parenttype": "User",
						"parentfield": "roles",
						"role": role,
					}
				).insert(ignore_permissions=True)
	return quarantine


def _replace_role_references() -> None:
	"""Move persisted permission/grant references before legacy Role deletion."""
	# Has Role is also used by Role Profile.  Migrate every persisted reference,
	# not only direct User children, before removing the legacy Role records.
	if frappe.db.table_exists("Has Role"):
		rows = frappe.get_all(
			"Has Role",
			filters={"role": ["in", sorted(set(BACKFILL_ROLE_MAP))]},
			fields=["name", "parent", "parenttype", "parentfield", "role"],
		)
		seen = {
			(row.parent, row.parenttype, row.parentfield, row.role)
			for row in frappe.get_all(
				"Has Role",
				filters={"role": ["in", sorted(CANONICAL_ROLES)]},
				fields=["parent", "parenttype", "parentfield", "role"],
			)
		}
		for row in rows:
			new_role = BACKFILL_ROLE_MAP[row.role]
			key = (row.parent, row.parenttype, row.parentfield, new_role)
			if key in seen:
				frappe.db.delete("Has Role", {"name": row.name})
			else:
				frappe.db.set_value("Has Role", row.name, "role", new_role, update_modified=False)
				seen.add(key)

	for table, field in (
		("DocPerm", "role"),
		("Custom DocPerm", "role"),
		("CRM AI Capability Grant", "parent"),
	):
		if not _has_role_reference_table(table, field):
			continue
		for old_role, new_role in BACKFILL_ROLE_MAP.items():
			if table == "CRM AI Capability Grant":
				rows = frappe.get_all(
					table,
					filters={"parent": old_role, "parenttype": "Role"},
					fields=["name", "grant_type", "value"],
				)
				existing = {
					(row.grant_type, row.value)
					for row in frappe.get_all(
						table,
						filters={"parent": new_role, "parenttype": "Role"},
						fields=["grant_type", "value"],
					)
				}
				for row in rows:
					key = (row.grant_type, row.value)
					if key in existing:
						frappe.db.delete(table, {"name": row.name})
					else:
						frappe.db.set_value(table, row.name, "parent", new_role, update_modified=False)
						existing.add(key)
			elif table in {"DocPerm", "Custom DocPerm"}:
				# Preserve old-role production overrides.  If the canonical role
				# already has the same doctype/permlevel row, merge flags instead of
				# deleting either grant; otherwise move the row in place.
				old_rows = frappe.get_all(table, filters={field: old_role}, fields=["*"])
				target_rows = frappe.get_all(table, filters={field: new_role}, fields=["*"])
				for row in old_rows:
					match = next(
						(
							candidate
							for candidate in target_rows
							if candidate.parent == row.parent
							and int(candidate.permlevel or 0) == int(row.permlevel or 0)
						),
						None,
					)
					if match is None:
						frappe.db.set_value(table, row.name, field, new_role, update_modified=False)
						target_rows.append(row)
						continue
					updates = {
						flag: 1
						for flag in PERMISSION_FIELDS
						if flag
						not in {"name", "parent", "parenttype", "parentfield", "idx", "role", "permlevel"}
						and (getattr(match, flag, 0) or getattr(row, flag, 0))
					}
					if updates:
						frappe.db.set_value(table, match.name, updates, update_modified=False)
					frappe.db.delete(table, {"name": row.name})
	# Other Frappe authorization tables carry a direct role/allowed field.  Move
	# those references before deleting the legacy Role records; child-table
	# duplicates are collapsed when the same parent already has the target role.
	for table, field in ROLE_REFERENCE_SPECS:
		if not _has_role_reference_table(table, field):
			continue
		for old_role, new_role in BACKFILL_ROLE_MAP.items():
			old_rows = frappe.get_all(table, filters={field: old_role}, fields=["*"])
			if not old_rows:
				continue
			target_rows = frappe.get_all(table, filters={field: new_role}, fields=["*"])
			for row in old_rows:
				# Child-table rows are naturally keyed by parent/parentfield.  For
				# standalone records, retaining the row and changing its role is the
				# lossless operation; duplicate cleanup is not safe without a doctype
				# specific unique key.
				parent = getattr(row, "parent", None)
				if parent:
					duplicate = next(
						(
							candidate
							for candidate in target_rows
							if getattr(candidate, "parent", None) == parent
							and getattr(candidate, "parenttype", None) == getattr(row, "parenttype", None)
							and getattr(candidate, "parentfield", None) == getattr(row, "parentfield", None)
						),
						None,
					)
					if duplicate is not None:
						frappe.db.delete(table, {"name": row.name})
						continue
				frappe.db.set_value(table, row.name, field, new_role, update_modified=False)
				target_rows.append(row)
	if frappe.db.table_exists("Invitation"):
		for old_role, new_role in BACKFILL_ROLE_MAP.items():
			frappe.db.set_value("Invitation", {"role": old_role}, "role", new_role, update_modified=False)


def _delete_legacy_roles() -> None:
	for role in BACKFILL_ROLE_MAP:
		if frappe.db.exists("Role", role):
			frappe.delete_doc("Role", role, ignore_permissions=True, force=True)


def _assert_no_legacy_references() -> None:
	"""Fail before commit if any persisted authorization reference survived."""
	legacy_roles = sorted(BACKFILL_ROLE_MAP)
	if frappe.db.exists("Role", {"name": ["in", legacy_roles]}):
		raise frappe.ValidationError("canonical CRM role cutover left legacy Role records")
	for table, field in (
		("Has Role", "role"),
		("DocPerm", "role"),
		("Custom DocPerm", "role"),
		("CRM AI Capability Grant", "parent"),
		("Invitation", "role"),
	):
		if _has_role_reference_table(table, field) and frappe.db.exists(table, {field: ["in", legacy_roles]}):
			raise frappe.ValidationError(f"canonical CRM role cutover left legacy references in {table}")
	for table, field in ROLE_REFERENCE_SPECS:
		if _has_role_reference_table(table, field) and frappe.db.exists(table, {field: ["in", legacy_roles]}):
			raise frappe.ValidationError(
				f"canonical CRM role cutover left legacy references in {table}.{field}"
			)


def _require_maintenance_window() -> None:
	"""Require an explicit quiesce flag before the destructive cutover."""
	if not frappe.conf.get("crm_role_migration_maintenance"):
		raise frappe.ValidationError(
			"Set site_config crm_role_migration_maintenance=1 after draining CRM workers before canonical role cutover"
		)


def execute():
	"""Snapshot, backfill, quarantine ambiguities, then remove old CRM roles."""
	_require_maintenance_window()
	_write_snapshot_once()
	try:
		create_roles(sorted(CANONICAL_ROLES | {"Administrator"}))
		quarantine = _backfill_user_roles()
		if quarantine:
			frappe.log_error(
				json.dumps(quarantine, ensure_ascii=False), "canonical CRM role migration quarantine"
			)
			raise frappe.ValidationError("canonical CRM role migration has mixed-role users; see Error Log")
		_replace_role_references()
		# `setup_crm_permissions` is an earlier patch in patches.txt and has
		# already published the canonical baseline.  Do not rewrite source JSON
		# during this transactional cutover: `_replace_role_references` has
		# merged legacy production DocPerm overrides directly in the DB, and a
		# later reload would otherwise discard that merge or leave the filesystem
		# half-published if a subsequent step failed.
		_delete_legacy_roles()
		_assert_no_legacy_references()
		frappe.db.commit()
		frappe.clear_cache()
	except Exception:
		frappe.db.rollback()
		raise


def execute_for_fresh_site() -> None:
	"""Install the canonical role contract while a new site is quiesced.

	Fresh Frappe sites are created before any CRM traffic exists, so requiring a
	separate maintenance flag there only leaves framework default roles behind.
	Production upgrades continue to use :func:`execute`, which retains the
	explicit maintenance-window guard and rollback snapshot.
	"""
	create_roles(sorted(CANONICAL_ROLES | {"Administrator"}))
	quarantine = _backfill_user_roles()
	if quarantine:
		frappe.log_error(json.dumps(quarantine, ensure_ascii=False), "fresh CRM role setup quarantine")
		raise frappe.ValidationError("fresh CRM role setup has mixed-role users; see Error Log")
	_replace_role_references()
	_delete_legacy_roles()
	_assert_no_legacy_references()
	frappe.clear_cache()
