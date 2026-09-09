from crm.demo import seed_task
from crm.demo.seed_task import (
	EXPECTED_PROVINCE_COUNT,
	LEAD_COUNT,
	LOCAL_AI_RUNTIME_CONFIG,
	SCHOOLS_PER_PROVINCE,
	build_lead_profiles,
	owner_account_for_index,
)


class _FakeLead:
	name = "HS-2026-HCM-000101"

	def __init__(self, processing_status, resolution):
		self.values = {"processing_status": processing_status, "resolution": resolution}

	def get(self, fieldname):
		return self.values.get(fieldname)


def _schools():
	return [
		{
			"name": f"School {index:02d}",
			"school_name": f"School {index:02d}",
			"school_code": f"{index:02d}",
			"province": f"Province {(index // SCHOOLS_PER_PROVINCE) + 1}",
			"ward": f"Ward {index:02d}",
		}
		for index in range(EXPECTED_PROVINCE_COUNT * SCHOOLS_PER_PROVINCE)
	]


def _campaigns():
	return [{"name": f"Campaign {index}"} for index in range(4)]


def test_build_lead_profiles_is_complete_and_covers_all_provinces():
	profiles = build_lead_profiles(_schools(), _campaigns(), {"platform": "Task Seed Website"})

	assert len(profiles) == LEAD_COUNT
	assert len({profile["student_email"] for profile in profiles}) == LEAD_COUNT
	assert len({profile["school"]["province"] for profile in profiles}) == EXPECTED_PROVINCE_COUNT
	assert all(profile["campaign"] for profile in profiles)
	assert all(profile["parent"]["phone"] for profile in profiles)


def test_owner_rotation_excludes_lead_sales_from_direct_ownership():
	owners = [owner_account_for_index(index)["function"] for index in range(LEAD_COUNT)]

	assert owners == ["CTV Sale", "Sale"] * (LEAD_COUNT // 2)


def test_task_seed_persists_ai_runtime_gates_after_seed(monkeypatch):
	config = {}
	writes = []

	monkeypatch.setattr(seed_task.frappe, "conf", config)
	monkeypatch.setattr(
		"frappe.installer.update_site_config",
		lambda key, value, validate=False: writes.append((key, value, validate)),
	)

	seed_task._persist_local_ai_runtime_config()

	assert config == LOCAL_AI_RUNTIME_CONFIG
	assert writes == [(key, value, False) for key, value in LOCAL_AI_RUNTIME_CONFIG.items()]


def test_seed_one_enriches_the_converted_student_before_creating_related_records(monkeypatch):
	"""The task fixture must not create a pre-conversion duplicate Student."""
	profile = {
		"key": "lead-01",
		"student_name": "Test Student",
		"campaign": "Campaign",
		"school": {"name": "School", "province": "HCM"},
		"major": "SE",
	}
	context = {"campaign": "Campaign"}
	accounts = {"staff_by_email": {"ctvsale@gmail.com": "CTV Staff"}, "team": "Team", "pool": "Pool"}
	calls = []

	monkeypatch.setattr(seed_task, "_submit_lead", lambda *_: "HS-2026-HCM-000101")
	monkeypatch.setattr(seed_task, "_complete_lead", lambda *_: calls.append("complete"))
	monkeypatch.setattr(seed_task, "_assign_lead", lambda *_: calls.append("assign"))
	monkeypatch.setattr(
		seed_task, "_ensure_conversion", lambda *_: calls.append("convert") or "HS-2026-HCM-000101"
	)
	monkeypatch.setattr(
		seed_task,
		"_ensure_contact",
		lambda student, *_: calls.append(("contact", student)) or student,
	)
	monkeypatch.setattr(seed_task, "_ensure_interactions", lambda *_: ("I1", "I2", "I3"))
	monkeypatch.setattr(seed_task, "_ensure_intents", lambda *_: ("Intent",))
	monkeypatch.setattr(seed_task, "_ensure_application", lambda *_: "Application")
	monkeypatch.setattr(seed_task, "_ensure_parent", lambda *_: "Parent")
	monkeypatch.setattr(seed_task, "_ensure_attribution", lambda *_: "Attribution")
	monkeypatch.setattr(seed_task, "_ensure_assessment", lambda *_: "Assessment")
	monkeypatch.setattr(seed_task, "_ensure_score", lambda *_: "Score")
	monkeypatch.setattr(seed_task, "_ensure_action", lambda *_: "Action")

	row = seed_task._seed_one(profile, context, accounts, 0)

	assert calls == ["complete", "assign", "convert", ("contact", "HS-2026-HCM-000101")]
	assert row["student"] == row["contact"] == "HS-2026-HCM-000101"


def test_assign_lead_is_idempotent_for_a_converted_lead(monkeypatch):
	lead = _FakeLead("CLOSED", "CREATED")
	calls = []
	monkeypatch.setattr(seed_task.frappe, "get_doc", lambda *_: lead)
	monkeypatch.setattr(
		seed_task.frappe.db,
		"get_value",
		lambda *_args, **_kwargs: seed_task.frappe._dict(
			owner_staff="CTV Staff", owning_team=None, owning_pool=None, ownership_revision=1
		),
	)
	monkeypatch.setattr(
		"crm.fcrm.lead_processing.mark_lead_assigned",
		lambda *_args, **_kwargs: calls.append("mark"),
	)
	monkeypatch.setattr(
		"crm.fcrm.student_ownership.change_student_ownership",
		lambda *_args, **_kwargs: calls.append("change"),
	)

	seed_task._assign_lead(lead.name, "CTV Staff", "Sales Team", "lead-01")

	assert calls == []
