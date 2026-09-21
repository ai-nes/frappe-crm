from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from crm.api import admin_catalog


class TestAdminCatalog(TestCase):
	def setUp(self):
		self.session = SimpleNamespace(user="Administrator")
		self.session_patch = patch.object(admin_catalog.frappe, "session", self.session)
		self.session_patch.start()

	def tearDown(self):
		self.session_patch.stop()

	def test_list_score_signals_supports_search_and_active_only_filter(self):
		rows = [
			{
				"name": "GRADE_12_GPA",
				"signal_key": "GRADE_12_GPA",
				"label": "Điểm TB lớp 12",
				"category": "Fit",
				"signal_type": "property",
				"is_active": 1,
				"description": "Điểm trung bình lớp 12",
			}
		]
		with patch.object(
			admin_catalog,
			"paged_list",
			return_value={"rows": rows, "total": 1, "start": 0, "page_length": 25},
		) as paged:
			result = admin_catalog.list_score_signals(
				search=" gpa ", active_only="true", start="0", page_length="25"
			)

		self.assertEqual(result["signals"][0]["signal_key"], "GRADE_12_GPA")
		self.assertEqual(result["total"], 1)
		self.assertEqual(paged.call_args.kwargs["filters"], {"is_active": 1})
		self.assertEqual(
			paged.call_args.kwargs["or_filters"],
			[
				["name", "like", "%gpa%"],
				["signal_key", "like", "%gpa%"],
				["label", "like", "%gpa%"],
				["category", "like", "%gpa%"],
				["signal_type", "like", "%gpa%"],
			],
		)
