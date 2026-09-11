"""Seed the first active admission profile catalog used by Student 360."""

import frappe

METHODS = (
	("THPT_SCORE", "Xét điểm thi tốt nghiệp THPT", 10),
	("DIRECT_ADMISSION", "Tuyển thẳng", 20),
)

DOCUMENT_TYPES = (
	("ENROLLMENT_FORM", "Phiếu nhập học", "education"),
	("STUDENT_PHOTO_3X4", "01 Ảnh 3×4 hoặc bản scan ảnh 3×4", "photo"),
	("HIGH_SCHOOL_TRANSCRIPT", "01 Bản sao chứng thực Học bạ THPT (đủ 3 năm)", "education"),
	("BIRTH_CERTIFICATE", "01 Bản sao chứng thực Giấy khai sinh", "identity"),
	("IDENTITY_CARD", "01 Bản sao chứng thực Căn cước/CCCD", "identity"),
	("PASSPORT", "01 Bản sao chứng thực Hộ chiếu", "identity"),
	("HIGH_SCHOOL_DIPLOMA", "01 Bản sao chứng thực Bằng tốt nghiệp THPT", "education"),
	(
		"HIGH_SCHOOL_GRADUATION_TEMPORARY_CERTIFICATE",
		"01 Bản sao Giấy chứng nhận tốt nghiệp THPT tạm thời (trong đó có điểm thi)",
		"education",
	),
	(
		"THPT_EXAM_RESULT_CERTIFICATE",
		"01 Bản sao chứng thực Giấy chứng nhận kết quả kỳ thi tốt nghiệp THPT đối với thí sinh tốt nghiệp năm 2026 (Sinh viên cần nộp bổ sung 01 Bản sao chứng thực Bằng tốt nghiệp THPT trong vòng 1 năm kể từ ngày bắt đầu học)",
		"education",
	),
	(
		"THPT_SCORE_CONFIRMATION",
		"Bản sao chứng thực Giấy chứng nhận kết quả thi THPT hoặc Bản sao chứng thực Giấy chứng nhận kết quả kỳ thi tốt nghiệp THPT; Bản sao Giấy chứng nhận tốt nghiệp THPT tạm thời (trong đó có điểm thi); Xác nhận điểm của Sở Giáo dục và Đào tạo hoặc của trường THPT (Giấy tờ khác này chỉ áp dụng đối với thí sinh nhập học dùng kết quả thi tốt nghiệp THPT các năm trước năm 2026)",
		"education",
	),
	(
		"INTERNATIONAL_PROGRAM_DIPLOMA",
		"01 Bản sao chứng thực Bằng tốt nghiệp Chương trình APTECH HDSE/APTECH ADSE/ARENA ADIM/SKILLKING/JETKING/BTEC HND/Melbourne Polytechnic/FUNiX Software Engineering",
		"education",
	),
	(
		"FIRST_GENERATION_PRIORITY_FORM",
		"Đơn đăng ký ưu tiên xét tuyển thế hệ 1 (Dành cho đối tượng Thế hệ 1)",
		"special_program",
	),
	(
		"FPT_POLYTECHNIC_DIPLOMA",
		"01 Bản sao chứng thực Bằng tốt nghiệp Cao đẳng FPT Polytechnic",
		"special_program",
	),
	(
		"ACHIEVEMENT_PROOF",
		"01 Bản sao chứng thực giấy tờ chứng minh thành tích khác",
		"special_program",
	),
	(
		"ENGLISH_SCORE_CONVERSION_CERTIFICATE",
		"01 Bản sao chứng thực Chứng chỉ ngoại ngữ (áp dụng đối với thí sinh dùng chứng chỉ ngoại ngữ để quy đổi thành điểm môn ngoại ngữ hoặc để tính điểm khuyến khích)",
		"language",
	),
	(
		"ENGLISH_EXEMPTION_CERTIFICATE",
		"01 Bản sao công chứng Chứng chỉ tiếng Anh còn thời hạn (nếu có) để xét miễn chương trình tiếng Anh dự bị theo quy định của Trường Đại học FPT",
		"language",
	),
	(
		"SCHOLARSHIP_ACHIEVEMENT_PROOF",
		"01 Bản sao chứng thực giấy tờ xác nhận thành tích (chỉ áp dụng đối với diện học bổng)",
		"scholarship",
	),
	(
		"STUDY_NOW_PAY_LATER_APPLICATION",
		"Đơn đề nghị tham gia chương trình Học trước – Trả sau do phụ huynh hoặc người giám hộ (sau đây gọi chung là phụ huynh) làm, được Trường nơi thí sinh đang học xác nhận (chỉ áp dụng đối với diện Học trước – Trả sau)",
		"special_program",
	),
	(
		"STUDY_NOW_PAY_LATER_AGREEMENT",
		"01 Thoả thuận Học trước – Trả sau (chỉ áp dụng đối với diện Học trước – Trả sau)",
		"special_program",
	),
	(
		"FINANCIAL_HARDSHIP_PROOF",
		"01 Bản gốc minh chứng về hoàn cảnh gia đình khó khăn như xác nhận hộ nghèo của địa phương/xác nhận thu nhập phụ huynh của đơn vị nơi đang công tác/Quyết toán thuế TNCN của phụ huynh năm gần nhất (nếu có, chỉ áp dụng đối với diện Học trước – Trả sau)",
		"special_program",
	),
	(
		"FAMILY_RELATIONSHIP_PROOF",
		"01 Giấy tờ xác nhận quan hệ của thí sinh với phụ huynh (áp dụng đối với diện Ưu đãi học phí cho thí sinh có anh/chị/em ruột theo học FE/con ruột CBNV FPT)",
		"special_program",
	),
	(
		"SIBLING_BIRTH_CERTIFICATE",
		"01 Bản sao chứng thực giấy khai sinh của anh/chị/em ruột thí sinh (áp dụng đối với diện Ưu đãi học phí cho thí sinh có anh/chị/em ruột theo học FE /Ưu đãi học phí cho thí sinh là con người thân là anh/chị/em ruột đang làm việc tại FE)",
		"special_program",
	),
	(
		"PARENT_IDENTITY_DOCUMENT",
		"01 Bản sao chứng thực Căn cước/CCCD của phụ huynh (áp dụng đối với diện Ưu đãi học phí cho thí sinh có anh/chị/em ruột theo học FE; người thân làm tại FE; con ruột CBNV FPT)",
		"special_program",
	),
	(
		"FAMILY_EMPLOYMENT_PROOF",
		"Bản gốc Giấy xác nhận anh/chị/em ruột đang theo học FE (áp dụng đối với diện Ưu đãi học phí cho thí sinh có anh/chị/em ruột theo học FE) hoặc Giấy xác nhận đang làm việc tại FE/FPT (áp dụng đối với diện Ưu đãi học phí cho thí sinh là CBNV hoặc có người thân làm việc tại FE/con ruột CBNV FPT)",
		"special_program",
	),
)

BASE_ROWS = (
	("ENROLLMENT_FORM", "BASIC_ADMISSION", "ALL", 1, "Phiếu nhập học theo biểu mẫu của nhà trường."),
	(
		"STUDENT_PHOTO_3X4",
		"BASIC_ADMISSION",
		"ALL",
		2,
		"Ảnh 3x4 hoặc bản scan ảnh 3x4; chụp trong vòng 6 tháng gần nhất; nền sáng; nhìn thẳng.",
	),
	(
		"HIGH_SCHOOL_TRANSCRIPT",
		"BASIC_ADMISSION",
		"ALL",
		3,
		"Bản sao chứng thực học bạ THPT đủ 3 năm; file phải nhìn rõ toàn bộ các trang.",
	),
	("BIRTH_CERTIFICATE", "BASIC_ADMISSION", "ALL", 4, "Bản sao chứng thực giấy khai sinh."),
	(
		"IDENTITY_CARD",
		"IDENTITY_PROOF",
		"ANY",
		5,
		"Bản sao chứng thực CCCD; thông tin phải khớp với hồ sơ học sinh.",
	),
	(
		"PASSPORT",
		"IDENTITY_PROOF",
		"ANY",
		6,
		"Bản sao chứng thực hộ chiếu còn giá trị; được dùng thay thế CCCD.",
	),
	("HIGH_SCHOOL_DIPLOMA", "GRADUATION_PROOF", "ANY", 7, "Bản sao chứng thực bằng tốt nghiệp THPT."),
	(
		"HIGH_SCHOOL_GRADUATION_TEMPORARY_CERTIFICATE",
		"GRADUATION_PROOF",
		"ANY",
		8,
		"Giấy chứng nhận tốt nghiệp THPT tạm thời.",
	),
)

THPT_RESULT_ROWS = (
	(
		"THPT_EXAM_RESULT_CERTIFICATE",
		"THPT_RESULT",
		"ANY",
		20,
		"Giấy chứng nhận kết quả kỳ thi tốt nghiệp THPT.",
	),
	("THPT_SCORE_CONFIRMATION", "THPT_RESULT", "ANY", 21, "Xác nhận điểm của Sở Giáo dục và Đào tạo."),
)

SPECIAL_PROFILE_ROWS = {
	"FIRST_GENERATION": (
		(
			"FIRST_GENERATION_PRIORITY_FORM",
			"FIRST_GENERATION",
			"ALL",
			30,
			"Đơn đăng ký ưu tiên xét tuyển thế hệ 1.",
		),
	),
	"LANGUAGE_CERTIFICATE": (
		(
			"ENGLISH_SCORE_CONVERSION_CERTIFICATE",
			"LANGUAGE_CERTIFICATE",
			"ALL",
			31,
			"Chứng chỉ ngoại ngữ dùng để quy đổi điểm.",
		),
		(
			"ENGLISH_EXEMPTION_CERTIFICATE",
			"LANGUAGE_CERTIFICATE",
			"ALL",
			32,
			"Chứng chỉ tiếng Anh còn thời hạn để miễn chương trình dự bị.",
		),
	),
	"INTERNATIONAL_PROGRAM": (
		(
			"INTERNATIONAL_PROGRAM_DIPLOMA",
			"INTERNATIONAL_PROGRAM",
			"ALL",
			33,
			"Bằng tốt nghiệp chương trình quốc tế.",
		),
	),
	"FPT_POLYTECHNIC": (
		(
			"FPT_POLYTECHNIC_DIPLOMA",
			"FPT_POLYTECHNIC",
			"ALL",
			34,
			"Bằng tốt nghiệp Cao đẳng FPT Polytechnic.",
		),
	),
	"ACHIEVEMENT": (("ACHIEVEMENT_PROOF", "ACHIEVEMENT", "ALL", 35, "Giấy tờ chứng minh thành tích khác."),),
	"STUDY_NOW_PAY_LATER": (
		(
			"STUDY_NOW_PAY_LATER_APPLICATION",
			"STUDY_NOW_PAY_LATER",
			"ALL",
			36,
			"Đơn đề nghị Học trước – Trả sau.",
		),
		(
			"STUDY_NOW_PAY_LATER_AGREEMENT",
			"STUDY_NOW_PAY_LATER",
			"ALL",
			37,
			"Thỏa thuận Học trước – Trả sau.",
		),
		(
			"FINANCIAL_HARDSHIP_PROOF",
			"STUDY_NOW_PAY_LATER",
			"ALL",
			38,
			"Minh chứng hoàn cảnh gia đình khó khăn.",
		),
	),
	"FAMILY_FE_FPT": (
		("FAMILY_RELATIONSHIP_PROOF", "FAMILY_FE_FPT", "ALL", 39, "Giấy tờ xác nhận quan hệ với người thân."),
		("SIBLING_BIRTH_CERTIFICATE", "FAMILY_FE_FPT", "ALL", 40, "Giấy khai sinh của anh/chị/em ruột."),
		("PARENT_IDENTITY_DOCUMENT", "FAMILY_FE_FPT", "ALL", 41, "CCCD của người thân."),
		(
			"FAMILY_EMPLOYMENT_PROOF",
			"FAMILY_FE_FPT",
			"ALL",
			42,
			"Xác nhận người thân đang học/làm việc tại FE/FPT.",
		),
	),
	"SCHOLARSHIP": (
		("SCHOLARSHIP_ACHIEVEMENT_PROOF", "SCHOLARSHIP", "ALL", 43, "Giấy tờ xác nhận thành tích học bổng."),
	),
}

SPECIAL_PROFILE_DEFINITIONS = (
	("FIRST_GENERATION", "Xét tuyển theo thế hệ 1"),
	("LANGUAGE_CERTIFICATE", "Xét có chứng chỉ ngoại ngữ"),
	("INTERNATIONAL_PROGRAM", "Xét có bằng tốt nghiệp chương trình quốc tế"),
	("FPT_POLYTECHNIC", "Xét có bằng tốt nghiệp Cao đẳng FPT Polytechnic"),
	("ACHIEVEMENT", "Xét giấy tờ các thành tích khác"),
	("STUDY_NOW_PAY_LATER", "Xét diện Học trước – Trả sau"),
	("FAMILY_FE_FPT", "Diện ưu đãi học phí người thân FE/FPT"),
	("SCHOLARSHIP", "Diện học bổng"),
)


def _condition(method: str | None) -> str | None:
	return f"field:application.admission_method={method}" if method else None


def _document_type_reference(code: str) -> str:
	return frappe.db.get_value("CRM Document Type", {"code": code}, "name") or code


def _rows(template_code: str) -> list[dict]:
	rows = []
	if template_code == "STANDARD":
		rows.extend(
			{
				"doctype": "CRM Profile Template Document Type",
				"section_code": "basic_admission",
				"document_type": _document_type_reference(document_type),
				"requirement_group": group,
				"requirement_mode": mode,
				"is_required": 1,
				"min_required": 1,
				"quantity": 1,
				"order_display": order,
				"instruction": instruction,
			}
			for document_type, group, mode, order, instruction in BASE_ROWS
		)
	if template_code == "STANDARD":
		for document_type, group, mode, order, instruction in THPT_RESULT_ROWS:
			rows.append(
				{
					"doctype": "CRM Profile Template Document Type",
					"section_code": "method",
					"document_type": _document_type_reference(document_type),
					"requirement_group": group,
					"requirement_mode": mode,
					"is_required": 1,
					"min_required": 1,
					"quantity": 1,
					"order_display": order,
					"condition_key": _condition("THPT_SCORE"),
					"instruction": instruction,
				}
			)
	for document_type, group, mode, order, instruction in SPECIAL_PROFILE_ROWS.get(template_code, ()):
		rows.append(
			{
				"doctype": "CRM Profile Template Document Type",
				"section_code": "special_program",
				"document_type": _document_type_reference(document_type),
				"requirement_group": group,
				"requirement_mode": mode,
				"is_required": 1,
				"min_required": 1,
				"quantity": 1,
				"order_display": order,
				"instruction": instruction,
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
		document_type_name = frappe.db.get_value("CRM Document Type", {"code": code}, "name")
		if document_type_name:
			frappe.db.set_value(
				"CRM Document Type",
				document_type_name,
				{"label": label, "category": category},
				update_modified=False,
			)
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

	for code, name, template_kind in (
		("STANDARD", "Hồ sơ thông thường", "standard"),
		*[(code, name, "special") for code, name in SPECIAL_PROFILE_DEFINITIONS],
	):
		template_name = frappe.db.get_value("CRM Admission Profile Template", {"template_code": code}, "name")
		if template_name:
			if code == "STANDARD":
				frappe.db.set_value(
					"CRM Admission Profile Template",
					template_name,
					{"template_name": name, "description": name},
					update_modified=False,
				)
			continue
		frappe.get_doc(
			{
				"doctype": "CRM Admission Profile Template",
				"template_code": code,
				"template_name": name,
				"template_kind": template_kind,
				"profile_type": "academic_admission",
				"status": "Active",
				"version": 1,
				"description": name,
				"document_types": _rows(code),
			}
		).insert(ignore_permissions=True)
