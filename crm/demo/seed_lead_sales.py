"""Seed one local Lead Sale login with three team-pool Student cases.

Run with::

    bench --site crm.localhost execute crm.demo.seed_lead_sales.execute

Lead Sale is scoped to its team's cases and unassigned pool, so these cases
remain pool-owned instead of being assigned as an individual owner.
"""

from __future__ import annotations

from typing import Any

import frappe

from crm.demo import seed_demo, seed_showcase, seed_staff
from crm.demo.seed_ctv_sale import SalesAccountSeed, execute_seed

NAMESPACE = "crm-demo-lead-sales"
ACCOUNT_EMAIL = "leadsale@gmail.com"
ACCOUNT_FULL_NAME = "Lead Sale Demo"
ACCOUNT_ROLE = "Lead Sale"
PASSWORD = "123456"
TEAM_MEMBERSHIP_FUNCTION = "Lead Sale"

STUDENT_SCENARIOS: tuple[dict[str, Any], ...] = (
	{
		"key": "student-01",
		"student_name": "Nguyễn Đức Anh",
		"email": "lead-sales.student01@example.test",
		"phone": "0909900301",
		"gender": "Nam",
		"date_of_birth": "2008-02-12",
		"id_number": "079308021201",
		"id_issued_date": "2024-03-22",
		"graduation_score": 8.7,
		"transcript_score": 8.9,
		"english_converted_score": 7.0,
		"total_score": 24.6,
		"notes": "Hồ sơ nằm trong pool team, chờ Lead Sale rà soát và phân tuyến.",
		"parent": {
			"name": "Nguyễn Văn Đức",
			"phone": "0909901301",
			"address": "Quận 10, Thành phố Hồ Chí Minh",
		},
	},
	{
		"key": "student-02",
		"student_name": "Võ Khánh Linh",
		"email": "lead-sales.student02@example.test",
		"phone": "0909900302",
		"gender": "Nữ",
		"date_of_birth": "2008-05-28",
		"id_number": "079308052802",
		"id_issued_date": "2024-06-30",
		"graduation_score": 8.2,
		"transcript_score": 8.5,
		"english_converted_score": 6.5,
		"total_score": 23.2,
		"notes": "Gia đình cần được tư vấn thêm về học phí và chính sách hỗ trợ tài chính.",
		"parent": {
			"name": "Võ Thị Thanh",
			"phone": "0909901302",
			"address": "Quận Gò Vấp, Thành phố Hồ Chí Minh",
		},
	},
	{
		"key": "student-03",
		"student_name": "Bùi Minh Quân",
		"email": "lead-sales.student03@example.test",
		"phone": "0909900303",
		"gender": "Nam",
		"date_of_birth": "2008-08-19",
		"id_number": "079308081903",
		"id_issued_date": "2024-09-25",
		"graduation_score": 8.4,
		"transcript_score": 8.6,
		"english_converted_score": 7.0,
		"total_score": 24.0,
		"notes": "Hồ sơ mới vào pool, cần Lead Sale kiểm tra trước khi giao cho Sale phụ trách.",
		"parent": {
			"name": "Bùi Văn Nam",
			"phone": "0909901303",
			"address": "Quận 6, Thành phố Hồ Chí Minh",
		},
	},
)

SEED_SPEC = SalesAccountSeed(
	namespace=NAMESPACE,
	account_email=ACCOUNT_EMAIL,
	account_full_name=ACCOUNT_FULL_NAME,
	account_role=ACCOUNT_ROLE,
	password=PASSWORD,
	team_membership_function=TEAM_MEMBERSHIP_FUNCTION,
	student_scenarios=STUDENT_SCENARIOS,
	assign_students_to_account=False,
	is_team_lead=True,
)


def _source_id(key: str) -> str:
	return f"{NAMESPACE}:{key}"


def _fixture_source_ids() -> tuple[str, ...]:
	return tuple(_source_id(scenario["key"]) for scenario in STUDENT_SCENARIOS)


def reset() -> dict[str, Any]:
	"""Return only this fixture's students to pool ownership for another run.

	The reset intentionally uses the canonical ownership command. This keeps
	ownership events and command receipts append-only while creating a fresh
	ownership revision and routing request for every test cycle.
	"""
	seed_showcase._assert_local_site()
	seed_showcase.ensure_local_integrity_keys()
	seed_showcase.ensure_demo_config()
	frappe.set_user("Administrator")

	with seed_showcase._temporary_local_flags():
		context = seed_demo._bootstrap()
		team = seed_staff._ensure_fixture_sales_team(context["campus"])
		pool = seed_staff._ensure_fixture_student_pool(team)
		students = frappe.get_all(
			"CRM Student",
			filters={"import_source_id": ["in", list(_fixture_source_ids())]},
			fields=["name", "import_source_id", "branch", "ownership_revision"],
			limit_page_length=0,
		)
		students_by_source = {row.import_source_id: row for row in students}
		missing = [source_id for source_id in _fixture_source_ids() if source_id not in students_by_source]
		reset_rows: list[dict[str, Any]] = []

		from crm.fcrm.student_ownership import change_student_ownership

		for scenario in STUDENT_SCENARIOS:
			source_id = _source_id(scenario["key"])
			row = students_by_source.get(source_id)
			if not row:
				continue
			current_revision = int(row.ownership_revision or 0)
			result = change_student_ownership(
				student=row.name,
				target_kind="pool",
				target_id=pool,
				target_team_id=team,
				reason="Reset Lead Sale assignment pipeline fixture for another test run.",
				idempotency_key=f"{NAMESPACE}:reset:{scenario['key']}:r{current_revision}",
				expected_revision=current_revision,
				correlation_id=f"{NAMESPACE}:reset:{scenario['key']}:r{current_revision}",
				_internal_service=True,
				_internal_actor="Administrator",
				_commit=False,
				_route_trigger="pool_return",
			)
			frappe.db.commit()
			reset_rows.append(
				{
					"student": row.name,
					"source_id": source_id,
					"revision": result.get("revision"),
					"request": frappe.db.get_value(
						"CRM Student Routing Request",
						{"student": row.name, "ownership_revision": result.get("revision")},
						"name",
					),
				}
			)

	return {
		"pool": pool,
		"team": team,
		"reset": reset_rows,
		"missing": missing,
		"count": len(reset_rows),
	}


def execute() -> dict[str, Any]:
	"""Create the local Lead Sale account and three team-pool Student cases."""
	return execute_seed(SEED_SPEC)
