"""Focused schema-contract tests for Phase 4 policy and persistence DocTypes."""

import json
from pathlib import Path
from unittest import TestCase

from crm.patches.v1_0.phase4_prepare_student_routing_sla import classify_student_topology


DOCTYPE_ROOT = Path(__file__).parent


def load_schema(directory):
	with (DOCTYPE_ROOT / directory / f"{directory}.json").open(encoding="utf-8") as schema_file:
		return json.load(schema_file)


class TestStudentRoutingSLAContracts(TestCase):
	def test_operational_doctypes_default_deny_generic_permissions(self):
		for directory in (
			"crm_student_routing_policy",
			"crm_student_routing_request",
			"crm_student_sla_policy",
			"crm_student_sla_attempt",
			"crm_student_sla_event",
			"crm_student_sla_delivery",
			"crm_student_sla_delivery_attempt",
		):
			self.assertEqual(load_schema(directory)["permissions"], [])

	def test_idempotency_identities_are_database_unique(self):
		unique_fields = {
			"crm_student_routing_request": "request_key",
			"crm_student_sla_attempt": "opening_revision_key",
			"crm_student_sla_event": "idempotency_key",
			"crm_student_sla_delivery": "idempotency_key",
			"crm_student_sla_delivery_attempt": "provider_submission_key",
		}
		for directory, fieldname in unique_fields.items():
			fields = {field["fieldname"]: field for field in load_schema(directory)["fields"]}
			self.assertEqual(fields[fieldname].get("unique"), 1)
		attempt_fields = {field["fieldname"]: field for field in load_schema("crm_student_sla_delivery_attempt")["fields"]}
		self.assertIn("recipient", attempt_fields)
		self.assertIn("submitted", attempt_fields["outcome"]["options"])

	def test_policies_expose_only_approved_v1_strategies(self):
		routing = {field["fieldname"]: field for field in load_schema("crm_student_routing_policy")["fields"]}
		sla = {field["fieldname"]: field for field in load_schema("crm_student_sla_policy")["fields"]}
		self.assertEqual(routing["strategy"]["options"], "round_robin")
		self.assertEqual(sla["recipient_strategy"]["options"], "owner_warning_lead_breach_director_escalation")

	def test_reset_contract_is_explicit_and_auditable(self):
		fields = {field["fieldname"]: field for field in load_schema("crm_student_sla_attempt")["fields"]}
		for fieldname in ("reset_sequence", "reset_reason", "reset_evidence_reference", "reset_approved_by"):
			self.assertIn(fieldname, fields)
		events = {field["fieldname"]: field for field in load_schema("crm_student_sla_event")["fields"]}
		self.assertIn("reset_requested", events["event_type"]["options"])

	def test_worker_fencing_and_pause_expiry_are_persisted_contracts(self):
		delivery = {field["fieldname"]: field for field in load_schema("crm_student_sla_delivery")["fields"]}
		self.assertIn("delivering", delivery["status"]["options"])
		events = {field["fieldname"]: field for field in load_schema("crm_student_sla_event")["fields"]}
		self.assertIn("pause_expired", events["event_type"]["options"])

	def test_interactions_require_backend_verified_source_for_sla(self):
		fields = {field["fieldname"]: field for field in load_schema("crm_interaction")["fields"]}
		self.assertEqual(fields["source_verified"].get("read_only"), 1)

	def test_migration_classifier_never_treats_invalid_topology_as_clockable(self):
		self.assertEqual(classify_student_topology({"owner_staff": "STAFF-1"}), "owner")
		self.assertEqual(
			classify_student_topology(
				{"owning_team": "TEAM-1", "branch": "CAMPUS-1"},
				[{"name": "POOL-1", "team": "TEAM-1", "campus": "CAMPUS-1", "is_active": 1}],
			),
			"pool",
		)
		self.assertEqual(classify_student_topology({"owning_team": "TEAM-1"}), "pool_projection_unresolved")
		self.assertEqual(
			classify_student_topology(
				{"owning_team": "TEAM-1", "branch": "CAMPUS-1"},
				[],
			),
			"missing_pool",
		)
		self.assertEqual(
			classify_student_topology(
				{"owning_pool": "POOL-1", "owning_team": "TEAM-2", "branch": "CAMPUS-1"},
				[{"name": "POOL-1", "team": "TEAM-1", "campus": "CAMPUS-1", "is_active": 1}],
			),
			"invalid_pool_topology",
		)
		self.assertEqual(
			classify_student_topology({"owner_staff": "STAFF-1", "owning_team": "POOL-1"}),
			"dual_owner_pool",
		)
		self.assertEqual(classify_student_topology({"enrollment_status": "Lost"}), "terminal")
