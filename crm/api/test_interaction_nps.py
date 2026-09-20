import json

import frappe

from crm.api.interaction_nps import _canonical_digest, _validate_dimensions


def _dimensions():
	return {
		dimension: {
			"score": 8,
			"confidence": "high",
			"evidence_refs": [
				{"doctype": "CRM Interaction Evidence", "name": "EVID-1", "actor_role": "student"}
			],
			"explanation": "Có tín hiệu rõ từ học sinh.",
		}
		for dimension in ("satisfaction", "resolution", "friction", "complaint")
	}


def test_nps_dimensions_are_bounded_and_canonical():
	validated = _validate_dimensions(_dimensions())

	assert set(validated) == {"satisfaction", "resolution", "friction", "complaint"}
	assert validated["resolution"]["score"] == 8
	assert len(_canonical_digest(json.loads(json.dumps(validated)))) == 64


def test_nps_dimensions_accept_parent_evidence_for_combined_quality():
	values = _dimensions()
	values["satisfaction"]["evidence_refs"][0]["actor_role"] = "parent"

	validated = _validate_dimensions(values)

	assert validated["satisfaction"]["evidence_refs"][0]["actor_role"] == "parent"


def test_nps_dimensions_reject_out_of_range_score():
	values = _dimensions()
	values["complaint"]["score"] = 11

	try:
		_validate_dimensions(values)
	except frappe.ValidationError:
		return
	raise AssertionError("out-of-range score was accepted")
