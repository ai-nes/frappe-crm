from unittest import TestCase

import frappe

from crm.fcrm import lead_assignment_workflow as workflow


class TestLeadAssignmentWorkflowConfig(TestCase):
	def test_legacy_values_are_normalized_with_safe_defaults(self):
		config = workflow.get_lead_assignment_workflow_config(
			{
				"lead_assignment_workflow_config": '{"input":{"scheduledMinAgeMinutes":"9"}}',
				"lead_workflow_revision": "4",
			}
		)

		self.assertEqual(config["version"], "lead-assignment-workflow-v4")
		self.assertEqual(config["stored"]["input"]["scheduledMinAgeMinutes"], 9)
		self.assertEqual(config["stored"]["input"]["maxLeadsPerRun"], 1000)
		self.assertTrue(config["stored"]["classification"]["enabled"])
		self.assertEqual(config["stored"]["review"]["maxRetries"], 3)

	def test_only_input_and_classification_can_toggle(self):
		self.assertTrue(workflow.step_snapshot(workflow.get_lead_assignment_workflow_config({}), "input")["canToggle"])
		self.assertTrue(
			workflow.step_snapshot(
				workflow.get_lead_assignment_workflow_config({}), "classification"
			)["canToggle"]
		)
		for step_id in ("validation", "matching", "review", "assignment"):
			snapshot = workflow.step_snapshot(workflow.get_lead_assignment_workflow_config({}), step_id)
			self.assertFalse(snapshot["canToggle"])
			self.assertTrue(snapshot["enabled"])

	def test_validation_matching_and_assignment_reject_settings(self):
		for step_id in ("validation", "matching", "assignment"):
			with self.assertRaises(frappe.ValidationError):
				workflow.validate_step_update(step_id, {"enabled": False})

	def test_review_keeps_manual_retry_and_normalizes_limit(self):
		settings = workflow.validate_step_update("review", {"maxRetries": 999})
		self.assertEqual(settings, {"maxRetries": workflow.MAX_RETRIES})
		self.assertEqual(
			workflow.step_snapshot(
				workflow.get_lead_assignment_workflow_config({}), "review"
			)["settings"]["retryMode"],
			"manual",
		)
