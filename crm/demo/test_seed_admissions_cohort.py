from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.demo.seed_admissions_cohort import (
	ADMISSIONS_TASK_TEMPLATES,
	SCENARIOS,
	SLA_SHOWCASE_SCENARIOS,
	SIBLING_POOL_NAME,
	SIBLING_SALE_EMAIL,
	SIBLING_TEAM_NAME,
	SIBLING_TEAM_SCENARIO,
	_ensure_lead_workspace_actions,
	_sla_due_times,
)


class TestSeedAdmissionsCohortDefinition(FrappeTestCase):
	def test_cohort_covers_the_current_lifecycle_with_two_sale_cases(self):
		self.assertEqual({scenario["target_stage"] for scenario in SCENARIOS}, {"Lead", "MQL", "Applicant", "Enrolled", "Lost"})
		self.assertEqual(sum(scenario["owner"] for scenario in SCENARIOS), 2)

	def test_sla_cases_are_the_two_supervisable_sale_cases(self):
		owned = {scenario["key"] for scenario in SCENARIOS if scenario["owner"]}
		self.assertEqual(owned, {"gia-han", "minh-khang"})

	def test_detail_walkthrough_has_the_five_admissions_task_templates(self):
		self.assertEqual(
			[template["title"] for template in ADMISSIONS_TASK_TEMPLATES],
			["Gọi lần đầu", "Gửi thông tin học bổng", "Nhắc tham dự Campus Tour", "Gọi phụ huynh", "Follow-up hồ sơ"],
		)

	def test_sla_showcase_exposes_each_non_terminal_queue_with_stable_fixture_identity(self):
		self.assertEqual({scenario["sla_status"] for scenario in SLA_SHOWCASE_SCENARIOS}, {"open", "warned", "breached"})
		self.assertEqual(len({scenario["key"] for scenario in SLA_SHOWCASE_SCENARIOS}), 3)
		self.assertTrue(all(scenario["email"].endswith("@example.test") for scenario in SLA_SHOWCASE_SCENARIOS))

	def test_sla_due_times_progress_only_to_requested_state(self):
		attempt = SimpleNamespace(warning_at="warning", breach_at="breach", escalation_at="escalation")
		self.assertEqual(_sla_due_times(attempt, "open"), ())
		self.assertEqual(_sla_due_times(attempt, "warned"), ("warning",))
		self.assertEqual(_sla_due_times(attempt, "breached"), ("warning", "breach"))

	def test_lead_workspace_scope_fixture_has_distinct_sibling_team_identity(self):
		self.assertNotEqual(SIBLING_TEAM_NAME, SIBLING_POOL_NAME)
		self.assertNotEqual(SIBLING_SALE_EMAIL, "nguyen-minh-khoi.sale@example.test")
		self.assertEqual(SIBLING_TEAM_SCENARIO["sla_status"], "breached")
		self.assertTrue(SIBLING_TEAM_SCENARIO["email"].endswith("@example.test"))

	def test_lead_workspace_actions_reuse_existing_manual_action_before_replaying_command(self):
		staff_context = {"staff_by_user": {"nguyen-minh-khoi.sale@example.test": "CRM-STAFF-001"}}
		students = {"gia-han": "CRM-STUDENT-001", "minh-khang": "CRM-STUDENT-002"}
		with patch(
			"crm.demo.seed_admissions_cohort.frappe.db.get_value",
			side_effect=["CRM-ACTION-001", "CRM-ACTION-002"],
		):
			self.assertEqual(
				_ensure_lead_workspace_actions(students, staff_context),
				["CRM-ACTION-001", "CRM-ACTION-002"],
			)
