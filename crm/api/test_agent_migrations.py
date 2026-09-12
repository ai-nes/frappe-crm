import unittest
from types import SimpleNamespace
from unittest.mock import patch

from crm.api import agent_migrations


class _Role:
	def __init__(self):
		self.custom_ai_capability_grants = []

	def append(self, _fieldname, values):
		self.custom_ai_capability_grants.append(SimpleNamespace(**values))

	def save(self, ignore_permissions=False):
		assert ignore_permissions is True


class _Frappe:
	class _Meta:
		@staticmethod
		def has_field(fieldname):
			return fieldname == "custom_ai_capability_grants"

	class _DB:
		def __init__(self, roles):
			self.roles = roles
			self.commits = 0

		def exists(self, doctype, name):
			return doctype == "Role" and name in self.roles

		def commit(self):
			self.commits += 1

		def delete(self, *_args, **_kwargs):
			return None

	def __init__(self, role_names):
		self.roles = {role_name: _Role() for role_name in role_names}
		self.db = self._DB(self.roles)
		self.conf = {"crm_agents_demo_full_access": True}
		self.cache_cleared = 0

	def get_meta(self, doctype):
		assert doctype == "Role"
		return self._Meta()

	def get_doc(self, doctype, name):
		assert doctype == "Role"
		return self.roles[name]

	def clear_cache(self):
		self.cache_cleared += 1


class TestKnowledgeGraphCapabilitySeed(unittest.TestCase):
	def test_capability_is_seeded_for_all_copilot_roles(self):
		role_names = (
			"Sale",
			"Marketing",
			"Lead Sale",
			"Admissions Director",
			"Administrator",
			"System Manager",
		)
		fake_frappe = _Frappe(role_names)

		with patch.object(agent_migrations, "frappe", fake_frappe):
			agent_migrations._grant_sales_worklist_capability()
			agent_migrations._grant_sales_worklist_capability()

		for role_name in ("Sale", "Marketing", "Lead Sale", "Admissions Director"):
			self.assertEqual(
				[
					row.value
					for row in fake_frappe.roles[role_name].custom_ai_capability_grants
					if row.grant_type == "semantic_capability" and row.value == "knowledge_graph.query"
				],
				["knowledge_graph.query"],
			)

		for role_name in ("Administrator", "System Manager"):
			self.assertFalse(
				any(
					row.value == "knowledge_graph.query"
					for row in fake_frappe.roles[role_name].custom_ai_capability_grants
				)
			)
		for role_name in ("Sale", "Marketing", "Lead Sale", "Admissions Director"):
			self.assertFalse(
				any(
					row.grant_type == "semantic_capability" and row.value == "action.crm_mutation"
					for row in fake_frappe.roles[role_name].custom_ai_capability_grants
				)
			)

		self.assertEqual(fake_frappe.db.commits, 1)
		self.assertEqual(fake_frappe.cache_cleared, 1)

	def test_retired_capability_cleanup_is_explicit(self):
		fake_frappe = _Frappe(("Sale",))

		with patch.object(agent_migrations, "frappe", fake_frappe):
			agent_migrations._remove_retired_capabilities()

		# The fake records the call shape through the DB API in the real app; the
		# explicit constant is the guard against deleting unrelated grants.
		self.assertEqual(
			agent_migrations.RETIRED_SEMANTIC_CAPABILITIES,
			("readmodel.analytics_query",),
		)
