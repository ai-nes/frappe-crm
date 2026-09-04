"""Seed one local Lead Sales login with three team-pool Student cases.

Run with::

    bench --site crm.localhost execute crm.demo.seed_lead_sales.execute

Lead Sales is scoped to its team's cases and unassigned pool, so these cases
remain pool-owned instead of being assigned as an individual owner.
"""

from __future__ import annotations

from typing import Any

from crm.demo.seed_ctv_sale import SalesAccountSeed, execute_seed

NAMESPACE = "crm-demo-lead-sales"
ACCOUNT_EMAIL = "leadsale@gmail.com"
ACCOUNT_FULL_NAME = "Lead Sales Demo"
ACCOUNT_ROLE = "Lead Sales"
PASSWORD = "123456"
TEAM_MEMBERSHIP_FUNCTION = "Lead Sales"

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
		"notes": "Hồ sơ nằm trong pool team, chờ Lead Sales rà soát và phân tuyến.",
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
		"notes": "Hồ sơ mới vào pool, cần Lead Sales kiểm tra trước khi giao cho Sale phụ trách.",
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


def execute() -> dict[str, Any]:
	"""Create the local Lead Sales account and three team-pool Student cases."""
	return execute_seed(SEED_SPEC)
