import unittest
from types import SimpleNamespace
from unittest.mock import patch

from crm.patches.v1_0 import add_ai_capability_gateway_fields


class _Database:
	def __init__(self, has_column):
		self.has_custom_ai_exposed = has_column
		self.ddl = []

	def has_column(self, doctype, fieldname):
		assert (doctype, fieldname) == ("DocType", "custom_ai_exposed")
		return self.has_custom_ai_exposed

	def sql_ddl(self, statement):
		self.ddl.append(statement)


class TestAiCapabilityGatewaySchemaRepair(unittest.TestCase):
	def test_ensures_fields_column_and_exposure_seed(self):
		database = _Database(has_column=False)
		frappe = SimpleNamespace(db=database)

		with (
			patch.object(add_ai_capability_gateway_fields, "frappe", frappe),
			patch.object(add_ai_capability_gateway_fields, "create_custom_fields") as create_fields,
			patch.object(add_ai_capability_gateway_fields, "_seed_exposed_crm_doctypes") as seed,
		):
			add_ai_capability_gateway_fields.ensure_ai_capability_gateway_fields()

		create_fields.assert_called_once_with(
			add_ai_capability_gateway_fields.CUSTOM_FIELDS,
			ignore_validate=True,
			update=True,
		)
		self.assertEqual(len(database.ddl), 1)
		self.assertIn("ALTER TABLE `tabDocType` ADD COLUMN `custom_ai_exposed`", database.ddl[0])
		seed.assert_called_once_with()

	def test_does_not_recreate_existing_column(self):
		database = _Database(has_column=True)
		frappe = SimpleNamespace(db=database)

		with (
			patch.object(add_ai_capability_gateway_fields, "frappe", frappe),
			patch.object(add_ai_capability_gateway_fields, "create_custom_fields"),
			patch.object(add_ai_capability_gateway_fields, "_seed_exposed_crm_doctypes") as seed,
		):
			add_ai_capability_gateway_fields.ensure_ai_capability_gateway_fields()

		self.assertEqual(database.ddl, [])
		seed.assert_called_once_with()
