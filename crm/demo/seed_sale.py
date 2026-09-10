"""Seed one local Sale login with three assigned Student cases.

Run with::

    bench --site crm.localhost execute crm.demo.seed_sale.execute

The fixture reuses the same idempotent ownership workflow as the CTV Sale
fixture and never removes unrelated data.
"""

from __future__ import annotations

from typing import Any

from crm.demo.seed_ctv_sale import SalesAccountSeed, execute_seed

NAMESPACE = "crm-demo-sale"
ACCOUNT_EMAIL = "sale@gmail.com"
ACCOUNT_FULL_NAME = "Sale Demo"
ACCOUNT_ROLE = "Sale"
PASSWORD = "123456"
TEAM_MEMBERSHIP_FUNCTION = "Sale"

STUDENT_SCENARIOS: tuple[dict[str, Any], ...] = (
	{
		"key": "student-01",
		"student_name": "Nguyễn Minh Anh",
		"email": "sale.student01@example.test",
		"phone": "0909900201",
		"gender": "Nữ",
		"date_of_birth": "2008-04-15",
		"id_number": "079308041501",
		"id_issued_date": "2024-05-18",
		"graduation_score": 8.8,
		"transcript_score": 8.9,
		"english_converted_score": 7.5,
		"total_score": 25.2,
		"notes": "Học sinh quan tâm học bổng, cần chốt ngân sách cùng phụ huynh.",
		"parent": {
			"name": "Trần Thị Thu Hà",
			"phone": "0909901201",
			"address": "Quận Bình Thạnh, Thành phố Hồ Chí Minh",
		},
	},
	{
		"key": "student-02",
		"student_name": "Phạm Gia Bảo",
		"email": "sale.student02@example.test",
		"phone": "0909900202",
		"gender": "Nam",
		"date_of_birth": "2008-06-21",
		"id_number": "079308062102",
		"id_issued_date": "2024-07-05",
		"graduation_score": 8.3,
		"transcript_score": 8.6,
		"english_converted_score": 6.5,
		"total_score": 23.4,
		"notes": "Học sinh đã để lại hồ sơ tư vấn và đang chờ tư vấn phương thức xét tuyển.",
		"parent": {
			"name": "Phạm Quốc Hùng",
			"phone": "0909901202",
			"address": "Quận Tân Bình, Thành phố Hồ Chí Minh",
		},
	},
	{
		"key": "student-03",
		"student_name": "Đỗ Hoàng Yến",
		"email": "sale.student03@example.test",
		"phone": "0909900203",
		"gender": "Nữ",
		"date_of_birth": "2008-09-30",
		"id_number": "079308093003",
		"id_issued_date": "2024-10-21",
		"graduation_score": 8.5,
		"transcript_score": 8.7,
		"english_converted_score": 7.0,
		"total_score": 24.2,
		"notes": "Học sinh muốn nhận checklist hồ sơ và lịch tư vấn ngành học.",
		"parent": {
			"name": "Đỗ Thị Hương",
			"phone": "0909901203",
			"address": "Quận 5, Thành phố Hồ Chí Minh",
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
)


def execute() -> dict[str, Any]:
	"""Create the local Sale account and three assigned Student cases."""
	return execute_seed(SEED_SPEC)
