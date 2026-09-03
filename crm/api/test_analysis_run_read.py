"""Permission, visibility, and retention contract for the Student 360 reader.

Exercises the real permission model, the real claim-JSON parsing, and the real
``status='completed'`` / ``stage_kind='student_360'`` filters against fixture
documents -- nothing in the module under test is mocked.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date

from crm.api import analysis_run_read
from crm.fcrm.test_permissions import TestSharedScopingPermissions

_RUN_TYPE = "CRM Student Analysis Run"


class TestGetStudent360(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = TestSharedScopingPermissions._make_campus(self, "_360 Reader Campus")
		self._department = TestSharedScopingPermissions._get_or_create_department(
			self, "_360 Reader Dept", self._campus
		)
		self._student = self._make_student("_360 Reader Student")
		self._run, self._stage = self._make_completed_360(self._student.name, revision="7")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("CRM Analysis Run Stage", {"parent_run": self._run})
		frappe.db.delete(_RUN_TYPE, {"name": self._run})
		for name in frappe.db.get_all("CRM Student", filters={"name": self._student.name}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)
		frappe.delete_doc("CRM Department", self._department, force=True)
		frappe.delete_doc("CRM Campus", self._campus, force=True)

	def _make_student(self, name):
		phone = "0" + "".join(str((int(c, 16) + 1) % 10) for c in frappe.generate_hash(length=9))
		student = frappe.get_doc({"doctype": "CRM Student", "student_name": name, "phone": phone})
		previous = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous
		return student

	def _make_completed_360(self, student, *, revision, creation=None, claims=None):
		digest = frappe.generate_hash(length=32) + frappe.generate_hash(length=32)
		run = frappe.get_doc(
			{
				"doctype": _RUN_TYPE,
				"student": student,
				"source_revision": revision,
				"source_digest": digest,
				"trigger": "automatic",
				"status": "completed",
				"request_fingerprint": frappe.generate_hash(length=32) + frappe.generate_hash(length=32),
			}
		).insert(ignore_permissions=True)
		if creation:
			frappe.db.set_value(_RUN_TYPE, run.name, "creation", creation, update_modified=False)
		stage = frappe.get_doc(
			{
				"doctype": "CRM Analysis Run Stage",
				"parent_run_type": _RUN_TYPE,
				"parent_run": run.name,
				"stage_kind": "student_360",
				"stage_key": f"{_RUN_TYPE}:{run.name}:student_360",
				"status": "completed",
				"stage_generation": 1,
				"expected_source_revision": revision,
				"expected_source_digest": digest,
				"policy_revision": "p1",
				"model_revision": "m1",
				"result_digest": "a" * 64,
				"claims": frappe.as_json(
					claims
					if claims is not None
					else [
						{
							"kind": "fact",
							"text": "Family attended the open day.",
							"provenance_ids": [f"student:{student}"],
							"visibility": "shareable",
						}
					]
				),
			}
		).insert(ignore_permissions=True)
		return run.name, stage.name

	def test_reads_by_run_id(self):
		payload = analysis_run_read.get_student_360(run_id=self._run)
		self.assertEqual(payload["status"], "completed")
		self.assertEqual(payload["student"], self._student.name)
		self.assertEqual(payload["source_revision"], "7")
		self.assertEqual(payload["result_digest"], "a" * 64)
		self.assertEqual(len(payload["claims"]), 1)
		self.assertEqual(payload["retention_expired"], False)

	def test_reads_by_student_and_source_revision(self):
		payload = analysis_run_read.get_student_360(student=self._student.name, source_revision="7")
		self.assertEqual(payload["run_id"], self._run)
		self.assertEqual(payload["status"], "completed")

	def test_wrong_revision_is_not_available(self):
		payload = analysis_run_read.get_student_360(student=self._student.name, source_revision="999")
		self.assertEqual(payload["status"], "not_available")
		self.assertEqual(payload["claims"], [])

	def test_requires_exactly_one_lookup_mode(self):
		with self.assertRaises(frappe.ValidationError):
			analysis_run_read.get_student_360()
		with self.assertRaises(frappe.ValidationError):
			analysis_run_read.get_student_360(run_id=self._run, student=self._student.name, source_revision="7")

	def test_retention_expired_withholds_claims(self):
		old_run, _ = self._make_completed_360(
			self._student.name, revision="3", creation=add_to_date(None, days=-2000)
		)
		self.addCleanup(frappe.db.delete, "CRM Analysis Run Stage", {"parent_run": old_run})
		self.addCleanup(frappe.db.delete, _RUN_TYPE, {"name": old_run})
		payload = analysis_run_read.get_student_360(run_id=old_run)
		self.assertEqual(payload["status"], "completed")
		self.assertEqual(payload["retention_expired"], True)
		self.assertEqual(payload["claims"], [])
		self.assertEqual(payload["result_digest"], "a" * 64)

	def test_out_of_scope_caller_gets_nothing(self):
		# A Sale sees only their own-assigned students; this fixture student is
		# assigned to nobody, so the run and its revision are both invisible.
		user, staff = TestSharedScopingPermissions._make_user_and_staff(
			self, "_360 Scoped Sale", roles=["Sale"]
		)
		self.addCleanup(frappe.delete_doc, "User", user, force=True)
		self.addCleanup(frappe.delete_doc, "CRM Staff", staff, force=True)

		frappe.set_user(user)
		try:
			with self.assertRaises(frappe.PermissionError):
				analysis_run_read.get_student_360(run_id=self._run)
			with self.assertRaises(frappe.PermissionError):
				analysis_run_read.get_student_360(student=self._student.name, source_revision="7")
		finally:
			frappe.set_user("Administrator")
