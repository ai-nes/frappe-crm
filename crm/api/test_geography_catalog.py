from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from crm.api import geography_catalog


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


class TestGeographyCatalog(TestCase):
	def setUp(self):
		self.session = SimpleNamespace(user="Administrator")
		self.session_patch = patch.object(geography_catalog.frappe, "session", self.session)
		self.session_patch.start()

	def tearDown(self):
		self.session_patch.stop()

	def test_list_provinces_maps_labels_and_filters_search(self):
		rows = [
			{
				"name": "HCM",
				"province_code": "79",
				"province_name": "Thành phố Hồ Chí Minh",
				"region": "MN",
				"city_type": "Centrally Controlled City",
				"modified": "2026-09-15 10:00:00",
			}
		]
		with (
			patch.object(geography_catalog.frappe, "get_list", return_value=rows) as get_list,
			patch.object(geography_catalog.frappe.db, "get_value", return_value="Miền Nam"),
		):
			result = geography_catalog.list_provinces(" Hồ Chí Minh ", city_type="Centrally Controlled City")

		self.assertEqual(result["provinces"][0]["name"], "Thành phố Hồ Chí Minh")
		self.assertEqual(result["provinces"][0]["regionName"], "Miền Nam")
		self.assertEqual(
			get_list.call_args.kwargs["or_filters"],
			[
				["name", "like", "%Hồ Chí Minh%"],
				["province_code", "like", "%Hồ Chí Minh%"],
				["province_name", "like", "%Hồ Chí Minh%"],
			],
		)

	def test_list_school_areas_maps_status_and_uses_pagination_contract(self):
		rows = [
			{
				"name": "KV1",
				"code": "KV1",
				"display_name": "Khu vực 1",
				"description": None,
				"enabled": 1,
				"sort_order": 10,
				"modified": "2026-09-15 10:00:00",
			}
		]
		with patch.object(geography_catalog.frappe, "get_list", return_value=rows):
			result = geography_catalog.list_school_areas(
				include_disabled=False,
				start=0,
				page_length=8,
			)

		self.assertEqual(result["schoolAreas"][0]["code"], "KV1")
		self.assertEqual(result["schoolAreas"][0]["sortOrder"], 10)

	def test_create_school_area_checks_create_permission_and_normalizes_code(self):
		doc = FakeDocument(
			name="KV5",
			code="KV5",
			display_name="Khu vực 5",
			enabled=1,
			sort_order=50,
			modified="2026-09-15 10:00:00",
		)
		with (
			patch.object(geography_catalog.frappe, "new_doc", return_value=doc),
			patch.object(geography_catalog.frappe.db, "exists", return_value=False),
		):
			created = geography_catalog.create_school_area({"code": " kv5 ", "display_name": " Khu vực 5 "})

		self.assertEqual(created["code"], "KV5")
		self.assertEqual(doc.values["code"], "KV5")
		self.assertEqual(doc.permission_calls, ["create"])
		self.assertEqual(doc.insert_calls, 1)

	def test_create_ward_accepts_province_without_zone(self):
		doc = FakeDocument(
			name="00001 - Tỉnh Test",
			ward_code="00001",
			ward_name="Xã Test",
			province="Tỉnh Test",
			ward_type="Commune",
			zone=None,
			modified="2026-09-16 10:00:00",
		)

		def exists(doctype, _value):
			return doctype == geography_catalog.PROVINCE

		with (
			patch.object(geography_catalog.frappe, "new_doc", return_value=doc),
			patch.object(geography_catalog.frappe.db, "exists", side_effect=exists),
			patch.object(geography_catalog.frappe.db, "get_value", return_value="Tỉnh Test"),
		):
			created = geography_catalog.create_ward(
				{
					"ward_code": "00001",
					"ward_name": "Xã Test",
					"ward_type": "Commune",
					"province": "Tỉnh Test",
				}
			)

		self.assertEqual(created["province"], "Tỉnh Test")
		self.assertIsNone(created["zone"])
		self.assertEqual(doc.permission_calls, ["create"])
		self.assertEqual(doc.insert_calls, 1)

	def test_update_province_keeps_identifiers_immutable(self):
		doc = FakeDocument(
			name="HCM",
			province_code="79",
			province_name="Thành phố Hồ Chí Minh",
			region="MN",
			city_type="Centrally Controlled City",
			modified="2026-09-15 10:00:00",
		)
		with patch.object(geography_catalog.frappe, "get_doc", return_value=doc):
			updated = geography_catalog.update_province(
				"HCM",
				{"city_type": "Province"},
				expected_modified="2026-09-15 10:00:00",
			)

		self.assertEqual(doc.values["city_type"], "Province")
		self.assertEqual(updated["code"], "79")
		self.assertEqual(doc.permission_calls, ["write"])
		self.assertEqual(doc.save_calls, 1)

		with patch.object(geography_catalog.frappe, "get_doc", return_value=doc):
			with self.assertRaises(frappe.PermissionError):
				geography_catalog.update_province("HCM", {"province_name": "Tên mới"})

	def test_guest_cannot_list_catalog(self):
		self.session.user = "Guest"
		with self.assertRaises(frappe.AuthenticationError):
			geography_catalog.list_provinces()
