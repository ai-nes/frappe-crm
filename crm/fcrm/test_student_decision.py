"""Behavior tests for the V2-native decision command service (decide_student_task).

No test anywhere in this repo previously exercised decide_student_task or
decide_recommendation end-to-end -- this covers the accept/reject contract,
the CAS staleness fence, and the invariant that V2 decisions are audited only
via CRM Student Decision Event, never the legacy CRM Agent Event outbox.
"""

import hashlib
import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from crm.fcrm.student_decision import StudentDecisionError, decide_student_task
from crm.fcrm.test_permissions import TestSharedScopingPermissions


class TestDecideStudentTask(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = TestSharedScopingPermissions._make_campus(self, "_Test Decision Campus")
		self._department = TestSharedScopingPermissions._get_or_create_department(
			self, "_Test Decision Dept", self._campus
		)
		self._sale_user, self._sale_staff = TestSharedScopingPermissions._make_user_and_staff(
			self, "_Test Decision Sale", roles=["Sale"]
		)
		self._student = self._make_student("_Test Decision Student")

	def tearDown(self):
		frappe.set_user("Administrator")
		# CRM Student Decision Event is append-only (on_trash always throws) --
		# a raw delete is the only way to clean it up in a test.
		frappe.db.delete("CRM Student Decision Event", {"student": self._student.name})
		for name in frappe.db.get_all(
			"CRM Action", filters={"student": self._student.name}, pluck="name"
		):
			frappe.delete_doc("CRM Action", name, force=True)
		frappe.db.delete("CRM Student Command Receipt", {"target_student": self._student.name})
		frappe.delete_doc("CRM Student", self._student.name, force=True)
		frappe.delete_doc("CRM Staff", self._sale_staff, force=True)
		frappe.delete_doc("User", self._sale_user, force=True)
		frappe.delete_doc("CRM Department", self._department, force=True)
		frappe.delete_doc("CRM Campus", self._campus, force=True)

	def _make_student(self, name):
		phone = "0" + "".join(str((int(c, 16) + 1) % 10) for c in frappe.generate_hash(length=9))
		student = frappe.get_doc({"doctype": "CRM Student", "student_name": name, "phone": phone})
		previous_flag = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous_flag
		return student

	def _make_task(self, *, disposition="ACT", action_type="CALL", current_slot=None):
		task = frappe.get_doc(
			{
				"doctype": "CRM Action",
				"student": self._student.name,
				"origin": "ai",
				"current_slot": current_slot,
				"source_context_revision": 1,
				"disposition": disposition,
				"action_type": action_type if disposition == "ACT" else None,
				"objective": "Follow up on application status.",
				"policy_context_version": "test-v1",
				"generation_idempotency_key": frappe.generate_hash(length=20),
				"producer_identity": "test-suite",
				"payload_digest": frappe.generate_hash(length=32),
			}
		)
		task.insert(ignore_permissions=True)
		return task

	def _upsert_recommendation(self, *, revision, key, action_type="CALL"):
		"""Drive the real AI generation command for this test's student."""
		from crm.api import student_decision as api

		candidate = {
			"context_revision": revision,
			"disposition": "ACT",
			"action_type": action_type,
			"objective": "Call the family about the offer.",
			"policy_version": "test-v2",
		}
		digest = hashlib.sha256(
			json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()
		).hexdigest()
		# The fenced Intelligence Run writer path is inert unless the site pins a
		# writer epoch; this exercises the plain v2 generation command instead.
		conf = frappe._dict(frappe.conf)
		conf.pop("crm_intelligence_writer_epoch", None)
		conf.pop("crm_agents_v2_rollout_epoch", None)
		with patch("crm.api.student_decision._require_v2_service"), patch(
			"crm.api.student_decision.frappe.conf", conf
		):
			return api._upsert_crm_action(
				student=self._student.name,
				expected_context_revision=revision,
				generation_idempotency_key=key,
				producer_identity="crm-agents:v2",
				payload_digest=digest,
				rollout_epoch=0,
				candidate=candidate,
			)

	def test_rejecting_an_action_vacates_the_current_slot(self):
		task = self._make_task(current_slot="CURRENT")
		decide_student_task(
			task.name,
			expected_revision=0,
			status="rejected",
			idempotency_key=f"reject-slot-{task.name}",
			decision_reason="Student asked not to be contacted.",
		)
		task.reload()
		self.assertEqual(task.state, "rejected")
		self.assertIsNone(task.current_slot)

	def test_validate_auto_clears_the_slot_on_a_terminal_transition(self):
		# The controller must vacate the slot itself -- the caller does not set it.
		task = self._make_task(current_slot="CURRENT")
		task.reload()
		self.assertEqual(task.current_slot, "CURRENT")
		previous = getattr(frappe.flags, "crm_action_command", False)
		frappe.flags.crm_action_command = True
		try:
			task.state = "superseded"
			task.save(ignore_permissions=True)
		finally:
			frappe.flags.crm_action_command = previous
		task.reload()
		self.assertIsNone(task.current_slot)

	def test_unique_current_slot_index_blocks_a_second_current_action(self):
		index = frappe.db.sql(
			"SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() "
			"AND table_name = 'tabCRM Action' AND index_name = %s LIMIT 1",
			("crm_action_student_current_slot_uniq",),
		)
		self.assertTrue(index, "patch crm_action_current_slot_unique must have created the unique key")
		self._make_task(current_slot="CURRENT")
		with self.assertRaises(Exception):
			self._make_task(current_slot="CURRENT")

	def test_new_recommendation_after_completion_opens_a_fresh_action(self):
		base = int(
			frappe.db.get_value("CRM Student", self._student.name, "student_context_revision") or 0
		)
		first = self._upsert_recommendation(revision=base, key="gen-first")
		done = frappe.get_doc("CRM Action", first["action"])
		self.assertEqual(done.current_slot, "CURRENT")

		previous = getattr(frappe.flags, "crm_action_command", False)
		frappe.flags.crm_action_command = True
		try:
			for state in ("accepted", "in-progress", "completed"):
				done.state = state
				done.save(ignore_permissions=True)
		finally:
			frappe.flags.crm_action_command = previous
		done.reload()
		self.assertEqual(done.state, "completed")
		self.assertIsNone(done.current_slot)

		frappe.db.set_value(
			"CRM Student", self._student.name, "student_context_revision", base + 1, update_modified=False
		)
		second = self._upsert_recommendation(revision=base + 1, key="gen-second")
		self.assertNotEqual(second["action"], done.name)
		done.reload()
		self.assertEqual(done.state, "completed", "the completed Action must never be reopened")
		fresh = frappe.get_doc("CRM Action", second["action"])
		self.assertEqual(fresh.current_slot, "CURRENT")
		self.assertEqual(fresh.state, "pending")

	def test_accept_creates_canonical_action_and_decision_event(self):
		task = self._make_task()
		result = decide_student_task(
			task.name,
			expected_revision=0,
			status="accepted",
			idempotency_key=f"accept-{task.name}",
			due_at=now_datetime(),
			assignee_staff=self._sale_staff,
		)

		self.assertEqual(result["status"], "accepted")
		self.assertEqual(result["action"], task.name)

		task.reload()
		self.assertEqual(task.state, "accepted")
		self.assertEqual(task.decision_revision, 1)

		event = frappe.get_doc("CRM Student Decision Event", result["event"])
		self.assertEqual(event.action, task.name)
		self.assertIsNone(event.recommendation)
		self.assertEqual(event.event_type, "action_started")

	def test_accept_does_not_write_a_legacy_agent_event(self):
		task = self._make_task()
		before = set(frappe.db.get_all("CRM Agent Event", pluck="name"))

		decide_student_task(
			task.name,
			expected_revision=0,
			status="accepted",
			idempotency_key=f"accept-no-outbox-{task.name}",
			due_at=now_datetime(),
			assignee_staff=self._sale_staff,
		)

		after = set(frappe.db.get_all("CRM Agent Event", pluck="name"))
		self.assertEqual(after - before, set(), "V2 task decisions must never route through the legacy outbox")

	def test_stale_expected_revision_is_rejected(self):
		task = self._make_task()
		decide_student_task(
			task.name,
			expected_revision=0,
			status="accepted",
			idempotency_key=f"accept-first-{task.name}",
			due_at=now_datetime(),
			assignee_staff=self._sale_staff,
		)

		with self.assertRaises(StudentDecisionError) as ctx:
			decide_student_task(
				task.name,
				expected_revision=0,
				status="accepted",
				idempotency_key=f"accept-stale-{task.name}",
				due_at=now_datetime(),
				assignee_staff=self._sale_staff,
			)
		self.assertEqual(ctx.exception.code, "STALE_REVISION")

	def test_reject_requires_decision_reason(self):
		task = self._make_task()

		with self.assertRaises(StudentDecisionError) as ctx:
			decide_student_task(
				task.name,
				expected_revision=0,
				status="rejected",
				idempotency_key=f"reject-{task.name}",
			)
		self.assertEqual(ctx.exception.code, "INVALID_INPUT")

		result = decide_student_task(
			task.name,
			expected_revision=0,
			status="rejected",
			idempotency_key=f"reject-with-reason-{task.name}",
			decision_reason="Student is no longer reachable.",
		)
		self.assertEqual(result["status"], "rejected")
		task.reload()
		self.assertEqual(task.state, "rejected")

	def _upsert_bundle(self, *, revision, base_key, action_types, rationales=None, package_seeds=None):
		from crm.api import student_decision as api

		candidates = [
			{
				"context_revision": revision,
				"disposition": "ACT",
				"action_type": atype,
				"objective": f"Do a {atype} for the family.",
				"policy_version": "test-v2",
				"evidence_refs": ["ctx:1"],
			}
			for atype in action_types
		]
		for candidate, seed in zip(candidates, package_seeds or []):
			if seed is not None:
				candidate["package_seed"] = seed
		digest = hashlib.sha256(
			json.dumps(candidates, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()
		).hexdigest()
		conf = frappe._dict(frappe.conf)
		conf.pop("crm_intelligence_writer_epoch", None)
		conf.pop("crm_agents_v2_rollout_epoch", None)
		with patch("crm.api.student_decision._require_v2_service"), patch(
			"crm.api.student_decision.frappe.conf", conf
		):
			return api._upsert_crm_action_bundle(
				student=self._student.name,
				expected_context_revision=revision,
				base_idempotency_key=base_key,
				base_stage_key=base_key,
				producer_identity="crm-agents:intelligence-run",
				payload_digest=digest,
				rollout_epoch=0,
				writer_epoch=None,
				candidates=candidates,
				rationales=rationales,
			)

	def test_bundle_creates_three_distinct_ranked_actions(self):
		revision = int(
			frappe.db.get_value("CRM Student", self._student.name, "student_context_revision") or 0
		)
		result = self._upsert_bundle(
			revision=revision, base_key="nba:test:r", action_types=["PARENT_CONTACT", "CALL", "EMAIL"]
		)
		self.assertEqual(result["status"], "completed")
		rows = frappe.get_all(
			"CRM Action",
			filters={"student": self._student.name, "origin": "ai"},
			fields=["name", "plan_rank", "current_slot", "state", "action_type"],
			order_by="plan_rank asc",
		)
		self.assertEqual([r.plan_rank for r in rows], [1, 2, 3])
		self.assertEqual([r.action_type for r in rows], ["PARENT_CONTACT", "CALL", "EMAIL"])
		self.assertEqual(rows[0].current_slot, "CURRENT")
		self.assertEqual(rows[0].state, "pending")
		self.assertIsNone(rows[1].current_slot)
		self.assertEqual(rows[1].state, "deferred")
		self.assertIsNone(rows[2].current_slot)

	def test_bundle_folds_the_nba_rationale_into_the_package_without_shifting_the_digest(self):
		revision = int(
			frappe.db.get_value("CRM Student", self._student.name, "student_context_revision") or 0
		)
		result = self._upsert_bundle(
			revision=revision,
			base_key="nba:rationale:r",
			action_types=["CALL", "EMAIL"],
			rationales=[
				{
					"action_type": "CALL",
					"why_now": "Học viên im lặng 9 ngày sau khi hỏi về học phí.",
					"approach": "Gọi xác nhận vướng mắc và chốt mốc nộp hồ sơ.",
					"expected_outcome": "Học viên đồng ý một bước tiếp theo.",
					"evidence_ref_ids": ["ctx:1"],
					"rank": 1,
				}
			],
		)
		self.assertEqual(result["status"], "completed")
		call_row = frappe.get_all(
			"CRM Action",
			filters={"student": self._student.name, "action_type": "CALL", "origin": "ai"},
			fields=["package_seed"],
		)[0]
		seed = json.loads(call_row.package_seed)
		self.assertEqual(
			seed["rationale"]["why_now"], "Học viên im lặng 9 ngày sau khi hỏi về học phí."
		)
		self.assertEqual(seed["rationale"]["evidence_ref_ids"], ["ctx:1"])
		email_row = frappe.get_all(
			"CRM Action",
			filters={"student": self._student.name, "action_type": "EMAIL", "origin": "ai"},
			fields=["package_seed"],
		)[0]
		self.assertNotIn("rationale", json.loads(email_row.package_seed))

	def test_bundle_replay_is_idempotent(self):
		revision = int(
			frappe.db.get_value("CRM Student", self._student.name, "student_context_revision") or 0
		)
		self._upsert_bundle(revision=revision, base_key="nba:replay:r", action_types=["CALL", "EMAIL"])
		second = self._upsert_bundle(
			revision=revision, base_key="nba:replay:r", action_types=["CALL", "EMAIL"]
		)
		self.assertTrue(second["idempotent"])
		count = frappe.db.count("CRM Action", {"student": self._student.name, "origin": "ai"})
		self.assertEqual(count, 2)

	def test_bundle_rejects_duplicate_action_types(self):
		revision = int(
			frappe.db.get_value("CRM Student", self._student.name, "student_context_revision") or 0
		)
		with self.assertRaises(frappe.ValidationError):
			self._upsert_bundle(
				revision=revision, base_key="nba:dupe:r", action_types=["CALL", "CALL"]
			)

	def test_bundle_defaults_action_owner_to_the_student_owner_staff(self):
		frappe.db.set_value(
			"CRM Student", self._student.name, "owner_staff", self._sale_staff, update_modified=False
		)
		revision = int(
			frappe.db.get_value("CRM Student", self._student.name, "student_context_revision") or 0
		)
		self._upsert_bundle(
			revision=revision, base_key="nba:owner:r", action_types=["CALL", "EMAIL", "MESSAGE"]
		)
		owners = frappe.get_all(
			"CRM Action",
			filters={"student": self._student.name, "origin": "ai"},
			pluck="action_owner",
		)
		self.assertTrue(owners)
		self.assertTrue(all(owner == self._sale_staff for owner in owners))

	def test_bundle_leaves_action_owner_unset_when_the_student_has_no_owner_staff(self):
		revision = int(
			frappe.db.get_value("CRM Student", self._student.name, "student_context_revision") or 0
		)
		self._upsert_bundle(
			revision=revision, base_key="nba:noowner:r", action_types=["CALL", "EMAIL"]
		)
		owners = frappe.get_all(
			"CRM Action",
			filters={"student": self._student.name, "origin": "ai"},
			pluck="action_owner",
		)
		self.assertTrue(all(not owner for owner in owners))

	def test_idempotent_bundle_replay_does_not_overwrite_a_reassigned_owner(self):
		frappe.db.set_value(
			"CRM Student", self._student.name, "owner_staff", self._sale_staff, update_modified=False
		)
		revision = int(
			frappe.db.get_value("CRM Student", self._student.name, "student_context_revision") or 0
		)
		self._upsert_bundle(
			revision=revision, base_key="nba:reassign:r", action_types=["CALL", "EMAIL"]
		)
		rank1 = frappe.get_all(
			"CRM Action",
			filters={"student": self._student.name, "origin": "ai", "plan_rank": 1},
			pluck="name",
		)[0]
		frappe.db.set_value("CRM Action", rank1, "action_owner", None, update_modified=False)
		self._upsert_bundle(
			revision=revision, base_key="nba:reassign:r", action_types=["CALL", "EMAIL"]
		)
		self.assertIsNone(frappe.db.get_value("CRM Action", rank1, "action_owner"))

	def test_validate_package_seed_logs_drift_but_never_rejects(self):
		from crm.api import student_decision as api

		with patch.object(api.frappe, "logger") as logger:
			api._validate_package_seed(
				{"package_version": "action-package:v2", "objective": "x", "surprise_key": 1},
				"CALL",
			)
			logger.return_value.warning.assert_called_once()
			logger.reset_mock()
			# a well-formed CALL package logs nothing
			api._validate_package_seed(
				{"package_version": "action-package:v2", "objective": "x", "talking_points": []},
				"CALL",
			)
			logger.return_value.warning.assert_not_called()

	def test_package_field_sets_mirror_the_published_contract_table(self):
		from crm.api.student_decision import _PACKAGE_FIELD_SETS

		# Byte-identical to tests/unit/test_action_packages.py::_EXPECTED_TYPE_FIELDS
		# in crm-agents — a drift on either side fails a test, not silently.
		expected = {
			"CALL": {"opening", "talking_points", "questions", "objections", "desired_outcome", "next_step"},
			"EMAIL": {
				"template_version", "recipient_ref", "subject", "body", "talking_points", "questions", "cta", "next_step"
			},
			"MESSAGE": {"channel", "opening", "key_points", "cta", "next_step"},
			"COUNSELING": {"topic", "agenda", "guidance_points", "concerns_to_address", "desired_outcome"},
			"MEETING": {"purpose", "agenda", "attendees_hint", "prep_checklist", "desired_outcome"},
			"EVENT_INVITE": {"event_ref", "why_relevant", "invite_message", "follow_up_step"},
			"CAMPUS_VISIT": {"visit_goal", "itinerary_points", "logistics_notes", "who_to_involve", "desired_outcome"},
			"DOCUMENT_REQUEST": {
				"missing_documents", "deadline", "request_message", "consequence_if_missing", "follow_up_step"
			},
			"APPLICATION_SUPPORT": {"blocking_steps", "support_actions", "deadline", "desired_outcome"},
			"PARENT_CONTACT": {
				"parent_ref", "reason", "talking_points", "sensitivities", "desired_outcome", "next_step"
			},
			"HANDOFF": {"to_role", "reason", "context_summary", "open_items", "expected_response_time"},
		}
		self.assertEqual({k: set(v) for k, v in _PACKAGE_FIELD_SETS.items()}, expected)

	def test_bundle_with_a_typed_document_request_package_persists_and_validates(self):
		from crm.api import student_decision as api

		revision = int(
			frappe.db.get_value("CRM Student", self._student.name, "student_context_revision") or 0
		)
		seed = {
			"package_version": "action-package:v2",
			"objective": "Yêu cầu học viên bổ sung giấy tờ còn thiếu.",
			"missing_documents": ["Học bạ THPT", "Giấy khai sinh"],
			"deadline": "Còn khoảng 3 ngày đến hạn nộp.",
			"request_message": "Hồ sơ của bạn còn thiếu một số giấy tờ bắt buộc.",
			"consequence_if_missing": "Thiếu giấy tờ quá hạn có thể khiến hồ sơ bị tạm dừng.",
			"follow_up_step": "Kiểm tra lại sau 2 ngày.",
		}
		with patch.object(api.frappe, "logger") as logger:
			result = self._upsert_bundle(
				revision=revision,
				base_key="nba:typed:r",
				action_types=["DOCUMENT_REQUEST", "CALL"],
				package_seeds=[seed, None],
			)
			# a contract-clean typed package logs no drift
			logger.return_value.warning.assert_not_called()
		self.assertEqual(result["status"], "completed")
		row = frappe.get_all(
			"CRM Action",
			filters={"student": self._student.name, "action_type": "DOCUMENT_REQUEST", "origin": "ai"},
			fields=["package_seed"],
		)[0]
		self.assertEqual(json.loads(row.package_seed)["missing_documents"], ["Học bạ THPT", "Giấy khai sinh"])

	def test_replaying_the_same_idempotency_key_returns_the_original_result(self):
		task = self._make_task()
		key = f"accept-replay-{task.name}"
		due_at = now_datetime()
		first = decide_student_task(
			task.name,
			expected_revision=0,
			status="accepted",
			idempotency_key=key,
			due_at=due_at,
			assignee_staff=self._sale_staff,
		)

		second = decide_student_task(
			task.name,
			expected_revision=0,
			status="accepted",
			idempotency_key=key,
			due_at=due_at,
			assignee_staff=self._sale_staff,
		)
		self.assertTrue(second["replayed"])
		self.assertEqual(second["action"], first["action"])
