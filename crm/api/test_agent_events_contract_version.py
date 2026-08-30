"""Contract-version checks reject incompatible payloads before delivery."""

from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api.agent_events import _check_agent_contract_version


class TestAgentEventContractVersion(FrappeTestCase):
    def test_known_matching_version_is_accepted(self):
        event = SimpleNamespace(event_type="student.context_changed.v2", contract_version=2, name="E-1")

        with patch("crm.api.agent_events._fetch_agent_contract_manifest", return_value=None):
            self.assertTrue(_check_agent_contract_version(event))

    def test_known_mismatch_is_logged_without_raising(self):
        event = SimpleNamespace(event_type="student.context_changed.v2", contract_version=3, name="E-2")
        with patch("frappe.logger") as logger_factory, patch(
            "crm.api.agent_events._fetch_agent_contract_manifest", return_value=None
        ):
            self.assertFalse(_check_agent_contract_version(event))

        logger_factory.return_value.warning.assert_called_once()

    def test_producer_manifest_is_preferred_when_available(self):
        event = SimpleNamespace(event_type="student.context_changed.v2", contract_version=3, name="E-3")
        manifest = {
            "events": [
                {"event_type": "student.context_changed.v2", "contract_version": 3},
            ],
        }
        with patch("crm.api.agent_events._fetch_agent_contract_manifest", return_value=manifest):
            self.assertTrue(_check_agent_contract_version(event))

    def test_event_missing_from_producer_manifest_is_rejected(self):
        event = SimpleNamespace(event_type="student.score_input_changed.v1", contract_version=1, name="E-4")
        with patch("frappe.logger") as logger_factory:
            with patch("crm.api.agent_events._fetch_agent_contract_manifest", return_value={"events": []}):
                self.assertFalse(_check_agent_contract_version(event))

        logger_factory.return_value.warning.assert_called_once()
