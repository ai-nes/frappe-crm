"""Phase 7: propose -> check impact -> approve -> effective date/version ->
audit log for the 5 governed shared lookup doctypes, per
crm/fcrm/master_data_governance.py."""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.master_data_governance import (
	GOVERNED_DOCTYPES,
	_governance_roles_for_user,
	approve_change,
	check_impact,
	propose_change,
	reject_change,
	set_governance_defaults,
)


class TestMasterDataGovernance(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	# ------------------------------------------------------------- set_governance_defaults

	def test_set_governance_defaults_auto_approves_new_row(self):
		name = self._make_lead_source("_Test Gov Source Defaults")
		doc = frappe.get_doc("CRM Lead Source", name)
		self.assertEqual(doc.owner_role, GOVERNED_DOCTYPES["CRM Lead Source"]["owner_role"])
		self.assertEqual(doc.approval_state, "Approved")
		self.assertEqual(doc.version, 1)
		self.assertTrue(doc.effective_date)

	def test_governance_uses_only_canonical_roles(self):
		self.assertEqual(GOVERNED_DOCTYPES["CRM Lead Source"]["owner_role"], "Marketing")
		self.assertEqual(GOVERNED_DOCTYPES["CRM Lost Reason"]["owner_role"], "Lead Sales")
		self.assertEqual(GOVERNED_DOCTYPES["CRM Lost Reason"]["approver_roles"], {"Lead Sales", "Marketing"})
		self.assertEqual(GOVERNED_DOCTYPES["CRM Campus"]["owner_role"], "Admissions Director")
		self.assertNotIn(
			"CRM Data Steward",
			{
				role
				for config in GOVERNED_DOCTYPES.values()
				for role in {config["owner_role"]} | config["approver_roles"]
			},
		)

	def test_system_manager_cannot_satisfy_business_role_signoffs(self):
		with patch("crm.fcrm.master_data_governance.frappe.get_roles", return_value=["System Manager"]):
			self.assertEqual(_governance_roles_for_user("system-manager@example.com"), frozenset())

	def test_set_governance_defaults_noop_for_ungoverned_doctype(self):
		# set_governance_defaults is a no-op (returns silently) for any doctype
		# not present in GOVERNED_DOCTYPES -- guards against accidental misuse
		# if it's ever wired into an unrelated doctype's before_insert.
		doc = frappe._dict({"doctype": "User"})
		set_governance_defaults(doc)
		self.assertNotIn("owner_role", doc)

	# ------------------------------------------------------------- check_impact

	def test_check_impact_counts_real_usage(self):
		platform_name = self._make_platform("_Test Gov Platform Impact")
		contact = self._make_contact("_Test Gov Impact Contact", "0981113301", platform=platform_name)

		usage = check_impact("CRM Platform", platform_name)
		self.assertEqual(usage.get("CRM Contact.platform"), 1)
		frappe.delete_doc("CRM Contact", contact, force=True)

	def test_check_impact_empty_for_lost_reason_is_intentional_zero(self):
		# CRM Lost Reason's usage_checks list is deliberately empty (nothing in
		# this fork links to it yet) -- check_impact must return {} rather than
		# erroring or fabricating a count.
		lost_reason = self._make_lost_reason("_Test Gov Lost Reason Impact")
		usage = check_impact("CRM Lost Reason", lost_reason)
		self.assertEqual(usage, {})

	# ------------------------------------------------------------- propose_change

	def test_propose_change_denied_without_owner_role(self):
		source = self._make_lead_source("_Test Gov Source Propose Denied")
		user, _ = self._make_user_with_roles("_test_gov_propose_denied", roles=["Sale"])
		try:
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				propose_change("CRM Lead Source", source, "Retire", reason="cleanup")
		finally:
			frappe.set_user("Administrator")
			self._cleanup_user(user)

	def test_direct_governed_update_is_rejected(self):
		source = self._make_lead_source("_Test Gov Direct Update")
		doc = frappe.get_doc("CRM Lead Source", source)
		doc.source_name = "_Test Gov Direct Update Changed"
		user, _ = self._make_user_with_roles("_test_gov_direct_update", roles=["Marketing"])
		try:
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				doc.save(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")
			self._cleanup_user(user)

	def test_propose_change_rejects_invalid_action(self):
		source = self._make_lead_source("_Test Gov Source Bad Action")
		with self.assertRaises(frappe.ValidationError):
			propose_change("CRM Lead Source", source, "Delete", reason="cleanup")

	def test_propose_change_rename_requires_new_value(self):
		source = self._make_lead_source("_Test Gov Source Rename NoValue")
		with self.assertRaises(frappe.ValidationError):
			propose_change("CRM Lead Source", source, "Rename", reason="typo fix")

	def test_propose_change_requires_reason(self):
		source = self._make_lead_source("_Test Gov Source No Reason")
		with self.assertRaises(frappe.ValidationError):
			propose_change("CRM Lead Source", source, "Retire")

	def test_propose_change_missing_docname(self):
		with self.assertRaises(frappe.ValidationError):
			propose_change("CRM Lead Source", "_Test Gov Nonexistent Source", "Retire", reason="cleanup")

	def test_propose_change_success_creates_change_log(self):
		source = self._make_lead_source("_Test Gov Source Propose OK")
		change_name = propose_change("CRM Lead Source", source, "Retire", reason="deprecated channel")
		self.addCleanup(lambda: frappe.delete_doc("CRM Master Data Change Log", change_name, force=True))

		change = frappe.get_doc("CRM Master Data Change Log", change_name)
		self.assertEqual(change.status, "Proposed")
		self.assertEqual(change.reference_doctype, "CRM Lead Source")
		self.assertEqual(change.reference_docname, source)
		self.assertEqual(
			change.required_approver_roles,
			",".join(sorted(GOVERNED_DOCTYPES["CRM Lead Source"]["approver_roles"])),
		)
		impact = json.loads(change.impact_summary)
		self.assertIsInstance(impact, dict)

	# ------------------------------------------------------------- approve_change

	def test_approve_change_rejects_non_proposed_status(self):
		source = self._make_lead_source("_Test Gov Source Approve Bad Status")
		change_name = propose_change("CRM Lead Source", source, "Retire", reason="deprecated")
		self.addCleanup(lambda: frappe.delete_doc("CRM Master Data Change Log", change_name, force=True))
		approve_change(change_name)  # single-approver type -> immediately applied

		with self.assertRaises(frappe.ValidationError):
			approve_change(change_name)

	def test_approve_change_denied_without_approver_role(self):
		source = self._make_lead_source("_Test Gov Source Approve Denied")
		change_name = propose_change("CRM Lead Source", source, "Retire", reason="deprecated")
		self.addCleanup(lambda: frappe.delete_doc("CRM Master Data Change Log", change_name, force=True))

		user, _ = self._make_user_with_roles("_test_gov_approve_denied", roles=["Sale"])
		try:
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				approve_change(change_name)
		finally:
			frappe.set_user("Administrator")
			self._cleanup_user(user)

	def test_approve_change_single_approver_applies_rename_immediately(self):
		source = self._make_lead_source("_Test Gov Source Rename Src")
		change_name = propose_change(
			"CRM Lead Source",
			source,
			"Rename",
			new_value="_Test Gov Source Rename Dst",
			reason="rebrand",
		)
		self.addCleanup(lambda: frappe.delete_doc("CRM Master Data Change Log", change_name, force=True))
		self.addCleanup(
			lambda: frappe.delete_doc("CRM Lead Source", "_Test Gov Source Rename Dst", force=True)
		)

		user, _ = self._make_user_with_roles("_test_gov_marketing", roles=["Marketing"])
		try:
			frappe.set_user(user)
			status = approve_change(change_name)
		finally:
			frappe.set_user("Administrator")
			self._cleanup_user(user)

		self.assertEqual(status, "Approved")
		self.assertFalse(frappe.db.exists("CRM Lead Source", "_Test Gov Source Rename Src"))
		self.assertTrue(frappe.db.exists("CRM Lead Source", "_Test Gov Source Rename Dst"))
		renamed = frappe.get_doc("CRM Lead Source", "_Test Gov Source Rename Dst")
		self.assertEqual(renamed.version, 2)

	def test_approve_change_dual_signoff_requires_both_roles(self):
		lost_reason = self._make_lost_reason("_Test Gov Lost Reason Dual")
		change_name = propose_change("CRM Lost Reason", lost_reason, "Retire", reason="no longer used")
		self.addCleanup(lambda: frappe.delete_doc("CRM Master Data Change Log", change_name, force=True))

		team_leader, _ = self._make_user_with_roles("_test_gov_lead_sales", roles=["Lead Sales"])
		marketing_lead, _ = self._make_user_with_roles("_test_gov_dual_marketing", roles=["Marketing"])
		try:
			frappe.set_user(team_leader)
			status_after_first = approve_change(change_name)
			self.assertEqual(status_after_first, "Proposed")

			change = frappe.get_doc("CRM Master Data Change Log", change_name)
			self.assertEqual(change.approved_by_roles, "Lead Sales")
			self.assertEqual(
				frappe.db.get_value("CRM Lost Reason", lost_reason, "approval_state"), "Approved"
			)

			frappe.set_user(marketing_lead)
			status_after_second = approve_change(change_name)
			self.assertEqual(status_after_second, "Approved")

			change.reload()
			self.assertEqual(set(change.approved_by_roles.split(",")), {"Lead Sales", "Marketing"})
			self.assertEqual(frappe.db.get_value("CRM Lost Reason", lost_reason, "approval_state"), "Retired")
		finally:
			frappe.set_user("Administrator")
			self._cleanup_user(team_leader)
			self._cleanup_user(marketing_lead)

	# ------------------------------------------------------------- reject_change

	def test_reject_change_sets_status_and_appends_reason(self):
		source = self._make_lead_source("_Test Gov Source Reject")
		change_name = propose_change("CRM Lead Source", source, "Retire", reason="deprecated channel")
		self.addCleanup(lambda: frappe.delete_doc("CRM Master Data Change Log", change_name, force=True))

		user, _ = self._make_user_with_roles("_test_gov_rejector", roles=["Marketing"])
		try:
			frappe.set_user(user)
			status = reject_change(change_name, reason="not a real duplicate")
		finally:
			frappe.set_user("Administrator")
			self._cleanup_user(user)

		self.assertEqual(status, "Rejected")
		change = frappe.get_doc("CRM Master Data Change Log", change_name)
		self.assertEqual(change.status, "Rejected")
		self.assertIn("not a real duplicate", change.reason)

	def test_reject_change_denied_without_approver_role(self):
		source = self._make_lead_source("_Test Gov Source Reject Denied")
		change_name = propose_change("CRM Lead Source", source, "Retire", reason="deprecated")
		self.addCleanup(lambda: frappe.delete_doc("CRM Master Data Change Log", change_name, force=True))

		user, _ = self._make_user_with_roles("_test_gov_reject_denied", roles=["Sale"])
		try:
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				reject_change(change_name, reason="no")
		finally:
			frappe.set_user("Administrator")
			self._cleanup_user(user)

	# ------------------------------------------------------------- DocType-level validate()

	def test_change_log_rejects_ungoverned_reference_doctype(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "CRM Master Data Change Log",
					"reference_doctype": "User",
					"reference_docname": "Administrator",
					"action": "Retire",
					"reason": "should never insert",
					"status": "Proposed",
				}
			).insert(ignore_permissions=True)

	# ------------------------------------------------------------------- helpers

	def _make_lead_source(self, name):
		if frappe.db.exists("CRM Lead Source", name):
			frappe.delete_doc("CRM Lead Source", name, force=True)
		doc = frappe.get_doc({"doctype": "CRM Lead Source", "source_name": name})
		doc.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: (
				frappe.delete_doc("CRM Lead Source", doc.name, force=True, delete_permanently=True)
				if frappe.db.exists("CRM Lead Source", doc.name)
				else None
			)
		)
		return doc.name

	def _make_platform(self, name):
		if frappe.db.exists("CRM Platform", name):
			frappe.delete_doc("CRM Platform", name, force=True)
		lead_source = self._make_lead_source(f"{name} Source")
		doc = frappe.get_doc({"doctype": "CRM Platform", "platform_name": name, "lead_source": lead_source})
		doc.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: (
				frappe.delete_doc("CRM Platform", doc.name, force=True)
				if frappe.db.exists("CRM Platform", doc.name)
				else None
			)
		)
		return doc.name

	def _make_lost_reason(self, name):
		if frappe.db.exists("CRM Lost Reason", name):
			frappe.delete_doc("CRM Lost Reason", name, force=True)
		doc = frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": name})
		doc.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: (
				frappe.delete_doc("CRM Lost Reason", doc.name, force=True)
				if frappe.db.exists("CRM Lost Reason", doc.name)
				else None
			)
		)
		return doc.name

	def _make_contact(self, name, phone, platform=None):
		payload = {
			"doctype": "CRM Contact",
			"full_name": name,
			"phone": phone,
			"enrollment_status": "Có triển vọng",
		}
		if platform:
			payload["platform"] = platform
		doc = frappe.get_doc(payload)
		doc.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: (
				frappe.delete_doc("CRM Contact", doc.name, force=True)
				if frappe.db.exists("CRM Contact", doc.name)
				else None
			)
		)
		return doc.name

	def _make_user_with_roles(self, prefix, roles=None):
		email = f"{prefix}@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": prefix,
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in (roles or ["Sale"])],
			}
		)
		user.insert(ignore_permissions=True)
		return email, None

	def _cleanup_user(self, user):
		if user and frappe.db.exists("User", user):
			frappe.delete_doc("User", user, force=True)
