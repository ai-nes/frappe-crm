"""Pure contract tests for bounded NBA decision signals."""

import hashlib

import pytest

from crm.fcrm.nba_context import (
	DECISION_SIGNALS_SCHEMA_REVISION,
	DECISION_SIGNALS_CONTENT_HASH,
	DECISION_SIGNALS_CONTENT_SPEC,
	decision_signals_digest,
	validate_decision_signals,
)


def _observation(ref="EVID-1"):
	return {
		"need_code": "RESOLVE_MAJOR_UNCERTAINTY",
		"status": "open",
		"basis": "explicit",
		"confidence": "high",
		"blocks_progress": True,
		"explicit_request": True,
		"advice_readiness": "ready",
		"application_readiness": "hesitant",
		"parent_influence": "unknown",
		"evidence_refs": [ref],
	}


def test_decision_signals_are_bounded_and_digestable():
	payload = {"schema_revision": DECISION_SIGNALS_SCHEMA_REVISION, "observations": [_observation()]}
	assert validate_decision_signals(payload) == payload
	assert len(decision_signals_digest(payload)) == 64


def test_decision_signals_content_fingerprint_is_frozen():
	assert hashlib.sha256(DECISION_SIGNALS_CONTENT_SPEC.encode()).hexdigest() == DECISION_SIGNALS_CONTENT_HASH


def test_decision_signals_reject_raw_or_overbounded_values():
	payload = {"schema_revision": DECISION_SIGNALS_SCHEMA_REVISION, "observations": [_observation()]}
	payload["observations"][0]["raw"] = "secret"
	with pytest.raises(ValueError):
		validate_decision_signals(payload)
	payload["observations"] = [_observation(str(index)) for index in range(13)]
	with pytest.raises(ValueError):
		validate_decision_signals(payload)
