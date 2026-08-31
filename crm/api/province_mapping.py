import frappe

# Importer for the old->new Vietnam province merger list (2025).
# Names are stored as CRM Province.previous_names child rows.


@frappe.whitelist()
def import_mapping(rows):
	"""rows: list of {"old_province": ..., "new_province": ...} dicts.
	old_province must already exist as a CRM Province record."""
	frappe.only_for(("System Manager", "Administrator"))

	if isinstance(rows, str):
		import json

		rows = json.loads(rows)

	created, skipped = [], []
	for row in rows:
		old_province = row.get("old_province")
		new_province = row.get("new_province")
		if new_province:
			new_province = new_province.strip()

		if not old_province or not new_province:
			skipped.append(row)
			continue
		if not frappe.db.exists("CRM Province", old_province):
			skipped.append(row)
			continue
		new_province_name = new_province if frappe.db.exists("CRM Province", new_province) else frappe.db.get_value("CRM Province", {"province_name": new_province}, "name")
		if not new_province_name:
			skipped.append(row)
			continue
		if not frappe.db.exists("CRM Province Former Name", {"parent": new_province_name, "parentfield": "previous_names", "former_name": old_province}):
			province = frappe.get_doc("CRM Province", new_province_name)
			province.append("previous_names", {"former_name": old_province})
			province.save(ignore_permissions=True)
		created.append(old_province)

	frappe.db.commit()
	return {"created": created, "skipped": skipped}
