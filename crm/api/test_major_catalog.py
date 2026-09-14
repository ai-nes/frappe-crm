from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from crm.api import major_catalog


class FakeDocument:
	def __init__(self, **values):
		self.values = values
		self.permission_calls = []
		self.insert_calls = 0
		self.save_calls = 0
		self.delete_calls = 0

	def get(self, fieldname, default=None):
		return self.values.get(fieldname, default)

	def set(self, fieldname, value):
		self.values[fieldname] = value

	def check_permission(self, permission_type):
		self.permission_calls.append(permission_type)

	def insert(self):
		self.insert_calls += 1

	def save(self):
		self.save_calls += 1

	def delete(self):
		self.delete_calls += 1


class TestMajorCatalog(TestCase):
	def setUp(self):
		self.session = SimpleNamespace(user="Administrator")
		self.session_patch = patch.object(major_catalog.frappe, "session", self.session)
		self.session_patch.start()

	def tearDown(self):
		self.session_patch.stop()

	def test_list_groups_maps_status_and_search(self):
		rows = [
			{
				"name": "ENGINEERING",
				"code": "ENGINEERING",
				"display_name": "Công nghệ",
				"description": "Tech",
				"enabled": 1,
				"sort_order": 2,
				"modified": "2026-09-14 10:00:00",
			}
		]
		with patch.object(major_catalog.frappe, "get_list", return_value=rows) as get_list:
			result = major_catalog.list_major_groups(" công nghệ ", include_disabled=False)

		self.assertEqual(result["groups"][0]["name"], "Công nghệ")
		self.assertTrue(result["groups"][0]["enabled"])
		self.assertEqual(get_list.call_args.kwargs["filters"], {"enabled": 1})
		self.assertEqual(
			get_list.call_args.kwargs["or_filters"],
			[
				["name", "like", "%công nghệ%"],
				["code", "like", "%công nghệ%"],
				["display_name", "like", "%công nghệ%"],
			],
		)

	def test_list_majors_filters_by_group_and_maps_parent_name(self):
		rows = [
			{
				"name": "Software Engineering",
				"major_name": "Software Engineering",
				"major_code": "SE",
				"degree_name": "Đại học",
				"major_group": "ENGINEERING",
				"is_active": 1,
				"modified": "2026-09-14 10:00:00",
			}
		]
		with (
			patch.object(major_catalog.frappe, "get_list", return_value=rows),
			patch.object(major_catalog.frappe.db, "get_value", return_value="Công nghệ"),
		):
			result = major_catalog.list_majors(group="ENGINEERING", include_inactive=False)

		self.assertEqual(result["majors"][0]["majorGroup"], "ENGINEERING")
		self.assertEqual(result["majors"][0]["majorGroupName"], "Công nghệ")

	def test_create_group_and_major_use_create_permission(self):
		group_doc = FakeDocument(
			name="ENGINEERING",
			code="ENGINEERING",
			display_name="Công nghệ",
			enabled=1,
			sort_order=0,
			modified="2026-09-14 10:00:00",
		)
		major_doc = FakeDocument(
			name="Software Engineering",
			major_name="Software Engineering",
			major_code="SE",
			major_group="ENGINEERING",
			is_active=1,
			modified="2026-09-14 10:00:00",
		)

		with (
			patch.object(major_catalog.frappe, "new_doc", side_effect=[group_doc, major_doc]),
			patch.object(major_catalog.frappe.db, "exists", side_effect=[False, True, False]),
			patch.object(major_catalog.frappe.db, "get_value", return_value="Công nghệ"),
		):
			created_group = major_catalog.create_major_group(
				{"code": " engineering ", "display_name": " Công nghệ "}
			)
			created_major = major_catalog.create_major(
				{
					"major_name": "Software Engineering",
					"major_code": "7480201",
					"major_group": "ENGINEERING",
				}
			)

		self.assertEqual(created_group["code"], "ENGINEERING")
		self.assertEqual(created_major["code"], "7480201")
		self.assertEqual(group_doc.permission_calls, ["create"])
		self.assertEqual(major_doc.permission_calls, ["create"])

	def test_new_major_requires_a_group(self):
		with self.assertRaises(frappe.ValidationError):
			major_catalog.create_major({"major_name": "New Major"})

	def test_major_update_keeps_identifier_immutable_and_supports_old_ungrouped_rows(self):
		doc = FakeDocument(
			name="Legacy Major",
			major_name="Legacy Major",
			major_code="LEGACY",
			major_group=None,
			degree_name=None,
			is_active=1,
			modified="2026-09-14 10:00:00",
		)
		with patch.object(major_catalog.frappe, "get_doc", return_value=doc):
			updated = major_catalog.update_major(
				"Legacy Major",
				{"degree_name": "Cao đẳng"},
				expected_modified="2026-09-14 10:00:00",
			)

		self.assertEqual(doc.values["degree_name"], "Cao đẳng")
		self.assertEqual(updated["majorGroup"], None)
		self.assertEqual(doc.permission_calls, ["write"])
		self.assertEqual(doc.save_calls, 1)

		with patch.object(major_catalog.frappe, "get_doc", return_value=doc):
			with self.assertRaises(frappe.PermissionError):
				major_catalog.update_major(
					"Legacy Major",
					{"name": "Renamed Major"},
					expected_modified="2026-09-14 10:00:00",
				)

	def test_referenced_group_cannot_be_deleted(self):
		doc = FakeDocument(
			name="ENGINEERING",
			code="ENGINEERING",
			display_name="Công nghệ",
			modified="2026-09-14 10:00:00",
		)
		with (
			patch.object(major_catalog.frappe, "get_doc", return_value=doc),
			patch.object(major_catalog.frappe.db, "exists", return_value=True),
		):
			with self.assertRaises(frappe.ValidationError):
				major_catalog.delete_major_group("ENGINEERING", expected_modified="2026-09-14 10:00:00")

		self.assertEqual(doc.permission_calls, ["delete"])
		self.assertEqual(doc.delete_calls, 0)
