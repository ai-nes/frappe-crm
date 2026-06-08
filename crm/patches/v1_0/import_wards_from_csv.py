"""
One-time patch: import CRM Ward records from CSV.
CSV columns: Mã Phường/ Xã, Tên, Tỉnh / Thành Phố (province_name)
"""

import csv
import os
import frappe


def execute():
	csv_path = os.path.join(
		frappe.get_app_path("crm"), "..", "..", "docs", "CRM Ward.csv"
	)
	if not os.path.exists(csv_path):
		frappe.log_error("CRM Ward CSV not found", csv_path)
		return

	# Build case-insensitive province_name → code mapping
	provinces = frappe.db.get_all("CRM Province", fields=["name", "province_name"])
	name_to_code = {p.province_name.lower().strip(): p.name for p in provinces}

	inserted = 0
	skipped = 0
	errors = []

	with open(csv_path, encoding="utf-8") as f:
		reader = csv.DictReader(f)
		for row in reader:
			ward_code = row.get("Mã Phường/ Xã", "").strip()
			ward_name = row.get("Tên", "").strip()
			province_raw = row.get("Tỉnh / Thành Phố", "").strip()

			if not ward_code or not ward_name or not province_raw:
				continue

			province_code = name_to_code.get(province_raw.lower())
			if not province_code:
				errors.append(f"Province not found: {province_raw!r}")
				continue

			if frappe.db.exists("CRM Ward", ward_code):
				skipped += 1
				continue

			try:
				frappe.get_doc({
					"doctype": "CRM Ward",
					"ward_code": ward_code,
					"ward_name": ward_name,
					"province": province_code,
				}).insert(ignore_permissions=True)
				inserted += 1
			except Exception as e:
				errors.append(f"{ward_code}: {e}")

	frappe.db.commit()

	summary = f"Import done: {inserted} inserted, {skipped} skipped"
	if errors:
		summary += f", {len(errors)} errors: {errors[:5]}"
	print(summary)
