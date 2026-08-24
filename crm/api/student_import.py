import json

import frappe

from crm.fcrm.utils.geo_resolver import resolve_high_school_strict
from crm.fcrm.utils.link_resolver import resolve_link_strict

LEGACY_LEAD_STATUS_MAP = {
	"New": "Mới",
	"Prospect": "Có triển vọng",
	"Pending Confirmation": "Đã xác nhận",
	"Confirmed": "Đã xác nhận",
	"Enrolled": "Đã nhập học",
	"Converted": "Đã chuyển đổi",
	"Rejected": "Từ chối",
	"Refused": "Từ chối",
	"Deferred": "Từ chối",
	"Withdrawn": "Từ chối",
	"Promising": "Có triển vọng",
}

MAPPED_PAYLOAD_KEYS = {
	"firstname",
	"lastname",
	"mobile",
	"email",
	"leadsource",
	"leads_campus",
	"cf_city",
	"cf_school",
	"cf_school_code",
	"cf_major",
	"cf_nvfpt",
	"cf_registered_year",
	"leadstatus",
	"cf_kenh_quang_cao",
}

NOTE_FIELD_LABELS = {
	"annualrevenue": "Doanh thu hàng năm",
	"assigned_user_id": "ID người phụ trách",
	"city": "Quận/huyện",
	"code": "Mã bưu chính",
	"company": "Công ty",
	"country": "Quốc gia",
	"designation": "Chức danh",
	"emailoptout": "Từ chối nhận email",
	"fax": "Fax",
	"industry": "Ngành nghề",
	"lane": "Địa chỉ đường/phố",
	"noofemployees": "Số nhân viên",
	"phone": "Điện thoại bàn",
	"pobox": "Hộp thư bưu điện",
	"rating": "Đánh giá lead",
	"salutationtype": "Danh xưng",
	"secondaryemail": "Email phụ",
	"state": "Tỉnh/thành gốc",
	"website": "Website",
	"cf_kha_nang_cd": "Khả năng chuyển đổi",
	"cf_noi_hoc_lead": "Nơi học lead",
	"cf_segment": "Phân khúc",
	"cf_su_kien_tham_gia": "Sự kiện tham gia",
	"cf_tag": "Tags",
	"cf_tinh_trang_cs_nhap_hoc": "Tình trạng chăm sóc/nhập học",
}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def upsert_student(payload: dict | str | None = None) -> dict:
	"""Create or update one CRM Student from an external lead payload.

	This webhook is intentionally public for the current third-party integration.
	It bypasses document permissions, so access control must be added before using
	it with any untrusted sender.
	"""
	if payload is None:
		payload = frappe.request.get_json(silent=True)
	payload = _parse_payload(payload)
	phone = _normalize_phone(payload.get("mobile"))
	email = _normalize_email(payload.get("email"))
	if not phone and not email:
		frappe.throw("Payload phải có mobile hoặc email.", title="Thiếu định danh học sinh")

	student = _find_existing_student(phone, email)
	values = _map_payload(payload, phone, email)
	if student:
		for fieldname, value in values.items():
			student.set(fieldname, value)
		student.save(ignore_permissions=True)
		action = "updated"
	else:
		student = frappe.get_doc({"doctype": "CRM Student", **values})
		student.insert(ignore_permissions=True)
		action = "created"

	return {"name": student.name, "action": action}


def _parse_payload(payload):
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except json.JSONDecodeError:
			frappe.throw("payload phải là JSON object hợp lệ.", title="Payload không hợp lệ")
	if not isinstance(payload, dict):
		frappe.throw("payload phải là JSON object.", title="Payload không hợp lệ")
	return payload


def _normalize_phone(value):
	if not isinstance(value, str):
		return None
	phone = value.strip()
	if phone.startswith("+84"):
		phone = "0" + phone[3:]
	return phone or None


def _normalize_email(value):
	if not isinstance(value, str):
		return None
	return value.strip().lower() or None


def _find_existing_student(phone, email):
	by_phone = frappe.db.get_value("CRM Student", {"phone": phone}, "name") if phone else None
	by_email = frappe.db.get_value("CRM Student", {"email": email}, "name") if email else None
	if by_phone and by_email and by_phone != by_email:
		frappe.throw(
			"mobile và email đang thuộc về hai học sinh khác nhau.",
			title="Định danh học sinh mâu thuẫn",
		)
	return frappe.get_doc("CRM Student", by_phone or by_email) if by_phone or by_email else None


def _map_payload(payload, phone, email):
	student_name = " ".join(
		str(value).strip()
		for value in (payload.get("firstname"), payload.get("lastname"))
		if value and str(value).strip()
	)
	values = {"notes": _serialize_unmapped_payload(payload)}
	if student_name:
		values["student_name"] = student_name
	if phone:
		values["phone"] = phone
	if email:
		values["email"] = email
	if value := payload.get("leadsource"):
		values["source"] = resolve_link_strict("CRM Lead Source", value, ["source_name"])
	if value := payload.get("leads_campus"):
		values["branch"] = resolve_link_strict("CRM Campus", value, ["campus_code", "campus_name"])

	province_value = payload.get("cf_city") or payload.get("city") or payload.get("state")
	if province_value:
		values["province"] = resolve_link_strict(
			"CRM Province", province_value, ["province_code", "province_name"]
		)
	if value := payload.get("cf_school_code") or payload.get("cf_school"):
		values["high_school"] = resolve_high_school_strict(value, values.get("province"))
	if value := payload.get("cf_major"):
		values["major"] = resolve_link_strict("CRM Major", value, ["major_code", "major_name"])
	if value := payload.get("cf_nvfpt"):
		values["aspiration"] = resolve_link_strict("CRM Aspiration", value, ["aspiration_name"])
	if value := payload.get("cf_registered_year"):
		values["admission_year"] = resolve_link_strict("CRM Admission Year", value, ["year_name"])
	if value := payload.get("leadstatus"):
		status = LEGACY_LEAD_STATUS_MAP.get(value, value)
		values["enrollment_status"] = resolve_link_strict("CRM Enrollment Status", status, ["status_name"])
	if value := payload.get("cf_kenh_quang_cao"):
		values["advertising_channel"] = str(value).strip()
	return values


def _serialize_unmapped_payload(payload):
	unmapped = {key: value for key, value in payload.items() if key not in MAPPED_PAYLOAD_KEYS}
	if not unmapped:
		return ""

	lines = ["Thông tin bổ sung từ nguồn tích hợp:"]
	for key in sorted(unmapped):
		lines.append(
			f"- {NOTE_FIELD_LABELS.get(key, _format_field_label(key))}: {_format_note_value(unmapped[key])}"
		)
	return "\n".join(lines)


def _format_field_label(key):
	return key.replace("_", " ").strip().capitalize()


def _format_note_value(value):
	if isinstance(value, (dict, list)):
		return json.dumps(value, ensure_ascii=False, separators=(",", ", "))
	if value is None:
		return "Không có"
	return str(value).strip()
