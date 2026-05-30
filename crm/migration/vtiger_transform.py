# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# Pure transformation functions — no Frappe DB calls, fully testable.

from crm.utils import parse_phone_number


def normalize_phone(raw):
	"""Normalize Vietnamese phone number to E.164 (+84...) via phonenumbers library."""
	if not raw:
		return None
	result = parse_phone_number(str(raw).strip(), default_country="VN")
	if result.get("success") and result.get("is_valid"):
		return result["formats"]["E164"]
	return None


def build_first_name(firstname, lastname):
	"""Return a non-empty first_name — required by CRM Lead."""
	if firstname and firstname.strip():
		return firstname.strip()
	parts = (lastname or "").strip().split(" ", 1)
	return parts[0] if parts and parts[0] else "N/A"


def build_lead_name(firstname, lastname):
	parts = [p.strip() for p in [lastname, firstname] if p and p.strip()]
	return " ".join(parts) or "N/A"


def resolve_ward_province(city_id_str, frappe):
	"""city_id in vtiger_wards is varchar — match by province_name or city_number."""
	if not city_id_str:
		return None
	name = frappe.db.get_value("CRM Province", {"province_name": city_id_str}, "name")
	if name:
		return name
	return frappe.db.get_value("CRM Province", {"city_number": city_id_str}, "name")


def safe_int(value):
	try:
		return int(value) if value not in (None, "", "None") else None
	except (ValueError, TypeError):
		return None


def clean_email(email):
	if not email:
		return None
	return email.strip().lower() or None
