"""Pure assembly of the current NBA Evaluation input envelope.

No Frappe import: the shaping and digest binding are testable without a bench
and stay byte-aligned with the shared golden fixtures under
``crm/fcrm/test_fixtures/nba-evaluation``. The Frappe-facing entry point in
``crm/api/nba_evaluation.py`` gathers the live projection and calls in here.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from crm.fcrm.nba_canonical import canonical_digest

CONTRACT_VERSION = "nba-evaluation"


def _clock(now: datetime | str) -> str:
	return now.isoformat() if isinstance(now, datetime) else str(now)


def assemble_evaluation_input(
	student: Mapping,
	context: Mapping,
	eligible_set: Mapping,
	policies: Mapping,
	*,
	now: datetime | str,
	evaluation_id: str | None = None,
	contract_version: str = CONTRACT_VERSION,
) -> dict:
	"""Bind pre-shaped sub-documents into the current NBA Evaluation envelope.

	``evaluation_key`` is an idempotency key over the evaluation inputs -- the
	student identity, its context revision, and the eligible-set and policy
	digests -- so two calls with the same governed state derive the same key and
	a consumer can de-duplicate. It is not a uniqueness guarantee for a run: the
	durable Evaluation runtime (Phase 03) may add a nonce when it needs a fresh
	evaluation over unchanged inputs.
	"""
	student = dict(student)
	eligible_set = dict(eligible_set)
	policies = dict(policies)

	evaluation_key = canonical_digest(
		{
			"student_id": student.get("student_id"),
			"context_revision": int(student.get("context_revision") or 0),
			"eligible_set_digest": eligible_set.get("set_digest"),
			"policies_digest": canonical_digest(policies),
		}
	)
	return {
		"contract_version": contract_version,
		"evaluation_id": evaluation_id or f"NBAEVAL-{evaluation_key[:16]}",
		"evaluation_key": evaluation_key,
		"evaluation_clock": _clock(now),
		"student": student,
		"context": dict(context),
		"eligible_action_set": eligible_set,
		"policies": policies,
	}


def input_digest(envelope: Mapping) -> str:
	"""Digest that a paired evaluation result binds via ``input_digest``."""
	return canonical_digest(envelope)
