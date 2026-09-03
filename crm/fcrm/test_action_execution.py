import unittest

from crm.services.action_execution_contract import TERMINAL, TRANSITIONS, fingerprint
from crm.services.action_provider import register_provider, send


class TestActionExecutionContract(unittest.TestCase):
	def test_attempt_transitions_are_monotonic(self):
		self.assertEqual(TRANSITIONS["pending"], {"queued", "cancelled"})
		self.assertEqual(TRANSITIONS["confirmed"], set())
		self.assertIn("failed", TERMINAL)

	def test_fingerprint_is_deterministic_and_revision_bound(self):
		one = fingerprint("ACT-1", "DISPATCH", "user@example.com", 2, 4)
		self.assertEqual(one, fingerprint("ACT-1", "DISPATCH", "user@example.com", 2, 4))
		self.assertNotEqual(one, fingerprint("ACT-1", "DISPATCH", "user@example.com", 3, 4))

	def test_provider_is_explicitly_registered(self):
		register_provider("EMAIL", lambda key, attempt: "provider-event-1")
		self.assertEqual(send("EMAIL", "provider-key", "ATT-1"), "provider-event-1")
