from crm.fcrm.admissions_projections import build_projection


def test_projection_envelope_has_one_server_owned_filter_and_source_contract():
	result = build_projection(
		"AICommandCenter", {"from": "2026-01-01", "to": "2026-01-31"}, {"leads": 2}, ai_unavailable=True
	)

	assert result["contract"] == "admissions-erd-v1"
	assert result["filters"]["from_date"] == "2026-01-01"
	assert result["source"]["mode"] == "target"
	assert result["source"]["definition_version"] == "admissions-erd-v1"
	assert result["source"]["subject_grain"] is None
	assert result["ai_unavailable"] is True
