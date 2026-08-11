import frappe

# Stub importer for the old->new Vietnam province merger list (2025).
# Not seeded with data — CRM Province Mapping ships empty until the user supplies
# the list. Call `import_mapping` once with [(old_province_name, new_province_name), ...].


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
		if frappe.db.exists("CRM Province Mapping", old_province):
			frappe.db.set_value("CRM Province Mapping", old_province, "new_province", new_province)
		else:
			frappe.get_doc(
				{
					"doctype": "CRM Province Mapping",
					"old_province": old_province,
					"new_province": new_province,
				}
			).insert(ignore_permissions=True)
		created.append(old_province)

	frappe.db.commit()
	return {"created": created, "skipped": skipped}
