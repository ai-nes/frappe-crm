"""Seed the first active admission profile catalog used by Student 360."""

import frappe

METHODS = (
	("THPT_SCORE", "Xét điểm thi tốt nghiệp THPT", 10),
	("DIRECT_ADMISSION", "Tuyển thẳng", 20),
)

DOCUMENT_TYPES = (
	("ENROLLMENT_FORM", "Phiếu nhập học", "education"),
	("STUDENT_PHOTO_3X4", "Ảnh 3x4 hoặc bản scan ảnh 3x4", "photo"),
	("HIGH_SCHOOL_TRANSCRIPT", "Bản sao chứng thực Học bạ THPT đủ 3 năm", "education"),
	("BIRTH_CERTIFICATE", "Bản sao chứng thực Giấy khai sinh", "identity"),
	("IDENTITY_CARD", "Bản sao chứng thực Căn cước/CCCD", "identity"),
	("PASSPORT", "Bản sao chứng thực Hộ chiếu", "identity"),
	("HIGH_SCHOOL_DIPLOMA", "Bản sao chứng thực Bằng tốt nghiệp THPT", "education"),
	("THPT_EXAM_RESULT_CERTIFICATE", "Giấy chứng nhận kết quả kỳ thi tốt nghiệp THPT", "education"),
	("PREVIOUS_THPT_EXAM_RESULT", "Minh chứng kết quả thi THPT các năm trước", "education"),
	("LANGUAGE_CERTIFICATE", "Chứng chỉ ngoại ngữ", "language"),
	("FIRST_GENERATION_PRIORITY_FORM", "Đơn đăng ký ưu tiên xét tuyển thế hệ 1", "special_program"),
	("VOCATIONAL_PROGRAM_DIPLOMA", "Bằng tốt nghiệp chương trình đối tác", "special_program"),
	("FPT_POLYTECHNIC_DIPLOMA", "Bằng tốt nghiệp Cao đẳng FPT Polytechnic", "special_program"),
	("ACHIEVEMENT_PROOF", "Giấy tờ chứng minh thành tích khác", "special_program"),
	("SCHOLARSHIP_ACHIEVEMENT_PROOF", "Giấy tờ xác nhận thành tích học bổng", "scholarship"),
	("ENGLISH_EXEMPTION_CERTIFICATE", "Chứng chỉ tiếng Anh còn thời hạn", "language"),
	("STUDY_NOW_PAY_LATER_APPLICATION", "Đơn đề nghị Học trước – Trả sau", "special_program"),
	("STUDY_NOW_PAY_LATER_AGREEMENT", "Thỏa thuận Học trước – Trả sau", "special_program"),
	("FINANCIAL_HARDSHIP_PROOF", "Minh chứng hoàn cảnh gia đình khó khăn", "special_program"),
	("FAMILY_RELATIONSHIP_PROOF", "Giấy tờ xác nhận quan hệ với phụ huynh", "special_program"),
	("SIBLING_BIRTH_CERTIFICATE", "Giấy khai sinh của anh/chị/em ruột", "special_program"),
	("PARENT_IDENTITY_DOCUMENT", "CCCD của phụ huynh", "special_program"),
	("FAMILY_EMPLOYMENT_PROOF", "Xác nhận người thân đang học/làm việc tại FE/FPT", "special_program"),
)

BASE_ROWS = (
	("ENROLLMENT_FORM", "BASIC_ADMISSION", "ALL", 1, "Phiếu nhập học theo biểu mẫu của nhà trường."),
	("STUDENT_PHOTO_3X4", "BASIC_ADMISSION", "ALL", 2, "Ảnh 3x4 hoặc bản scan ảnh 3x4; chụp trong vòng 6 tháng gần nhất; nền sáng; nhìn thẳng."),
	("HIGH_SCHOOL_TRANSCRIPT", "BASIC_ADMISSION", "ALL", 3, "Bản sao chứng thực học bạ THPT đủ 3 năm; file phải nhìn rõ toàn bộ các trang."),
	("BIRTH_CERTIFICATE", "BASIC_ADMISSION", "ALL", 4, "Bản sao chứng thực giấy khai sinh."),
	("IDENTITY_CARD", "IDENTITY_PROOF", "ANY", 5, "Bản sao chứng thực CCCD; thông tin phải khớp với hồ sơ học sinh."),
	("PASSPORT", "IDENTITY_PROOF", "ANY", 6, "Bản sao chứng thực hộ chiếu còn giá trị; được dùng thay thế CCCD."),
	("HIGH_SCHOOL_DIPLOMA", "GRADUATION_PROOF", "ANY", 7, "Bản sao chứng thực bằng tốt nghiệp THPT."),
	("THPT_EXAM_RESULT_CERTIFICATE", "GRADUATION_PROOF", "ANY", 8, "Giấy chứng nhận kết quả kỳ thi tốt nghiệp THPT; bổ sung bằng tốt nghiệp theo chính sách."),
)

THPT_ROWS = (
	("PREVIOUS_THPT_EXAM_RESULT", "THPT_SCORE", "ALL", 20),
	("LANGUAGE_CERTIFICATE", "THPT_SCORE", "ALL", 21),
)

SPECIAL_ROWS = (
	("FIRST_GENERATION_PRIORITY_FORM", "SPECIAL_PROGRAM", "ALL", 30),
	("STUDY_NOW_PAY_LATER_APPLICATION", "SPECIAL_PROGRAM", "ALL", 31),
	("STUDY_NOW_PAY_LATER_AGREEMENT", "SPECIAL_PROGRAM", "ALL", 32),
	("FINANCIAL_HARDSHIP_PROOF", "SPECIAL_PROGRAM", "ALL", 33),
	("FAMILY_RELATIONSHIP_PROOF", "SPECIAL_PROGRAM", "ALL", 34),
	("SIBLING_BIRTH_CERTIFICATE", "SPECIAL_PROGRAM", "ALL", 35),
	("PARENT_IDENTITY_DOCUMENT", "SPECIAL_PROGRAM", "ALL", 36),
	("FAMILY_EMPLOYMENT_PROOF", "SPECIAL_PROGRAM", "ALL", 37),
)

SCHOLARSHIP_ROWS = (
	("SCHOLARSHIP_ACHIEVEMENT_PROOF", "SCHOLARSHIP", "ALL", 40),
)


def _condition(method: str | None) -> str | None:
	return f"field:application.admission_method={method}" if method else None


def _rows(template_code: str) -> list[dict]:
	rows = [
		{
			"doctype": "CRM Profile Template Document Type",
			"section_code": "basic_admission",
			"document_type": document_type,
			"requirement_group": group,
			"requirement_mode": mode,
			"is_required": 1,
			"min_required": 1,
			"quantity": 1,
			"order_display": order,
			"instruction": instruction,
		}
		for document_type, group, mode, order, instruction in BASE_ROWS
	]
	for document_type, group, mode, order in THPT_ROWS:
		rows.append(
			{
				"doctype": "CRM Profile Template Document Type",
				"section_code": "method",
				"document_type": document_type,
				"requirement_group": group,
				"requirement_mode": mode,
				"is_required": 0,
				"min_required": 1,
				"quantity": 1,
				"order_display": order,
				"condition_key": _condition("THPT_SCORE"),
			}
		)
	for document_type, group, mode, order in SPECIAL_ROWS:
		if template_code == "SPECIAL_PROGRAM":
			rows.append(
				{
					"doctype": "CRM Profile Template Document Type",
					"section_code": "special_program",
					"document_type": document_type,
					"requirement_group": group,
					"requirement_mode": mode,
					"is_required": 0,
					"min_required": 1,
					"quantity": 1,
					"order_display": order,
				}
			)
	for document_type, group, mode, order in SCHOLARSHIP_ROWS:
		if template_code == "SCHOLARSHIP":
			rows.append(
				{
					"doctype": "CRM Profile Template Document Type",
					"section_code": "scholarship",
					"document_type": document_type,
					"requirement_group": group,
					"requirement_mode": mode,
					"is_required": 1,
					"min_required": 1,
					"quantity": 1,
					"order_display": order,
				}
			)
	# A direct-admission application temporarily exposes the whole catalog.
	used = {row["document_type"] for row in rows}
	for offset, (document_type, _label, _category) in enumerate(DOCUMENT_TYPES, start=100):
		if document_type in used:
			continue
		rows.append(
			{
				"doctype": "CRM Profile Template Document Type",
				"section_code": "direct_admission",
				"document_type": document_type,
				"requirement_group": f"direct:{document_type}",
				"requirement_mode": "ALL",
				"is_required": 0,
				"min_required": 1,
				"quantity": 1,
				"order_display": offset,
				"condition_key": _condition("DIRECT_ADMISSION"),
			}
		)
	return rows


def execute() -> None:
	for code, display_name, sort_order in METHODS:
		if not frappe.db.exists("CRM Admission Method", code):
			frappe.get_doc(
				{
					"doctype": "CRM Admission Method",
					"code": code,
					"display_name": display_name,
					"enabled": 1,
					"sort_order": sort_order,
				}
			).insert(ignore_permissions=True)

	for code, label, category in DOCUMENT_TYPES:
		if frappe.db.exists("CRM Document Type", {"code": code}):
			continue
		frappe.get_doc(
			{
				"doctype": "CRM Document Type",
				"code": code,
				"label": label,
				"category": category,
				"status": "Active",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	for code, name in (
		("STANDARD", "Hồ sơ nhập học tiêu chuẩn"),
		("SCHOLARSHIP", "Hồ sơ nhập học có học bổng"),
		("SPECIAL_PROGRAM", "Hồ sơ nhập học diện đặc biệt"),
	):
		if frappe.db.exists("CRM Admission Profile Template", {"template_code": code}):
			continue
		frappe.get_doc(
			{
				"doctype": "CRM Admission Profile Template",
				"template_code": code,
				"template_name": name,
				"profile_type": "academic_admission",
				"status": "Active",
				"version": 1,
				"description": name,
				"document_types": _rows(code),
			}
		).insert(ignore_permissions=True)
