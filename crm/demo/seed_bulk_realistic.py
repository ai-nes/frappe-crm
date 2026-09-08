"""Pure helpers for the large, deterministic CRM demo student cohort.

The Frappe orchestration stays in :mod:`seed_showcase`; this module keeps the
allocation contract independent of a site so it can be tested quickly and
reused by both local and deployed demo runs.
"""

from __future__ import annotations

import random
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any


DEFAULT_ALLOCATION_SEED = 3184
DEFAULT_PER_SCHOOL_CAP = 10
BULK_IMPORT_NAMESPACE = "crm-demo-showcase:bulk"
LEGACY_BULK_IMPORT_NAMESPACE = "crm-demo-showcase"

_STAGE_STATUS_NAMES = {
	"Lead": "NEW",
	"MQL": "PROSPECT",
	"Applicant": "CONFIRMED",
	"Enrolled": "ENROLLED",
	"Lost": "REFUSED",
}
_GRADE_STAGES = (
	("10", "grade_10"),
	("11", "grade_11"),
	("12", "grade_12_h1"),
	("12", "grade_12_h2"),
	("post_exam", "post_exam"),
)


def _fold(value: Any) -> str:
	"""Return a case/diacritic-insensitive label for province classification."""
	text = str(value or "").replace("Đ", "D").replace("đ", "d")
	text = unicodedata.normalize("NFKD", text)
	return "".join(char for char in text if not unicodedata.combining(char)).casefold()


def background_student_count(total_target: int, curated_count: int, edge_count: int = 5) -> int:
	"""Return the exact ordinary-row count needed to hit the namespace target."""
	if total_target < 0 or curated_count < 0 or edge_count < 0:
		raise ValueError("student counts cannot be negative")
	remaining = total_target - curated_count - edge_count
	if remaining < 0:
		raise ValueError("the target is smaller than the curated and edge cohorts")
	return remaining


def province_weight(province: Any) -> float:
	"""Weight extra school placements toward HCM and Dong Nai."""
	label = _fold(province)
	if "ho chi minh" in label:
		return 2.0
	if "dong nai" in label:
		return 1.5
	return 1.0


def _school_sort_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
	return (
		_fold(row.get("province")),
		_fold(row.get("school_name") or row.get("name")),
		_fold(row.get("ward")),
		str(row.get("name") or ""),
	)


def allocate_school_placements(
	schools: Iterable[Any],
	student_count: int,
	*,
	seed: int = DEFAULT_ALLOCATION_SEED,
	per_school_cap: int = DEFAULT_PER_SCHOOL_CAP,
) -> list[dict[str, Any]]:
	"""Allocate every student to a real school with deterministic regional bias.

	Every school receives one placement before weighted, diminishing-return
	placements are assigned. The load-balancing score keeps HCM above the other
	provinces, Dong Nai between HCM and the baseline, and prevents a single school
	from absorbing the cohort.
"""
	if student_count < 0:
		raise ValueError("student_count cannot be negative")
	if per_school_cap < 1:
		raise ValueError("per_school_cap must be positive")
	if not schools:
		if student_count:
			raise ValueError("cannot place students without schools")
		return []

	ordered = sorted((_canonical_school(row) for row in schools), key=_school_sort_key)
	seen_names: set[str] = set()
	for row in ordered:
		name = str(row.get("name") or "").strip()
		province = str(row.get("province") or "").strip()
		ward = str(row.get("ward") or "").strip()
		if not name or not province or not ward:
			raise ValueError("every school must have name, province and ward")
		if name in seen_names:
			raise ValueError(f"duplicate school name: {name}")
		seen_names.add(name)
	if student_count < len(ordered):
		raise ValueError("student_count must cover every school at least once")
	if student_count > len(ordered) * per_school_cap:
		raise ValueError("student_count exceeds the per-school capacity")

	rng = random.Random(seed)
	placements = [dict(row) for row in ordered]
	remaining = student_count - len(ordered)
	groups: dict[float, list[dict[str, Any]]] = {}
	for row in ordered:
		groups.setdefault(province_weight(row.get("province")), []).append(row)

	# Reserve the extra rows by province first. This makes the requested regional
	# bias a guarantee rather than a statistical hope, while the round-robin inside
	# each group keeps individual schools close to one another.
	weight_total = sum(weight * len(rows) for weight, rows in groups.items())
	quotas: dict[float, int] = {}
	fractions: list[tuple[float, float]] = []
	for weight, rows in groups.items():
		ideal = remaining * weight * len(rows) / weight_total
		quotas[weight] = min(int(ideal), len(rows) * (per_school_cap - 1))
		fractions.append((ideal - int(ideal), weight))
	left = remaining - sum(quotas.values())
	for _fraction, weight in sorted(fractions, key=lambda item: (-item[0], -item[1])):
		if not left:
			break
		capacity = len(groups[weight]) * (per_school_cap - 1)
		if quotas[weight] < capacity:
			quotas[weight] += 1
			left -= 1
	if left:
		# This only occurs when a weighted quota hit a small group's cap. Fill any
		# remaining capacity in the highest-weight eligible groups.
		for weight in sorted(groups, reverse=True):
			capacity = len(groups[weight]) * (per_school_cap - 1)
			available = capacity - quotas[weight]
			allocation = min(left, available)
			quotas[weight] += allocation
			left -= allocation
			if not left:
				break
		if left:
			raise ValueError("unable to distribute the requested student count")

	for weight, rows in groups.items():
		rotation = rng.randrange(len(rows)) if rows else 0
		for offset in range(quotas[weight]):
			placements.append(dict(rows[(rotation + offset) % len(rows)]))

	return placements


def _value(row: Any, key: str) -> Any:
	if isinstance(row, Mapping):
		return row.get(key)
	return getattr(row, key, None)


def _canonical_school(row: Any) -> dict[str, Any]:
	name = str(_value(row, "name") or "").strip()
	province = str(_value(row, "province") or "").strip()
	ward = str(_value(row, "ward") or "").strip()
	if not name:
		raise ValueError("every school must have a name")
	if not province:
		raise ValueError(f"school {name!r} is missing province")
	if not ward:
		raise ValueError(f"school {name!r} is missing ward")
	return {"name": name, "province": province, "ward": ward}


def enrich_bulk_scenarios(
	scenarios: Iterable[Mapping[str, Any]],
	schools: Iterable[Any],
	major_choices: Iterable[tuple[str, float]],
	lead_sources: Iterable[str],
	*,
	seed: int = DEFAULT_ALLOCATION_SEED,
	per_school_cap: int = DEFAULT_PER_SCHOOL_CAP,
) -> tuple[dict[str, Any], ...]:
	"""Attach school-derived geography and deterministic references to scenarios."""
	scenario_rows = [dict(row) for row in scenarios]
	placements = allocate_school_placements(
		schools,
		len(scenario_rows),
		seed=seed,
		per_school_cap=per_school_cap,
	)
	major_rows = [(str(name), float(weight)) for name, weight in major_choices if str(name).strip()]
	source_rows = [str(source).strip() for source in lead_sources if str(source).strip()]
	if not major_rows:
		raise ValueError("at least one major is required")
	if not source_rows:
		raise ValueError("at least one lead source is required")

	rng = random.Random(seed ^ 0x9911)
	enriched: list[dict[str, Any]] = []
	for scenario, school in zip(scenario_rows, placements, strict=True):
		row = dict(scenario)
		row.update(
			high_school=school["name"],
			province=school["province"],
			ward=school["ward"],
			major=rng.choices(
				[name for name, _weight in major_rows],
				weights=[weight for _name, weight in major_rows],
				k=1,
			)[0],
			source=rng.choice(source_rows),
		)
		enriched.append(row)
	return tuple(enriched)


def build_student_values(
	scenario: Mapping[str, Any],
	context: Mapping[str, Any],
	*,
	index: int,
	status_by_stage: Mapping[str, str] | None = None,
	owning_team: str | None = None,
	owning_pool: str | None = None,
	assigned_to: str | None = None,
) -> dict[str, Any]:
	"""Build the complete payload for one shallow background student."""
	stage = str(scenario.get("target_stage") or "Lead")
	status_name = (status_by_stage or _STAGE_STATUS_NAMES).get(stage)
	if not status_name:
		raise ValueError(f"missing enrollment status mapping for lifecycle stage {stage!r}")
	if not scenario.get("high_school") or not scenario.get("province") or not scenario.get("ward"):
		raise ValueError(f"scenario {scenario.get('key')!r} is missing school-derived geography")

	grade, study_stage = _GRADE_STAGES[index % len(_GRADE_STAGES)]
	if stage in {"Applicant", "Enrolled"} and index % 3:
		grade, study_stage = "post_exam", "post_exam"
	admission_year = int(context["admission_year"])
	key = str(scenario["key"])
	values = {
		"doctype": "CRM Lead",
		"student_name": scenario["student_name"],
		"email": scenario["email"],
		"phone": scenario["phone"],
		"gender": scenario["gender"],
		"admission_method": scenario["admission_method"],
		"admission_year": context["admission_year"],
		"enrollment_status": status_name,
		"high_school": scenario["high_school"],
		"province": scenario["province"],
		"ward": scenario["ward"],
		"branch": context["campus"],
		"major": scenario.get("major") or context.get("major"),
		"source": scenario.get("source") or context.get("source"),
		"aspiration": context.get("aspiration"),
		"education_program": context.get("education_program"),
		"current_grade": grade,
		"study_stage": study_stage,
		"cohort_start_year": admission_year,
		"cohort_end_year": admission_year + 3,
		"owning_team": owning_team,
		"owning_pool": owning_pool,
		"assigned_to": assigned_to,
		"import_source_id": f"{BULK_IMPORT_NAMESPACE}:{key}",
		"notes": f"Dữ liệu demo nền — {key}; hồ sơ dùng cho danh sách và dashboard.",
	}
	if index % 3:
		values.update(
			alt_name=f"Phụ huynh của {scenario['student_name']}",
			alt_phone=f"098{index + 1:07d}",
		)
	return values


def seed_bulk_students(
	scenarios: Iterable[Mapping[str, Any]],
	context: Mapping[str, Any],
	staff_context: Mapping[str, Any],
	*,
	status_by_stage: Mapping[str, str] | None = None,
	batch_size: int = 100,
) -> dict[str, Any]:
	"""Insert or update the background cohort in bounded transactions."""
	if batch_size < 1:
		raise ValueError("batch_size must be positive")
	import frappe

	staff_names = sorted(
		{
			str(name)
			for name in (staff_context.get("staff_by_user") or {}).values()
			if name
		}
	)
	team = staff_context.get("team")
	pool = staff_context.get("pool")
	manifest: list[dict[str, Any]] = []
	errors: list[dict[str, Any]] = []
	created = 0
	updated = 0
	rows = list(scenarios)

	for index, scenario in enumerate(rows):
		savepoint = f"bulk_student_{index}"
		frappe.db.savepoint(savepoint)
		try:
			assigned_to = staff_names[index % len(staff_names)] if staff_names and scenario.get("owner") else None
			values = build_student_values(
				scenario,
				context,
				index=index,
				status_by_stage=status_by_stage,
				owning_team=team,
				owning_pool=pool,
				assigned_to=assigned_to,
			)
			import_source_id = values["import_source_id"]
			existing = frappe.db.get_value("CRM Lead", {"import_source_id": import_source_id}, "name")
			if not existing:
				existing = frappe.db.get_value("CRM Lead", {"email": values["email"]}, "name")
			if existing:
				existing_source = frappe.db.get_value("CRM Lead", existing, "import_source_id")
				legacy_source = f"{LEGACY_BULK_IMPORT_NAMESPACE}:{scenario['key']}"
				if existing_source not in {import_source_id, legacy_source}:
					raise ValueError(f"student email is already owned by another seed row: {values['email']}")
				_update_existing_student(frappe, existing, values)
				student_name = existing
				updated += 1
			else:
				doc = frappe.get_doc(values)
				doc.insert(ignore_permissions=True)
				student_name = doc.name
				created += 1
			manifest.append(
				{
					"key": scenario["key"],
					"student": student_name,
					"operation": "updated" if existing else "created",
					"high_school": values["high_school"],
					"province": values["province"],
					"ward": values["ward"],
					"lifecycle_stage": stage_for_status(status_by_stage, values["enrollment_status"]),
				}
			)
			if (index + 1) % batch_size == 0:
				frappe.db.commit()
				_clear_frappe_caches(frappe)
		except Exception as exc:
			try:
				frappe.db.rollback(save_point=savepoint)
			except Exception:
				frappe.db.rollback()
			errors.append({"key": scenario.get("key"), "error": str(exc)})

	if manifest:
		frappe.db.commit()
	return {
		"manifest": manifest,
		"errors": errors,
		"created": created,
		"updated": updated,
		"requested": len(rows),
		"namespace": BULK_IMPORT_NAMESPACE,
	}


def stage_for_status(status_by_stage: Mapping[str, str] | None, status_name: str) -> str:
	for stage, name in (status_by_stage or _STAGE_STATUS_NAMES).items():
		if name == status_name:
			return stage
	return "Lead"


def _update_existing_student(frappe, name: str, values: Mapping[str, Any]) -> None:
	"""Repair a previous bulk row while respecting Student service guards."""
	doc = frappe.get_doc("CRM Lead", name)
	for key, value in values.items():
		if key != "doctype":
			setattr(doc, key, value)
	previous_lifecycle = frappe.flags.get("student_lifecycle_service")
	previous_ownership = frappe.flags.get("student_ownership_service")
	frappe.flags.student_lifecycle_service = True
	frappe.flags.student_ownership_service = True
	try:
		doc.save(ignore_permissions=True)
	finally:
		frappe.flags.student_lifecycle_service = previous_lifecycle
		frappe.flags.student_ownership_service = previous_ownership


def _clear_frappe_caches(frappe) -> None:
	frappe.local.document_cache = {}
	if hasattr(frappe.local, "meta_cache"):
		frappe.local.meta_cache = {}
	frappe.clear_messages()
