"""Care-queue behavior: risk tier policy, the claim path, and the queue reader.

Covers the invariants that the tier is a Frappe-owned function a client cannot
lower, that a claim locks the Student row / rejects takeover / resolves a rotated
or contended claim to exactly one winner, and that the queue read-model never
leaks an out-of-scope Student.
"""

import hashlib
import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

# Import the module, not the class name -- binding the TestCase into this
# module's namespace would make the loader re-run its suite here.
import crm.fcrm.test_permissions as _perm
from crm.api import student_decision as decision_api
from crm.api import student_worklist
from crm.fcrm.student_decision import (
	RISK_TIER_POLICY,
	StudentDecisionError,
	claim_current_action,
	compute_risk_tier,
	decide_student_task,
	max_risk_tier,
	sensitive_content_flags,
)

_ACT_TYPES = sorted(RISK_TIER_POLICY)


class TestCareQueue(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._campus = _perm.TestSharedScopingPermissions._make_campus(self, "_Test Queue Campus")
		self._department = _perm.TestSharedScopingPermissions._get_or_create_department(
			self, "_Test Queue Dept", self._campus
		)
		self._team = _perm.TestSharedScopingPermissions._make_team(self, "_Test Queue Team", self._campus)
		self._sale_user, self._sale_staff = _perm.TestSharedScopingPermissions._make_user_and_staff(
			self, "_Test Queue Sale", roles=["Sale"], team=self._team
		)
		self._lead_user, self._lead_staff = _perm.TestSharedScopingPermissions._make_user_and_staff(
			self, "_Test Queue Lead", roles=["Lead Sale"], team=self._team, function="Lead Sale"
		)
		self._outsider_user, self._outsider_staff = _perm.TestSharedScopingPermissions._make_user_and_staff(
			self, "_Test Queue Outsider", roles=["Sale"]
		)
		self._student = self._make_student("_Test Queue Student")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("CRM Student Decision Event", {"student": self._student.name})
		for name in frappe.db.get_all(
			"CRM Action Item", filters={"student": self._student.name}, pluck="name"
		):
			frappe.delete_doc("CRM Action Item", name, force=True)
		frappe.db.delete("CRM Student Command Receipt", {"target_student": self._student.name})
		frappe.delete_doc("CRM Lead", self._student.name, force=True)
		for staff in (self._sale_staff, self._lead_staff, self._outsider_staff):
			frappe.delete_doc("CRM Staff", staff, force=True)
		for user in (self._sale_user, self._lead_user, self._outsider_user):
			frappe.delete_doc("User", user, force=True)
		frappe.delete_doc("CRM Team", self._team, force=True)
		frappe.delete_doc("CRM Department", self._department, force=True)
		frappe.delete_doc("CRM Campus", self._campus, force=True)

	# ---- fixtures ------------------------------------------------------

	def _make_student(self, name):
		phone = "0" + "".join(str((int(c, 16) + 1) % 10) for c in frappe.generate_hash(length=9))
		student = frappe.get_doc({"doctype": "CRM Lead", "student_name": name, "phone": phone})
		previous = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous
		return student

	def _make_action(
		self, *, action_type="CALL", disposition="ACT", current_slot="CURRENT", package_seed=None, state=None
	):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Action Item",
				"student": self._student.name,
				"origin": "ai",
				"current_slot": current_slot,
				"source_context_revision": 0,
				"disposition": disposition,
				"action_type": action_type if disposition == "ACT" else None,
				"objective": "Follow up on application status.",
				"policy_context_version": "test-v1",
				"generation_idempotency_key": frappe.generate_hash(length=20),
				"producer_identity": "test-suite",
				"payload_digest": frappe.generate_hash(length=32),
				"package_seed": json.dumps(package_seed) if package_seed is not None else None,
			}
		)
		doc.insert(ignore_permissions=True)
		if state:
			self._command_save(doc, state=state)
		return doc

	@staticmethod
	def _command_save(doc, **fields):
		previous = getattr(frappe.flags, "crm_action_command", False)
		frappe.flags.crm_action_command = True
		try:
			for key, value in fields.items():
				setattr(doc, key, value)
			doc.save(ignore_permissions=True)
		finally:
			frappe.flags.crm_action_command = previous

	def _generate(self, *, revision, key, action_type="CALL"):
		candidate = {
			"context_revision": revision,
			"disposition": "ACT",
			"action_type": action_type,
			"objective": "Call the family about the offer.",
			"policy_version": "test-v2",
		}
		digest = hashlib.sha256(
			json.dumps(
				candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
			).encode()
		).hexdigest()
		conf = frappe._dict(frappe.conf)
		conf.pop("crm_intelligence_writer_epoch", None)
		conf.pop("crm_agents_v2_rollout_epoch", None)
		with (
			patch("crm.api.student_decision._require_action_writer"),
			patch("crm.api.student_decision.frappe.conf", conf),
		):
			return decision_api.write_canonical_action(
				student=self._student.name,
				expected_context_revision=revision,
				generation_idempotency_key=key,
				producer_identity="crm-agents:v2",
				payload_digest=digest,
				rollout_epoch=0,
				candidate=candidate,
			)

	def _set_student(self, **fields):
		frappe.db.set_value("CRM Lead", self._student.name, fields, update_modified=False)

	def _context_base(self):
		return int(frappe.db.get_value("CRM Lead", self._student.name, "student_context_revision") or 0)

	def _current_revision(self, action):
		return int(frappe.db.get_value("CRM Action Item", action, "decision_revision") or 0)

	# ---- risk tier ----------------------------------------------------

	def test_every_action_type_records_its_policy_tier(self):
		for action_type in _ACT_TYPES:
			with self.subTest(action_type=action_type):
				doc = self._make_action(action_type=action_type, current_slot=None)
				self.assertEqual(doc.risk_tier, RISK_TIER_POLICY[action_type])
		self.assertEqual(RISK_TIER_POLICY["CALL"], "low")

	def test_unknown_or_missing_action_type_fails_closed_to_high(self):
		self.assertEqual(compute_risk_tier(None, None), "high")
		self.assertEqual(compute_risk_tier("NOT_A_REAL_TYPE", None), "high")

	def test_max_risk_tier_is_monotonic_on_low_mid_high(self):
		self.assertEqual(max_risk_tier("low", "mid"), "mid")
		self.assertEqual(max_risk_tier("high", "low"), "high")
		self.assertEqual(max_risk_tier("mid", "mid"), "mid")
		self.assertEqual(max_risk_tier("low", None), "high")

	def test_package_seed_cannot_raise_or_lower_the_frappe_policy_tier(self):
		self.assertEqual(sensitive_content_flags("CALL", {"mentions_scholarship": True}), [])
		doc = self._make_action(
			action_type="CALL", current_slot=None, package_seed={"mentions_scholarship": True}
		)
		self.assertEqual(doc.risk_tier, "low")
		self.assertEqual(sensitive_content_flags("PARENT_CONTACT", {}), ["direct_to_applicant_or_parent"])

	def test_free_text_seed_content_does_not_change_the_tier(self):
		doc = self._make_action(
			action_type="CALL",
			current_slot=None,
			package_seed={"talking_points": ["scholarship", "tuition", "change enrollment status"]},
		)
		self.assertEqual(doc.risk_tier, "low")

	def test_tier_cannot_be_lowered_by_editing_the_protected_seed(self):
		doc = self._make_action(
			action_type="CALL", current_slot=None, package_seed={"mentions_tuition": True}
		)
		self.assertEqual(doc.risk_tier, "low")
		doc.package_seed = json.dumps({})
		with self.assertRaises(frappe.PermissionError):
			doc.save(ignore_permissions=True)
		doc.reload()
		self.assertEqual(doc.risk_tier, "low")

	def test_legitimate_seed_edit_under_command_recomputes_the_tier(self):
		doc = self._make_action(
			action_type="CALL", current_slot=None, package_seed={"mentions_tuition": True}
		)
		self._command_save(doc, package_seed=json.dumps({"opening": "Hello"}))
		doc.reload()
		self.assertEqual(doc.risk_tier, "low")

	def test_recompute_on_action_type_change(self):
		doc = self._make_action(action_type="CALL", current_slot=None)
		self.assertEqual(doc.risk_tier, "low")
		self._command_save(doc, action_type="APPLICATION_SUPPORT")
		doc.reload()
		self.assertEqual(doc.risk_tier, "high")

	# ---- claim ------------------------------------------------------

	def test_claim_sets_owner_bumps_revisions_and_writes_an_event(self):
		self._set_student(assigned_to=self._sale_staff, owner_staff=self._sale_staff)
		action = self._make_action()
		frappe.set_user(self._sale_user)
		result = claim_current_action(
			self._student.name,
			expected_revision=0,
			idempotency_key="claim-1",
			expected_action=action.name,
		)
		self.assertEqual(result["status"], "claimed")
		self.assertTrue(frappe.db.exists("CRM Student Decision Event", result["event"]))
		action.reload()
		self.assertEqual(action.action_owner, self._sale_staff)
		self.assertEqual(action.decision_revision, 1)
		self.assertEqual(action.action_revision, 2)

	def test_claim_replays_the_same_idempotency_key(self):
		self._set_student(assigned_to=self._sale_staff, owner_staff=self._sale_staff)
		action = self._make_action()
		frappe.set_user(self._sale_user)
		key = "claim-replay"
		first = claim_current_action(
			self._student.name, expected_revision=0, idempotency_key=key, expected_action=action.name
		)
		second = claim_current_action(
			self._student.name, expected_revision=0, idempotency_key=key, expected_action=action.name
		)
		self.assertTrue(second["replayed"])
		self.assertEqual(second["action"], first["action"])
		action.reload()
		self.assertEqual(action.decision_revision, 1, "a replay must not bump the revision again")

	def test_claim_widens_assigned_to_when_the_student_is_unassigned(self):
		self._set_student(owning_team=self._team)
		action = self._make_action()
		frappe.set_user(self._lead_user)
		result = claim_current_action(
			self._student.name,
			expected_revision=0,
			idempotency_key="claim-widen",
			expected_action=action.name,
		)
		self.assertEqual(result["status"], "claimed")
		row = frappe.db.get_value(
			"CRM Lead", self._student.name, ["assigned_to", "owner_staff", "owning_team"], as_dict=True
		)
		self.assertEqual(row.assigned_to, self._lead_staff)
		self.assertIsNone(row.owner_staff)
		self.assertEqual(row.owning_team, self._team)

	def test_claim_then_decide_accept_succeeds(self):
		self._set_student(owning_team=self._team)
		action = self._make_action()
		frappe.set_user(self._lead_user)
		claim_current_action(
			self._student.name,
			expected_revision=0,
			idempotency_key="claim-then-accept",
			expected_action=action.name,
		)
		result = decide_student_task(
			action.name,
			expected_revision=self._current_revision(action.name),
			status="accepted",
			idempotency_key="accept-after-claim",
			due_at=now_datetime(),
			assignee_staff=self._lead_staff,
		)
		self.assertEqual(result["status"], "accepted")
		action.reload()
		self.assertEqual(action.state, "accepted")

	def test_two_users_claim_the_same_action_one_wins(self):
		self._set_student(assigned_to=self._sale_staff, owner_staff=self._sale_staff, owning_team=self._team)
		action = self._make_action()

		frappe.set_user(self._sale_user)
		first = claim_current_action(
			self._student.name, expected_revision=0, idempotency_key="race-a", expected_action=action.name
		)
		frappe.set_user(self._lead_user)
		second = claim_current_action(
			self._student.name, expected_revision=0, idempotency_key="race-b", expected_action=action.name
		)

		outcomes = sorted([first["status"], second["status"]])
		self.assertEqual(outcomes, ["claimed", "stale_revision"])
		action.reload()
		self.assertEqual(action.action_owner, self._sale_staff)

	def test_claim_on_an_action_owned_by_another_user_is_rejected(self):
		self._set_student(assigned_to=self._sale_staff, owner_staff=self._sale_staff, owning_team=self._team)
		action = self._make_action()

		frappe.set_user(self._sale_user)
		claim_current_action(
			self._student.name, expected_revision=0, idempotency_key="own-a", expected_action=action.name
		)
		frappe.set_user(self._lead_user)
		result = claim_current_action(
			self._student.name,
			expected_revision=self._current_revision(action.name),
			idempotency_key="own-b",
			expected_action=action.name,
		)
		self.assertEqual(result["code"], "ALREADY_CLAIMED")
		self.assertEqual(result["assignee_ref"], self._sale_staff)
		action.reload()
		self.assertEqual(action.action_owner, self._sale_staff)

	def test_reclaim_by_the_same_owner_is_allowed(self):
		self._set_student(assigned_to=self._sale_staff, owner_staff=self._sale_staff)
		action = self._make_action()
		frappe.set_user(self._sale_user)
		claim_current_action(
			self._student.name, expected_revision=0, idempotency_key="re-a", expected_action=action.name
		)
		again = claim_current_action(
			self._student.name,
			expected_revision=self._current_revision(action.name),
			idempotency_key="re-b",
			expected_action=action.name,
		)
		self.assertEqual(again["status"], "claimed")

	def test_claim_after_supersede_returns_stale_with_the_new_current_action(self):
		self._set_student(assigned_to=self._sale_staff, owner_staff=self._sale_staff)
		base = self._context_base()
		first = self._generate(revision=base, key="gen-a")
		self._set_student(student_context_revision=base + 1)
		second = self._generate(revision=base + 1, key="gen-b")
		self.assertNotEqual(first["action"], second["action"])

		frappe.set_user(self._sale_user)
		result = claim_current_action(
			self._student.name,
			expected_revision=0,
			idempotency_key="claim-rotated",
			expected_action=first["action"],
		)
		self.assertEqual(result["code"], "STALE_REVISION")
		self.assertEqual(result["current_action"]["name"], second["action"])
		self.assertIsNone(frappe.get_doc("CRM Action Item", first["action"]).current_slot)
		self.assertEqual(
			frappe.db.count("CRM Action Item", {"student": self._student.name, "current_slot": "CURRENT"}), 1
		)

	def test_claim_then_regeneration_keeps_exactly_one_current_action(self):
		self._set_student(assigned_to=self._sale_staff, owner_staff=self._sale_staff)
		base = self._context_base()
		first = self._generate(revision=base, key="gen-x")
		frappe.set_user(self._sale_user)
		claim_current_action(
			self._student.name,
			expected_revision=0,
			idempotency_key="claim-then-regen",
			expected_action=first["action"],
		)
		frappe.set_user("Administrator")
		self._set_student(student_context_revision=base + 1)
		second = self._generate(revision=base + 1, key="gen-y")
		self.assertEqual(
			frappe.db.count("CRM Action Item", {"student": self._student.name, "current_slot": "CURRENT"}), 1
		)
		self.assertTrue(frappe.db.exists("CRM Action Item", first["action"]))
		self.assertEqual(frappe.db.get_value("CRM Action Item", second["action"], "current_slot"), "CURRENT")

	def test_out_of_scope_caller_is_rejected_and_not_added_to_assigned_to(self):
		self._set_student(assigned_to=self._sale_staff, owner_staff=self._sale_staff)
		action = self._make_action()
		frappe.set_user(self._outsider_user)
		with self.assertRaises(StudentDecisionError) as ctx:
			claim_current_action(
				self._student.name,
				expected_revision=0,
				idempotency_key="claim-oos",
				expected_action=action.name,
			)
		self.assertEqual(ctx.exception.code, "OUT_OF_SCOPE")
		self.assertEqual(
			frappe.db.get_value("CRM Lead", self._student.name, "assigned_to"), self._sale_staff
		)

	def test_no_current_action_claims_as_stale(self):
		self._set_student(assigned_to=self._sale_staff, owner_staff=self._sale_staff)
		frappe.set_user(self._sale_user)
		result = claim_current_action(
			self._student.name,
			expected_revision=0,
			idempotency_key="claim-empty",
			expected_action="ACT-does-not-exist",
		)
		self.assertEqual(result["code"], "STALE_REVISION")

	# ---- queue reader ----------------------------------------------

	def test_queue_hides_out_of_scope_students_and_reports_hints(self):
		self._set_student(owning_team=self._team)
		self._make_action()
		frappe.set_user(self._lead_user)
		mine = student_worklist.list_action_queue()
		self.assertEqual(mine["contract_version"], "action-queue-row-v1")
		row = next(r for r in mine["items"] if r["student"] == self._student.name)
		self.assertEqual(row["queue_status"], "unassigned")
		self.assertTrue(row["can_claim"])
		self.assertEqual(row["primary_command"], "claim")
		self.assertEqual(row["risk_tier"], "low")

		frappe.set_user(self._outsider_user)
		theirs = student_worklist.list_action_queue()
		self.assertNotIn(self._student.name, {r["student"] for r in theirs["items"]})

	def test_queue_can_claim_is_false_when_the_claim_would_not_grant_execute(self):
		# The Director sees the Student (campus oversight) but is not its owner
		# and not on its owning team; the Student is already assigned, so a claim
		# would widen nothing and not grant execute -- can_claim must be false.
		self._set_student(assigned_to=self._sale_staff, owner_staff=self._sale_staff)
		self._make_action()
		director_user, director_staff = _perm.TestSharedScopingPermissions._make_user_and_staff(
			self, "_Test Queue Director", roles=["Admissions Director"]
		)
		try:
			frappe.set_user(director_user)
			row = next(
				r for r in student_worklist.list_action_queue()["items"] if r["student"] == self._student.name
			)
			self.assertFalse(row["can_claim"])
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("CRM Staff", director_staff, force=True)
			frappe.delete_doc("User", director_user, force=True)

	def test_queue_is_closed_to_a_role_without_crm_action_access(self):
		self._set_student(assigned_to=self._sale_staff, owner_staff=self._sale_staff)
		self._make_action()
		marketing_user, _ = _perm.TestSharedScopingPermissions._make_user_and_staff(
			self, "_Test Queue Marketing", roles=["Marketing"]
		)
		try:
			frappe.set_user(marketing_user)
			with self.assertRaises(frappe.PermissionError):
				student_worklist.list_action_queue()
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("User", marketing_user, force=True)

	def test_queue_kill_switch_closes_the_endpoint(self):
		self._set_student(assigned_to=self._sale_staff, owner_staff=self._sale_staff)
		self._make_action()
		conf = frappe._dict(frappe.conf)
		conf["crm_student_action_queue_enabled"] = 0
		with patch("crm.api.student_worklist.frappe.conf", conf):
			frappe.set_user(self._sale_user)
			with self.assertRaises(frappe.PermissionError):
				student_worklist.list_action_queue()

	def test_queue_rejects_a_non_string_student_filter(self):
		frappe.set_user(self._sale_user)
		with self.assertRaises(Exception):
			student_worklist.list_action_queue(student=["STU-1"])

	def test_queue_can_execute_is_false_for_a_non_owner(self):
		self._set_student(assigned_to=self._sale_staff, owner_staff=self._sale_staff)
		self._make_action()
		frappe.set_user(self._sale_user)
		row = next(
			r for r in student_worklist.list_action_queue()["items"] if r["student"] == self._student.name
		)
		self.assertFalse(row["can_execute"])
		self.assertIsNone(row["assignee_ref"])
