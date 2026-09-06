"""Integration contracts for the Person-School association grain."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMSchoolStakeholder(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=8)
		self.role = frappe.db.get_value("CRM Stakeholder Role", {"enabled": 1}, "name")
		self.activity_type = frappe.db.get_value("CRM School Activity Type", {"enabled": 1}, "name")
		if not self.role or not self.activity_type:
			self.skipTest("School-domain lookups are not installed")
		self.province = frappe.db.get_value("CRM Province", {}, "name")
		self.ward = frappe.db.get_value("CRM Ward", {"province": self.province}, "name") if self.province else None
		if not self.province or not self.ward:
			self.skipTest("Geography masters are not installed")
		phone_suffix = "".join(str(int(char, 16) % 10) for char in self.suffix)
		self.person = frappe.get_doc({
			"doctype": "CRM Person",
			"full_name": f"_Test Stakeholder {self.suffix}",
			"phone": f"09{phone_suffix}",
		}).insert(ignore_permissions=True)
		self.schools = []
		self.associations = []
		self.activities = []

	def tearDown(self):
		for doctype, names in (
			("CRM School Activity", self.activities),
			("CRM School Stakeholder", self.associations),
			("CRM High School", self.schools),
			("CRM Person", [self.person.name] if getattr(self, "person", None) else []),
		):
			for name in names:
				if frappe.db.exists(doctype, name):
					frappe.delete_doc(doctype, name, force=True)

	def _school(self, suffix):
		school = frappe.get_doc({
			"doctype": "CRM High School",
			"school_name": f"_Test School {self.suffix} {suffix}",
			"school_code": f"TEST-{self.suffix}-{suffix}",
			"province": self.province,
			"ward": self.ward,
		}).insert(ignore_permissions=True)
		self.schools.append(school.name)
		return school

	def _association(self, school):
		association = frappe.get_doc({
			"doctype": "CRM School Stakeholder",
			"high_school": school.name,
			"person": self.person.name,
			"stakeholder_role": self.role,
			"position_title": "Principal",
		}).insert(ignore_permissions=True)
		self.associations.append(association.name)
		return association

	def test_one_person_can_have_multiple_school_associations(self):
		school_a = self._school("A")
		school_b = self._school("B")

		self._association(school_a)
		self._association(school_b)

		self.assertEqual(
			frappe.db.count("CRM School Stakeholder", {"person": self.person.name}),
			2,
		)

	def test_duplicate_association_is_rejected(self):
		school = self._school("Duplicate")
		self._association(school)

		with self.assertRaises(frappe.DuplicateEntryError):
			frappe.get_doc({
				"doctype": "CRM School Stakeholder",
				"high_school": school.name,
				"person": self.person.name,
				"stakeholder_role": self.role,
			}).insert(ignore_permissions=True)

	def test_activity_rejects_stakeholder_from_another_school(self):
		school_a = self._school("Activity-A")
		school_b = self._school("Activity-B")
		association = self._association(school_a)

		activity = frappe.get_doc({
			"doctype": "CRM School Activity",
			"high_school": school_b.name,
			"activity_type": self.activity_type,
			"activity_date": "2026-08-30",
			"stakeholder": association.name,
		})
		with self.assertRaises(frappe.ValidationError):
			activity.insert(ignore_permissions=True)

	def test_relationship_backfill_rollback_removes_only_created_association(self):
		school = self._school("Rollback")
		association = self._association(school)

		from crm.patches.v1_0.simplify_school_domain_schema import rollback_relationship_backfill

		rollback_relationship_backfill({
			"version": 1,
			"activity_stakeholders": [],
			"activity_metrics": [],
			"migration": {"created_association_ids": [association.name]},
		})

		self.assertFalse(frappe.db.exists("CRM School Stakeholder", association.name))
