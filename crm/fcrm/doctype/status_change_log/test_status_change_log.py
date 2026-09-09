# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.doctype.status_change_log.status_change_log import get_duration, get_status_field


class _StubMeta:
	def __init__(self, fields):
		self._fields = set(fields)

	def has_field(self, fieldname):
		return fieldname in self._fields


class _StubDoc:
	"""Minimal stand-in — get_status_field only touches doc.doctype and doc.meta."""

	def __init__(self, doctype, fields):
		self.doctype = doctype
		self.meta = _StubMeta(fields)


class TestGetStatusField(FrappeTestCase):
	def test_uses_hook_override_when_field_exists(self):
		doc = _StubDoc("CRM Student", ["student_stage", "status", "stage"])
		self.assertEqual(get_status_field(doc), "student_stage")

	def test_falls_back_to_stage_when_no_hook_registered(self):
		doc = _StubDoc("CRM Lead", ["stage", "status"])
		self.assertEqual(get_status_field(doc), "stage")

	def test_falls_back_to_status_when_no_stage_field(self):
		doc = _StubDoc("CRM Lead", ["status"])
		self.assertEqual(get_status_field(doc), "status")

	def test_returns_none_when_no_candidate_field_present(self):
		doc = _StubDoc("CRM Lead", ["some_other_field"])
		self.assertIsNone(get_status_field(doc))

	def test_ignores_hook_override_when_field_missing_from_doctype(self):
		# Hook says "student_stage" for CRM Student, but this stub doesn't have
		# that field — must fall back to stage/status rather than returning a
		# nonexistent fieldname.
		doc = _StubDoc("CRM Student", ["stage"])
		self.assertEqual(get_status_field(doc), "stage")


class TestGetDuration(FrappeTestCase):
	def test_duration_in_seconds(self):
		duration = get_duration("2026-01-01 00:00:00", "2026-01-01 00:05:00")
		self.assertEqual(duration, 300)


class TestStatusChangeLogViaCRMContact(FrappeTestCase):
	"""Integration coverage for add_status_change_log/log_status_change through the
	real CRM Contact save path — the hook wiring (crm.hooks.status_change_log_field
	+ doc_events) is the behavior actually in play in production."""

	def setUp(self):
		frappe.set_user("Administrator")
		self._statuses = {}
		for stage_order, status_name in enumerate(("TEST_STATUS_A", "TEST_STATUS_B", "TEST_STATUS_C"), 1):
			if not frappe.db.exists("CRM Enrollment Status", status_name):
				frappe.get_doc(
					{
						"doctype": "CRM Enrollment Status",
						"code": status_name,
						"display_name": status_name,
						"sort_order": stage_order,
						"stage_category": "open",
					}
				).insert(ignore_permissions=True)
			self._statuses[status_name] = status_name

	def tearDown(self):
		for name in frappe.db.get_all("CRM Student", filters={"phone": ["like", "090000%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)
		for status_name in self._statuses:
			if frappe.db.exists("CRM Enrollment Status", status_name):
				frappe.delete_doc("CRM Enrollment Status", status_name, force=True)

	def _make_contact(self, phone, student_stage):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "_Test Status Contact",
				"phone": phone,
				"student_stage": student_stage,
			}
		)
		doc.insert(ignore_permissions=True)
		if not student_stage:
			frappe.db.set_value("CRM Student", doc.name, "student_stage", "", update_modified=False)
		# validate() derives owner_staff/owning_team via db_set-free assignment on the
		# in-memory doc, but reload to pick up server-side defaults (status_change_log)
		# consistently with the rest of this test module's pattern.
		doc.reload()
		return doc

	def test_status_change_appends_log_row(self):
		contact = self._make_contact("0900000001", "New")
		self.assertEqual(len(contact.status_change_log), 1)
		self.assertEqual(contact.status_change_log[0].to, "")

		contact.student_stage = "Attempting"
		self._save_stage(contact)
		contact.reload()

		self.assertEqual(len(contact.status_change_log), 2)
		closed_row = contact.status_change_log[0]
		self.assertEqual(closed_row.get("from"), "New")
		self.assertEqual(closed_row.to, "Attempting")
		open_row = contact.status_change_log[1]
		self.assertEqual(open_row.get("from"), "Attempting")
		self.assertEqual(open_row.to, "")

	def test_no_status_change_does_not_append_new_row(self):
		contact = self._make_contact("0900000002", "New")
		self.assertEqual(len(contact.status_change_log), 1)

		contact.full_name = "_Test Status Contact Renamed"
		self._save_stage(contact)
		contact.reload()

		self.assertEqual(len(contact.status_change_log), 1)
		self.assertEqual(contact.status_change_log[0].get("from"), "New")
		self.assertEqual(contact.status_change_log[0].to, "")

	def test_multiple_status_changes_each_append(self):
		contact = self._make_contact("0900000003", "New")

		contact.student_stage = "Attempting"
		self._save_stage(contact)
		contact.reload()

		contact.student_stage = "Connected"
		self._save_stage(contact)
		contact.reload()

		self.assertEqual(len(contact.status_change_log), 3)
		self.assertEqual(contact.status_change_log[-1].get("from"), "Connected")
		self.assertEqual(contact.status_change_log[-1].to, "")

	def test_status_change_on_record_with_empty_log_and_blank_previous_status(self):
		# Simulates every CRM Contact created before this hook existed: an existing
		# record whose status_change_log is empty and whose previous status is blank.
		# add_status_change_log must backfill an open row instead of indexing into
		# the (still empty) child table.
		contact = self._make_contact("0900000005", "")
		frappe.db.delete("Status Change Log", {"parent": contact.name, "parenttype": "CRM Student"})
		contact.reload()
		self.assertEqual(len(contact.status_change_log), 0)

		contact.student_stage = "Attempting"
		self._save_stage(contact)  # must not raise IndexError
		contact.reload()

		self.assertEqual(len(contact.status_change_log), 2)
		closed_row = contact.status_change_log[0]
		self.assertEqual(closed_row.get("from"), "")
		self.assertEqual(closed_row.to, "Attempting")
		open_row = contact.status_change_log[1]
		self.assertEqual(open_row.get("from"), "Attempting")
		self.assertEqual(open_row.to, "")

	def _save_stage(self, contact):
		previous_flag = getattr(frappe.flags, "student_stage_service", False)
		frappe.flags.student_stage_service = True
		try:
			contact.save(ignore_permissions=True)
		finally:
			frappe.flags.student_stage_service = previous_flag

	def test_log_status_change_failure_never_blocks_contact_save(self):
		contact = self._make_contact("0900000004", "New")

		def _boom(doc):
			raise RuntimeError("simulated status log failure")

		import crm.fcrm.doctype.status_change_log.status_change_log as scl_module

		patched = scl_module.add_status_change_log
		scl_module.add_status_change_log = _boom
		try:
			contact.student_stage = "Attempting"
			# Must not raise even though the status log helper blows up.
			self._save_stage(contact)
		finally:
			scl_module.add_status_change_log = patched

		contact.reload()
		self.assertEqual(contact.student_stage, "Attempting")
