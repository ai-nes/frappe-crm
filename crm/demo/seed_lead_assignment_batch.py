"""Seed a local Lead assignment batch with ten student profiles.

Run with::

    bench --site crm.localhost execute crm.demo.seed_lead_assignment_batch.execute

The fixture creates ten CRM Lead records, places them in one draft assignment
batch, and leaves preview/run to the dashboard so the operator can follow the
same flow as a real batch.
"""

from __future__ import annotations

from typing import Any

import frappe

from crm.api import lead_assignment_batch
from crm.demo import seed_ctv_sale, seed_showcase
from crm.demo.seed_ctv_sale import SalesAccountSeed

NAMESPACE = "crm-demo-lead-assignment-batch"
BATCH_NAME = "Demo phân công 10 Lead"
BATCH_DESCRIPTION = "Đợt mẫu gồm 10 hồ sơ học sinh để kiểm tra trước và phân công."
ACCOUNT_EMAIL = "leadsale@gmail.com"
ACCOUNT_FULL_NAME = "Lead Sale Demo"
ACCOUNT_ROLE = "Lead Sale"
PASSWORD = "123456"
TEAM_MEMBERSHIP_FUNCTION = "Lead Sale"


def _scenario(
	key: str,
	student_name: str,
	email: str,
	phone: str,
	gender: str,
	date_of_birth: str,
	id_number: str,
	graduation_score: float,
	transcript_score: float,
	english_converted_score: float,
	total_score: float,
	parent_name: str,
	parent_phone: str,
	parent_address: str,
	notes: str,
) -> dict[str, Any]:
	return {
		"key": key,
		"student_name": student_name,
		"email": email,
		"phone": phone,
		"gender": gender,
		"date_of_birth": date_of_birth,
		"id_number": id_number,
		"id_issued_date": "2024-06-30",
		"graduation_score": graduation_score,
		"transcript_score": transcript_score,
		"english_converted_score": english_converted_score,
		"total_score": total_score,
		"notes": notes,
		"parent": {
			"name": parent_name,
			"phone": parent_phone,
			"address": parent_address,
		},
	}


STUDENT_SCENARIOS: tuple[dict[str, Any], ...] = (
	_scenario(
		"student-01",
		"Nguyễn Đức Anh",
		"lead-assignment.student01@example.test",
		"0909900401",
		"Nam",
		"2008-02-12",
		"079308021201",
		8.7,
		8.9,
		7.0,
		24.6,
		"Nguyễn Văn Đức",
		"0909901401",
		"Quận 10, Thành phố Hồ Chí Minh",
		"Quan tâm ngành công nghệ và muốn được tư vấn lộ trình xét tuyển.",
	),
	_scenario(
		"student-02",
		"Võ Khánh Linh",
		"lead-assignment.student02@example.test",
		"0909900402",
		"Nữ",
		"2008-05-28",
		"079308052802",
		8.2,
		8.5,
		6.5,
		23.2,
		"Võ Thị Thanh",
		"0909901402",
		"Quận Gò Vấp, Thành phố Hồ Chí Minh",
		"Gia đình cần thông tin học phí và chính sách hỗ trợ tài chính.",
	),
	_scenario(
		"student-03",
		"Bùi Minh Quân",
		"lead-assignment.student03@example.test",
		"0909900403",
		"Nam",
		"2008-08-19",
		"079308081903",
		8.4,
		8.6,
		7.0,
		24.0,
		"Bùi Văn Nam",
		"0909901403",
		"Quận 6, Thành phố Hồ Chí Minh",
		"Hồ sơ mới, cần tư vấn thêm về ngành học và phương thức xét tuyển.",
	),
	_scenario(
		"student-04",
		"Lê Ngọc Mai",
		"lead-assignment.student04@example.test",
		"0909900404",
		"Nữ",
		"2008-10-07",
		"079308100704",
		8.8,
		9.0,
		7.5,
		25.1,
		"Lê Văn Hùng",
		"0909901404",
		"Quận Bình Thạnh, Thành phố Hồ Chí Minh",
		"Đã xem thông tin chương trình và muốn nhận lịch tư vấn chuyên sâu.",
	),
	_scenario(
		"student-05",
		"Phạm Hoàng Nam",
		"lead-assignment.student05@example.test",
		"0909900405",
		"Nam",
		"2008-03-24",
		"079308032405",
		8.0,
		8.3,
		6.0,
		22.8,
		"Phạm Thị Hạnh",
		"0909901405",
		"Quận Tân Phú, Thành phố Hồ Chí Minh",
		"Đang so sánh chương trình đào tạo và thời gian học.",
	),
	_scenario(
		"student-06",
		"Trần Gia Hân",
		"lead-assignment.student06@example.test",
		"0909900406",
		"Nữ",
		"2008-07-16",
		"079308071606",
		8.6,
		8.8,
		7.0,
		24.4,
		"Trần Quốc Dũng",
		"0909901406",
		"Thành phố Thủ Đức, Thành phố Hồ Chí Minh",
		"Quan tâm học bổng và cần checklist hồ sơ đăng ký.",
	),
	_scenario(
		"student-07",
		"Đặng Minh Khoa",
		"lead-assignment.student07@example.test",
		"0909900407",
		"Nam",
		"2008-11-03",
		"079308110307",
		8.1,
		8.4,
		6.5,
		23.0,
		"Đặng Thị Lan",
		"0909901407",
		"Quận 3, Thành phố Hồ Chí Minh",
		"Muốn được tư vấn về đầu ra và cơ hội việc làm sau tốt nghiệp.",
	),
	_scenario(
		"student-08",
		"Nguyễn Phương Thảo",
		"lead-assignment.student08@example.test",
		"0909900408",
		"Nữ",
		"2008-12-21",
		"079308122108",
		8.9,
		9.1,
		7.5,
		25.4,
		"Nguyễn Thanh Sơn",
		"0909901408",
		"Quận 7, Thành phố Hồ Chí Minh",
		"Đã hoàn tất biểu mẫu tư vấn và chờ nhân sự phụ trách liên hệ.",
	),
	_scenario(
		"student-09",
		"Hoàng Tuấn Kiệt",
		"lead-assignment.student09@example.test",
		"0909900409",
		"Nam",
		"2008-01-29",
		"079308012909",
		7.8,
		8.0,
		6.0,
		22.1,
		"Hoàng Thị Hương",
		"0909901409",
		"Quận 11, Thành phố Hồ Chí Minh",
		"Hồ sơ dùng để kiểm tra nhánh cần bổ sung thông tin cơ sở.",
	),
	_scenario(
		"student-10",
		"Phan Nhật Vy",
		"lead-assignment.student10@example.test",
		"0909900410",
		"Nữ",
		"2008-09-14",
		"079308091410",
		8.3,
		8.5,
		6.5,
		23.6,
		"Phan Minh Tâm",
		"0909901410",
		"Quận 1, Thành phố Hồ Chí Minh",
		"Hồ sơ dùng để kiểm tra nhánh cần xử lý thủ công.",
	),
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


def _ensure_review_variants(students: list[str]) -> None:
	"""Leave two profiles without a branch to exercise manual review after preview."""
	for student in students[-2:]:
		doc = frappe.get_doc("CRM Lead", student)
		if doc.branch:
			doc.branch = None
			doc.save(ignore_permissions=True)


def _ensure_student_profile(
	spec: SalesAccountSeed,
	context: dict[str, Any],
	pool: str,
	team: str,
	scenario: dict[str, Any],
) -> str:
	"""Create a Lead directly so this fixture does not depend on intake side effects."""
	source_id = f"{spec.namespace}:{scenario['key']}"
	student = frappe.db.get_value("CRM Lead", {"import_source_id": source_id}, "name")
	student = student or frappe.db.get_value("CRM Lead", {"email": scenario["email"]}, "name")
	if not student:
		student = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": scenario["student_name"],
				"phone": scenario["phone"],
				"email": scenario["email"],
				"gender": scenario["gender"],
				"date_of_birth": scenario["date_of_birth"],
				"processing_status": "NEW",
				"resolution": "PENDING",
				"conversion_status": "Not Ready",
				"lifecycle_stage": "Lead",
				"owning_team": team,
				"owning_pool": pool,
				"import_source_id": source_id,
			}
		).insert(ignore_permissions=True)
		student = student.name

	previous_lifecycle_flag = getattr(frappe.flags, "student_lifecycle_service", False)
	frappe.flags.student_lifecycle_service = True
	try:
		seed_ctv_sale._complete_student_profile(spec, context, student, scenario)
	finally:
		frappe.flags.student_lifecycle_service = previous_lifecycle_flag
	frappe.db.set_value(
		"CRM Lead",
		student,
		{"owning_team": team, "owning_pool": pool, "import_source_id": source_id},
		update_modified=False,
	)
	return student


def _ensure_batch(student_ids: list[str], pool: str) -> dict[str, Any]:
	existing = frappe.db.exists("CRM Lead Assignment Batch", BATCH_NAME)
	if existing:
		batch = frappe.get_doc("CRM Lead Assignment Batch", existing)
		if batch.description != BATCH_DESCRIPTION:
			batch.description = BATCH_DESCRIPTION
			batch.save(ignore_permissions=True)
		return lead_assignment_batch._serialize_batch(batch)

	return lead_assignment_batch.create_lead_assignment_batch(
		batch_name=BATCH_NAME,
		lead_ids=student_ids,
		pool=pool,
		source="crm-demo-lead-assignment-batch",
		description=BATCH_DESCRIPTION,
	)


def execute() -> dict[str, Any]:
	"""Create ten local student profiles and one draft assignment batch."""
	seed_showcase._assert_local_site()
	seed_showcase.ensure_local_integrity_keys()
	seed_showcase.ensure_demo_config()
	frappe.set_user("Administrator")

	with seed_showcase._temporary_local_flags():
		context = seed_ctv_sale.seed_demo._bootstrap()
		seed_showcase._ensure_lifecycle_statuses()
		department = seed_ctv_sale.seed_staff._ensure_fixture_department(context["campus"])
		team = seed_ctv_sale.seed_staff._ensure_fixture_sales_team(context["campus"])
		pool = seed_ctv_sale.seed_staff._ensure_fixture_student_pool(team)
		seed_ctv_sale._ensure_user(SEED_SPEC)
		staff_name = seed_ctv_sale._ensure_staff(SEED_SPEC, context["campus"], department)
		seed_ctv_sale._ensure_team_membership(SEED_SPEC, staff_name, team)
		seed_showcase._ensure_policies(context["campus"], pool)
		frappe.db.commit()

		student_ids = [
			_ensure_student_profile(SEED_SPEC, context, pool, team, scenario)
			for scenario in STUDENT_SCENARIOS
		]
		frappe.db.commit()
		_ensure_review_variants(student_ids)
		batch = _ensure_batch(student_ids, pool)
		frappe.db.commit()

	return {
		"namespace": NAMESPACE,
		"batch": batch,
		"students": student_ids,
		"count": len(student_ids),
		"note": "Đợt đang ở trạng thái Nháp. Mở dashboard, kiểm tra trước rồi chạy phân công.",
	}


def reset() -> dict[str, Any]:
	"""Return this local fixture to a draft batch for another walkthrough."""
	seed_showcase._assert_local_site()
	seed_showcase.ensure_local_integrity_keys()
	seed_showcase.ensure_demo_config()
	frappe.set_user("Administrator")

	batch_name = frappe.db.exists("CRM Lead Assignment Batch", BATCH_NAME)
	if not batch_name:
		return {"batch": None, "count": 0}

	with seed_showcase._temporary_local_flags():
		batch = frappe.get_doc("CRM Lead Assignment Batch", batch_name)
		for item in batch.items:
			lead = frappe.get_doc("CRM Lead", item.lead)
			frappe.db.set_value(
				"CRM Lead",
				lead.name,
				{
					"processing_status": "NEW",
					"resolution": "PENDING",
					"resolution_reason": None,
					"matched_student": None,
				},
				update_modified=False,
			)
			lead_assignment_batch._reset_item(item)
			item.execution_id = None
			item.ownership_revision = int(lead.get("ownership_revision") or 0)
		batch.status = "draft"
		batch.execution_id = None
		batch.started_at = None
		batch.completed_at = None
		batch.save(ignore_permissions=True)
		frappe.db.commit()

	return {
		"batch": lead_assignment_batch._serialize_batch(batch),
		"count": len(batch.items),
		"note": "Đợt đã được đưa về trạng thái Nháp để kiểm tra lại luồng.",
	}
