"""Named, server-authorized Action Workbench command boundary."""
import frappe

from crm.services.sales_action_dispatch import edit_action_package


def _load_command_action(action, expected_action_revision, expected_package_revision):
	if not action:
		frappe.throw("action is required.", frappe.ValidationError)
	doc = frappe.get_doc("CRM Action Item", action)
	if not doc.has_permission("read"):
		frappe.throw("Action is outside the actor's scope.", frappe.PermissionError)
	if doc.state in {"completed", "cancelled", "rejected", "superseded"}:
		frappe.throw("The Action is terminal.", frappe.ValidationError)
	if int(doc.action_revision or 1) != int(expected_action_revision):
		frappe.throw("Action changed; refresh before retrying.", frappe.ValidationError, title="STALE_REVISION")
	if int(doc.execution_package_version or 0) != int(expected_package_revision):
		frappe.throw("Package changed; refresh before retrying.", frappe.ValidationError, title="STALE_REVISION")
	return doc

@frappe.whitelist()
def edit_package(task_name, expected_action_revision, expected_package_revision, changes, reason):
	return edit_action_package(task_name, int(expected_action_revision), int(expected_package_revision), changes, reason)

@frappe.whitelist()
def request_dispatch(action, idempotency_key, expected_action_revision, expected_package_revision):
	if not action or not idempotency_key:
		frappe.throw("action and idempotency_key are required.", frappe.ValidationError)
	from crm.services.action_execution import create_or_replay_attempt
	return create_or_replay_attempt(action, "DISPATCH", idempotency_key, expected_action_revision, expected_package_revision)

@frappe.whitelist()
def schedule_action(action, idempotency_key, expected_action_revision, expected_package_revision, scheduled_at=None):
	if not action or not idempotency_key:
		frappe.throw("action and idempotency_key are required.", frappe.ValidationError)
	doc = _load_command_action(action, expected_action_revision, expected_package_revision)
	if doc.state not in {"accepted", "in-progress"}:
		frappe.throw("Only accepted or in-progress Actions may be scheduled.", frappe.ValidationError)
	from crm.fcrm.nba import resolve_nba_channel, resolve_nba_schedule, update_nba_execution
	from crm.services.action_execution import create_or_replay_attempt
	scheduled_at = resolve_nba_schedule(doc, scheduled_at)
	timing_policy = (
		frappe.db.get_value("CRM Recommendation", doc.recommendation, "timing_policy")
		if doc.get("recommendation")
		else None
	)
	result = create_or_replay_attempt(
		action, "SCHEDULE", idempotency_key, int(expected_action_revision), int(expected_package_revision)
	)
	update_nba_execution(
		result["attempt_id"],
		status="pending",
		channel=resolve_nba_channel(doc),
		scheduled_at=scheduled_at,
		input_payload={
			"operation": "SCHEDULE",
			"timing_policy": timing_policy,
			"scheduled_at": str(scheduled_at),
		},
	)
	return {**result, "status": "scheduled", "scheduled_at": scheduled_at}


@frappe.whitelist()
def assign_action(action, idempotency_key, expected_action_revision, expected_package_revision, assignee_staff):
	"""Adapter for the typed ASSIGN command; assignment remains same-team governed."""
	_load_command_action(action, expected_action_revision, expected_package_revision)
	from crm.fcrm.student_decision import reassign_action
	return reassign_action(
		action, int(expected_action_revision), assignee_staff, idempotency_key,
		"Workbench assignment", _internal_service=False,
	)

@frappe.whitelist()
def record_outcome(action, idempotency_key, expected_action_revision, expected_package_revision, outcome_code, evidence_refs=None, attempt_id=None, impact_score=None):
	if not action or not idempotency_key or not outcome_code:
		frappe.throw("action, idempotency_key and outcome_code are required.", frappe.ValidationError)
	refs = evidence_refs if isinstance(evidence_refs, list) else []
	if not refs:
		frappe.throw("At least one evidence reference is required.", frappe.ValidationError)
	from crm.fcrm.student_decision import transition_action
	if not attempt_id:
		frappe.throw("A confirmed attempt is required.", frappe.ValidationError)
	return transition_action(
		action, int(expected_action_revision), "completed", idempotency_key,
		outcome_code=outcome_code, evidence=refs, attempt_id=attempt_id, impact_score=impact_score,
	)


@frappe.whitelist()
def complete_action_manually(action, idempotency_key, expected_action_revision, expected_package_revision, outcome_code, outcome_evidence=None, outcome_notes=None):
	"""Self-service completion for Actions with no provider dispatch (manual outcomes).

	Creates and self-confirms a RECORD_OUTCOME execution attempt on the actor's
	behalf, then records the outcome through the same command path as
	``record_outcome``. Scoped strictly to the RECORD_OUTCOME operation so it can
	never substitute for a CALL/EMAIL provider dispatch confirmation.
	"""
	if not action or not idempotency_key or not outcome_code:
		frappe.throw("action, idempotency_key and outcome_code are required.", frappe.ValidationError)
	from crm.services.action_execution import create_or_replay_attempt, transition_attempt

	attempt = create_or_replay_attempt(
		action, "RECORD_OUTCOME", idempotency_key, int(expected_action_revision), int(expected_package_revision)
	)
	attempt_id = attempt["attempt_id"]
	status = attempt["status"]
	if status == "pending":
		status = transition_attempt(attempt_id, "queued")["status"]
	if status == "queued":
		attempt_doc = frappe.db.get_value("CRM Action Execution Attempt", attempt_id, "operation")
		if attempt_doc != "RECORD_OUTCOME":
			frappe.throw("Only manual RECORD_OUTCOME attempts may be self-confirmed.", frappe.PermissionError)
		status = transition_attempt(attempt_id, "confirmed")["status"]
	if status != "confirmed":
		frappe.throw("Could not confirm the manual execution attempt.", frappe.ValidationError)

	refs = (
		[outcome_evidence]
		if isinstance(outcome_evidence, str) and outcome_evidence.strip()
		else (outcome_evidence if isinstance(outcome_evidence, list) and outcome_evidence else ["manual-confirmation"])
	)
	result = record_outcome(
		action, idempotency_key, expected_action_revision, expected_package_revision,
		outcome_code, evidence_refs=refs, attempt_id=attempt_id,
	)
	if outcome_notes:
		frappe.db.set_value("CRM Action Item", action, "outcome_notes", str(outcome_notes)[:2000], update_modified=False)
	return result


@frappe.whitelist(allow_guest=False)
def confirm_provider_event(attempt_id, provider_event_id, signature, raw_body):
	from crm.services.action_execution import confirm_provider_event as confirm
	return confirm(attempt_id, provider_event_id, signature, raw_body)


@frappe.whitelist(allow_guest=False)
def queue_attempt(attempt_id):
	from crm.services.action_execution import transition_attempt
	return transition_attempt(attempt_id, "queued")


@frappe.whitelist()
def authorize_attempt_for_send(attempt_id):
	from crm.services.action_execution import authorize_attempt_for_send as authorize
	return authorize(attempt_id)


@frappe.whitelist()
def process_queued_attempt(attempt_id, channel=None):
	from crm.services.action_execution import process_queued_attempt as process
	return process(attempt_id, channel)


@frappe.whitelist()
def release_action(action, idempotency_key, expected_action_revision, reason):
	from crm.fcrm.student_decision import release_action as release
	return release(action, int(expected_action_revision), idempotency_key, reason)
