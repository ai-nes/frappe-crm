from types import SimpleNamespace
from unittest.mock import Mock, patch

from frappe.tests.utils import FrappeTestCase

from crm.services import action_execution


class TestActionExecution(FrappeTestCase):
	def test_send_authorization_revalidates_the_same_channel_override(self):
		attempt = action_execution.frappe._dict(
			status="queued",
			name="ATTEMPT-1",
			action="ACT-1",
			actor="sale@example.test",
			operation="DISPATCH",
			action_revision=1,
			package_revision=0,
			nba_execution=None,
			provider_idempotency_key="key",
			lease_count=0,
		)
		attempt.save = Mock()
		action = action_execution.frappe._dict(
			name="ACT-1",
			student="STU-1",
			contact="CON-1",
			state="accepted",
			action_revision=1,
			execution_package_version=0,
		)
		action.has_permission = Mock(return_value=True)

		with patch.object(action_execution.frappe, "get_doc", side_effect=[attempt, action]), patch.object(
			action_execution, "validate_nba_action_execution", return_value=None
		), patch.object(action_execution.frappe.db, "get_value", return_value=None), patch.object(
			action_execution, "resolve_nba_channel", return_value="EMAIL"
		), patch(
			"crm.services.outreach_consent.current_outreach_consent_allows", return_value=True
		) as consent:
			result = action_execution.authorize_attempt_for_send("ATTEMPT-1", channel="EMAIL")

		self.assertEqual(result["status"], "authorized")
		consent.assert_called_once_with(student="STU-1", action_contact="CON-1", channel="EMAIL")

	def test_process_queued_attempt_rejects_channel_override(self):
		attempt = SimpleNamespace(action="ACT-1")
		action = action_execution.frappe._dict(name="ACT-1", student="STU-1", contact="CON-1")
		with patch.object(action_execution.frappe, "get_doc", side_effect=[attempt, action]), patch.object(
			action_execution, "resolve_nba_channel", return_value="CALL"
		):
			with self.assertRaises(action_execution.frappe.PermissionError):
				action_execution.process_queued_attempt("ATTEMPT-1", channel="EMAIL")
