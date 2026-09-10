import json
from pathlib import Path

import pytest

from crm.services.intelligence_refs import (
	build_coverage,
	build_decision_ref,
	build_evidence_ref,
	build_finding_ref,
	build_outcome_ref,
	build_subject_ref,
	finding_id,
	reference_digest,
)


def test_frappe_reference_shape_and_digest_are_stable():
	subject = build_subject_ref("student", "STU-1", "site-a", admission_year="2026")
	one = build_evidence_ref("e-1", subject, "score", "score-1", "7")
	two = build_evidence_ref("e-1", subject, "score", "score-1", "7")
	assert one == two
	assert reference_digest(one) == reference_digest(two)
	decision_one = build_decision_ref("d-1", "student_nba", subject, "recommend", "nba-decision-policy", evidence_refs=["score:score-1:7"], expires_at="2026-12-01T00:00:00Z")
	decision_two = {**decision_one, "expires_at": "2026-12-02T00:00:00Z"}
	assert reference_digest(decision_one) == reference_digest(decision_two)


def test_frappe_rejects_invalid_evidence_state():
	subject = build_subject_ref("school", "SCH-1", "site-a")
	with pytest.raises(ValueError):
		build_evidence_ref("e-1", subject, "activity", "a-1", "1", freshness="stale")
	with pytest.raises(ValueError):
		build_evidence_ref("e-2", subject, "activity", "a-2", "1", status="denied", visibility="shareable")


def test_frappe_shared_refs_cover_decision_outcome_and_coverage_states():
	subject = build_subject_ref("student", "STU-1", "site-a")
	coverage = build_coverage("coverage-1", "truncated", 8, 2, reason="model_history_limit")
	finding = build_finding_ref(finding_id=finding_id(subject=subject, kind="risk", code="missing_doc", evidence_refs=["score:score-1:7"]), subject=subject, kind="risk", code="missing_doc", evidence_refs=["score:score-1:7"], confidence=0.7)
	decision = build_decision_ref("d-1", "student_nba", subject, "recommend", "nba-decision-policy", evidence_refs=["score:score-1:7"], finding_refs=[finding["finding_id"]], expires_at="2026-12-01T00:00:00Z")
	outcome = build_outcome_ref("o-1", subject, "verified_outcome", "enrolled", "8", decision_id=decision["decision_id"], verified=True)
	assert coverage["state"] == "truncated"
	assert finding["subject"] == decision["subject"] == outcome["subject"]
	assert reference_digest(outcome) == reference_digest(dict(outcome))


def test_frappe_redacted_fixture_and_enum_guards_match_contract():
	fixture = json.loads((Path(__file__).parents[1] / "fcrm" / "fixtures" / "intelligence-reference-v1.json").read_text(encoding="utf-8"))
	subject_data = fixture["subject"]
	subject = build_subject_ref("student", subject_data["subject_id"], subject_data["tenant_id"], admission_year=subject_data["admission_year"])
	evidence = build_evidence_ref(fixture["evidence"]["evidence_id"], subject, fixture["evidence"]["source_kind"], fixture["evidence"]["source_id"], fixture["evidence"]["source_revision"], freshness=fixture["evidence"]["freshness"], visibility=fixture["evidence"]["visibility"])
	assert evidence["subject"] == subject
	assert build_coverage(**{key: fixture["coverage"][key] for key in ("coverage_id", "state", "included_count", "omitted_count")})["state"] == "available"
	with pytest.raises(ValueError):
		build_finding_ref("f-1", subject, "not-a-kind", "code", ["score:SC-1:7"])
	with pytest.raises(ValueError):
		build_decision_ref("d-1", "not-a-domain", subject, "wait", "policy")
