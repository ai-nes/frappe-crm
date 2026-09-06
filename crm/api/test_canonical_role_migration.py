"""Post-cutover proof that the Frappe site contains only canonical CRM roles."""
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.patches.v1_0.migrate_to_canonical_crm_roles import (
	BACKFILL_ROLE_MAP,
	CANONICAL_BUSINESS_ROLES,
	_checksum,
	_canonical_targets,
	execute,
	restore_from_snapshot,
)
from crm.operations_cutover_canonical_roles import _MODULE as canonical_cutover


class TestCanonicalRoleCutover(FrappeTestCase):
	def test_cutover_preserves_already_canonical_user_roles(self):
		rows = [
			SimpleNamespace(name="canonical", parent="user@example.com", role="Sale"),
			SimpleNamespace(name="legacy", parent="user@example.com", role="Sales Manager"),
		]
		with (
			patch.object(canonical_cutover.frappe, "get_all", side_effect=[rows, []]),
			patch.object(canonical_cutover, "_ensure_user_role") as ensure_role,
			patch.object(canonical_cutover.frappe.db, "delete") as delete,
		):
			changes = canonical_cutover._replace_user_roles()

		self.assertEqual(changes, [{"user": "user@example.com", "from": "Sales Manager", "to": "Lead Sale"}])
		ensure_role.assert_called_once_with("user@example.com", "Lead Sale")
		delete.assert_called_once_with("Has Role", {"name": "legacy"})

	def test_historical_assignments_map_to_one_least_privilege_role(self):
		self.assertEqual(_canonical_targets({"Sales User"}), {"Sale"})
		self.assertEqual(_canonical_targets({"Sales Manager", "Sales User"}), {"Lead Sale"})
		self.assertEqual(_canonical_targets({"Marketing Operator", "Marketing Lead"}), {"Marketing"})

	def test_site_has_no_legacy_crm_role_records(self):
		for legacy_role in BACKFILL_ROLE_MAP:
			self.assertFalse(frappe.db.exists("Role", legacy_role), legacy_role)
		for canonical_role in CANONICAL_BUSINESS_ROLES:
			self.assertTrue(frappe.db.exists("Role", canonical_role), canonical_role)

	def test_restore_from_snapshot_rehydrates_all_role_bound_sections(self):
		payload = {
			"version": 4,
			"scope_roles": ["Sales User"],
			"affected_users": ["user@example.com"],
			"roles": [{"name": "Sales User", "role_name": "Sales User", "desk_access": 1, "disabled": 0}],
			"assignments": [{"parent": "user@example.com", "role": "Sales User"}],
			"docperms": [{
				"name": "perm-sales-user", "parent": "CRM Student", "parenttype": "DocType", "parentfield": "permissions", "idx": 1,
				"role": "Sales User", "permlevel": 0, "read": 1, "write": 0, "create": 0, "delete": 0,
				"submit": 0, "cancel": 0, "amend": 0, "report": 1, "export": 1, "import": 0, "share": 0, "print": 1, "email": 0, "if_owner": 1, "select": 1,
			}],
			"custom_docperms": [{
				"name": "custom-perm-sales-user", "parent": "CRM Student", "parenttype": "Customize Form", "parentfield": "permissions", "idx": 1,
				"role": "Sales User", "permlevel": 0, "read": 1, "write": 0, "create": 0, "delete": 0,
				"submit": 0, "cancel": 0, "amend": 0, "report": 1, "export": 1, "import": 0, "share": 0, "print": 1, "email": 0, "if_owner": 1, "select": 1,
			}],
			"capability_grants": [{
				"name": "grant-sales-user", "parent": "Sales User", "parenttype": "Role", "parentfield": "custom_ai_capability_grants", "idx": 1,
				"grant_type": "data_scope", "value": "student.self",
			}],
			"user_permissions": [{
				"name": "user-perm-sales-user", "user": "user@example.com", "allow": "CRM Student", "for_value": "STU-1",
				"is_default": 0, "apply_to_all_doctypes": 0, "applicable_for": "CRM Student", "hide_descendants": 0,
			}],
			"invitations": [{
				"name": "invite-sales-user", "email": "invite@example.com", "role": "Sales User", "key": "k", "invited_by": "Administrator", "status": "Pending",
			}],
			"role_references": [],
			"aliases": [{"source_role": "Sales User", "canonical_role": "Sale"}],
			"manifest_hashes": {"Sales User": "a" * 64},
		}
		snapshot = {**payload, "checksum": _checksum(payload)}
		inserted = []

		class FakeDoc:
			def __init__(self, data):
				self.data = data

			def insert(self, **_kwargs):
				inserted.append(self.data)

		with patch.object(frappe.db, "exists", return_value=False), \
			patch.object(frappe.db, "delete") as delete, \
			patch.object(frappe.db, "commit"), \
			patch.object(frappe, "clear_cache"), \
			patch.object(frappe, "get_doc", side_effect=lambda data: FakeDoc(data)):
			restore_from_snapshot(snapshot)

		doctypes = {row["doctype"] for row in inserted}
		self.assertTrue({"Role", "Has Role", "DocPerm", "Custom DocPerm", "CRM AI Capability Grant"} <= doctypes)
		self.assertIn({"name": "perm-sales-user"}, [call.args[1] for call in delete.call_args_list if call.args[0] == "DocPerm"])
		self.assertNotIn({"role": "Administrator"}, [call.args[1] for call in delete.call_args_list if call.args[0] == "DocPerm"])
		custom_rows = [row for row in inserted if row["doctype"] == "Custom DocPerm"]
		self.assertNotIn("parenttype", custom_rows[0])
		self.assertNotIn("parentfield", custom_rows[0])

	def test_restore_preserves_post_cutover_rows_with_empty_snapshot(self):
		payload = {
			"version": 4,
			"scope_roles": ["Sale"],
			"affected_users": [],
			"roles": [{"name": "Sale", "role_name": "Sale", "desk_access": 1, "disabled": 0}],
			"assignments": [], "docperms": [], "custom_docperms": [],
			"capability_grants": [], "user_permissions": [], "invitations": [],
			"role_references": [],
			"aliases": [], "manifest_hashes": {"Sale": "a" * 64},
		}
		snapshot = {**payload, "checksum": _checksum(payload)}
		with patch.object(frappe.db, "exists", return_value=True), \
			patch.object(frappe.db, "delete") as delete, \
			patch.object(frappe.db, "set_value"), \
			patch.object(frappe.db, "commit"), \
			patch.object(frappe, "clear_cache"):
			restore_from_snapshot(snapshot)

		self.assertNotIn(("DocPerm", {"role": "Sale"}), [(call.args[0], call.args[1]) for call in delete.call_args_list])
		self.assertNotIn(("Custom DocPerm", {"role": "Sale"}), [(call.args[0], call.args[1]) for call in delete.call_args_list])
		self.assertNotIn(("CRM AI Capability Grant", {"parent": "Sale"}), [(call.args[0], call.args[1]) for call in delete.call_args_list])

	def test_restore_rejects_corrupt_snapshot(self):
		with self.assertRaises(ValueError):
			restore_from_snapshot({"version": 4, "assignments": [], "checksum": "bad"})

	def test_restore_rejects_legacy_snapshot_schema(self):
		payload = {
			"version": 3, "scope_roles": ["Sale"], "affected_users": [],
			"roles": [], "assignments": [], "role_profile_assignments": [],
			"docperms": [], "custom_docperms": [], "capability_grants": [],
			"user_permissions": [], "invitations": [], "role_references": [],
			"aliases": [], "manifest_hashes": {"Sale": "a" * 64},
		}
		with self.assertRaisesRegex(ValueError, "legacy snapshots"):
			restore_from_snapshot({**payload, "checksum": _checksum(payload)})

	def test_execute_runs_cutover_after_quarantine_is_empty(self):
		calls = []
		with patch("crm.patches.v1_0.migrate_to_canonical_crm_roles._require_maintenance_window"), \
			patch("crm.patches.v1_0.migrate_to_canonical_crm_roles._write_snapshot_once"), \
			patch("crm.patches.v1_0.migrate_to_canonical_crm_roles.create_roles", side_effect=lambda *_: calls.append("roles")), \
			patch("crm.patches.v1_0.migrate_to_canonical_crm_roles._backfill_user_roles", return_value=[]), \
			patch("crm.patches.v1_0.migrate_to_canonical_crm_roles._replace_role_references", side_effect=lambda: calls.append("replace")), \
			patch("crm.patches.v1_0.migrate_to_canonical_crm_roles._delete_legacy_roles", side_effect=lambda: calls.append("delete")), \
			patch("crm.patches.v1_0.migrate_to_canonical_crm_roles._assert_no_legacy_references", side_effect=lambda: calls.append("assert")), \
			patch.object(frappe.db, "commit", side_effect=lambda: calls.append("commit")), \
			patch.object(frappe, "clear_cache"):
			execute()

		self.assertEqual(calls, ["roles", "replace", "delete", "assert", "commit"])
