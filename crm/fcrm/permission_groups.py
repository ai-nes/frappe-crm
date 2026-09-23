"""User-facing permission groups for the managed CRM DocType catalog.

The permission profile still stores one row per real Frappe DocType because
Frappe's DocPerm engine needs that shape. The admin API uses these groups to
let an administrator configure business objects instead of implementation
details such as Student Admission Profile or Student Document.
"""

PERMISSION_DOCTYPE_GROUPS = (
	{
		"document_type": "CRM Lead",
		"label": "Lead",
		"description": "Hồ sơ lead.",
		"doctypes": ("CRM Lead",),
	},
	{
		"document_type": "CRM Student",
		"label": "Học sinh",
		"description": "Bao gồm hồ sơ tuyển sinh và tài liệu của học sinh.",
		"doctypes": (
			"CRM Student",
			"CRM Student Admission Profile",
			"CRM Student Document",
		),
	},
	{
		"document_type": "CRM Major",
		"label": "Danh mục tuyển sinh",
		"description": "Ngành, trường, khu vực và các danh mục tham chiếu.",
		"doctypes": (
			"CRM Major",
			"CRM High School",
			"CRM Province",
			"CRM Ward",
			"CRM Admission Year",
			"CRM Education Program",
			"CRM Department",
			"Holiday List",
			"CRM Team",
			"CRM Lost Reason",
			"CRM Campaign Type",
			"CRM Intent Type",
			"CRM Interaction Type",
			"CRM School Type",
			"CRM School Area",
			"CRM Stakeholder Role",
			"CRM School Activity Type",
			"CRM Major Group",
			"CRM Aspiration",
			"CRM Region",
			"CRM Enrollment Status",
			"CRM Admission Method",
		),
	},
	{
		"document_type": "CRM Campaign",
		"label": "Chiến dịch tuyển sinh",
		"description": "Chiến dịch tuyển sinh.",
		"doctypes": ("CRM Campaign",),
	},
	{
		"document_type": "CRM Event",
		"label": "Sự kiện tuyển sinh",
		"description": "Sự kiện và hoạt động gắn với chiến dịch.",
		"doctypes": ("CRM Event",),
	},
	{
		"document_type": "CRM Lead Source",
		"label": "Nguồn Lead",
		"description": "Nguồn lead và nền tảng tiếp nhận.",
		"doctypes": ("CRM Lead Source", "CRM Platform"),
	},
	{
		"document_type": "CRM Campus",
		"label": "Cơ sở tuyển sinh",
		"description": "Cơ sở, mẫu hồ sơ và loại tài liệu tuyển sinh.",
		"doctypes": (
			"CRM Campus",
			"CRM Admission Profile Template",
			"CRM Document Type",
		),
	},
	{
		"document_type": "CRM Student Payment Account",
		"label": "Thông tin thanh toán",
		"description": "Dữ liệu thanh toán nhạy cảm của học sinh.",
		"doctypes": ("CRM Student Payment Account",),
	},
	{
		"document_type": "CRM Recommendation",
		"label": "Đề xuất và hành động tuyển sinh",
		"description": "Đề xuất, hành động và lịch sử quyết định liên quan.",
		"doctypes": (
			"CRM Recommendation",
			"CRM Action",
			"CRM Action Item",
			"CRM Student Decision Event",
		),
	},
	{
		"document_type": "CRM Marketing Engagement",
		"label": "Tương tác tuyển sinh",
		"description": "Bằng chứng tương tác và attribution.",
		"doctypes": ("CRM Marketing Engagement",),
	},
)

SYSTEM_PERMISSION_DOCTYPES = frozenset(
	{
		"Fields Layout",
		"Form Script",
		"View Settings",
		"Global Settings",
		"FCRM Settings",
		"Notification",
		"Dashboard",
		"Invitation",
		"Telephony Agent",
		"Service Level Agreement",
		"CRM Influence",
		"CRM Academic Year Config",
	}
)

PERMISSION_DOCTYPE_GROUP_BY_DOCTYPE = {
	doctype: group for group in PERMISSION_DOCTYPE_GROUPS for doctype in group["doctypes"]
}


def permission_group_for_doctype(document_type):
	"""Return the business-object group for a real DocType, if one exists."""
	return PERMISSION_DOCTYPE_GROUP_BY_DOCTYPE.get(document_type)


def is_system_permission_doctype(document_type):
	"""Return whether a DocType is managed by the system, not the CRM admin UI."""
	return document_type in SYSTEM_PERMISSION_DOCTYPES
