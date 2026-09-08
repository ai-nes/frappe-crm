# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.doctype.crm_nba_calibration_proposal.crm_nba_calibration_proposal import (
	create_calibration_proposal,
	submit_calibration_review,
)


class TestCRMNBACalibrationProposal(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.db.get_all(
			"CRM NBA Calibration Proposal",
			filters={"dataset_digest": ["like", "_test-%"]},
			pluck="name",
		):
			frappe.db.delete("CRM NBA Calibration Proposal", {"name": name})
		frappe.db.commit()

	def _make_director(self, email="_test-nba-calibration-director@example.com"):
		if not frappe.db.exists("User", email):
			user = frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Director", "send_welcome_email": 0}
			)
			user.insert(ignore_permissions=True)
		else:
			user = frappe.get_doc("User", email)
		if "Admissions Director" not in {r.role for r in user.get("roles") or []}:
			user.add_roles("Admissions Director")
		return email

	def _make_proposal(self, dataset_digest="_test-digest-1"):
		return create_calibration_proposal(
			dataset_digest=dataset_digest,
			report_digest="a" * 64,
			baseline_json={"component_weights": {"opportunity_fit": 0.45, "urgency": 0.25, "effectiveness_index": 0.30}},
			candidate_json={"component_weights": {"opportunity_fit": 0.5, "urgency": 0.2, "effectiveness_index": 0.30}},
		)

	# ------------------------------------------------------------ creation

	def test_direct_insert_without_the_service_flag_is_rejected(self):
		doc = frappe.get_doc(
			{
				"doctype": "CRM NBA Calibration Proposal",
				"dataset_digest": "_test-digest-direct",
				"report_digest": "b" * 64,
				"baseline_json": {},
				"candidate_json": {},
			}
		)
		with self.assertRaises(frappe.PermissionError):
			doc.insert(ignore_permissions=True)

	def test_create_calibration_proposal_requires_system_manager(self):
		email = self._make_director()
		frappe.set_user(email)
		try:
			with self.assertRaises(frappe.PermissionError):
				self._make_proposal("_test-digest-director-create")
		finally:
			frappe.set_user("Administrator")

	def test_create_calibration_proposal_succeeds_in_shadow_status(self):
		name = self._make_proposal("_test-digest-happy")
		doc = frappe.get_doc("CRM NBA Calibration Proposal", name)
		self.assertEqual(doc.status, "shadow")
		self.assertIsNone(doc.approved_by or None)

	# ------------------------------------------------------------ review

	def test_review_requires_director_or_system_manager_role(self):
		name = self._make_proposal("_test-digest-review-role")
		other = "_test-nba-calibration-outsider@example.com"
		if not frappe.db.exists("User", other):
			frappe.get_doc(
				{"doctype": "User", "email": other, "first_name": "Outsider", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.set_user(other)
		try:
			with self.assertRaises(frappe.PermissionError):
				submit_calibration_review(name, "approved")
		finally:
			frappe.set_user("Administrator")

	def test_director_can_approve_a_shadow_proposal(self):
		name = self._make_proposal("_test-digest-approve")
		email = self._make_director()
		frappe.set_user(email)
		try:
			result = submit_calibration_review(name, "approved", review_note="looks fine")
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result["status"], "approved")
		doc = frappe.get_doc("CRM NBA Calibration Proposal", name)
		self.assertEqual(doc.approved_by, email)
		self.assertIsNotNone(doc.approved_at)
		self.assertEqual(doc.review_note, "looks fine")

	def test_a_second_review_of_an_already_reviewed_proposal_is_rejected(self):
		name = self._make_proposal("_test-digest-double-review")
		submit_calibration_review(name, "approved")
		with self.assertRaises(frappe.ValidationError):
			submit_calibration_review(name, "rejected")

	def test_invalid_decision_value_is_rejected(self):
		name = self._make_proposal("_test-digest-bad-decision")
		with self.assertRaises(frappe.ValidationError):
			submit_calibration_review(name, "maybe")

	# ------------------------------------------------------------ immutability

	def test_report_fields_cannot_change_after_creation(self):
		name = self._make_proposal("_test-digest-immutable")
		doc = frappe.get_doc("CRM NBA Calibration Proposal", name)
		doc.dataset_digest = "_test-digest-tampered"
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)

	def test_proposal_cannot_be_deleted(self):
		name = self._make_proposal("_test-digest-no-delete")
		with self.assertRaises(frappe.PermissionError):
			frappe.delete_doc("CRM NBA Calibration Proposal", name)

	def test_approved_status_requires_an_approver(self):
		name = self._make_proposal("_test-digest-no-approver")
		doc = frappe.get_doc("CRM NBA Calibration Proposal", name)
		doc.status = "approved"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
