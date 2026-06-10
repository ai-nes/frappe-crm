import frappe


def execute():
	workspace = frappe.get_doc("Workspace", "Frappe CRM")

	for link in workspace.links:
		if link.link_to == "CRM Enrollment Status":
			return

	school_type_idx = None
	for i, link in enumerate(workspace.links):
		if link.link_to == "CRM School Type":
			school_type_idx = i
			break

	insert_pos = school_type_idx + 1 if school_type_idx is not None else len(workspace.links)

	workspace.links.insert(
		insert_pos,
		{
			"dependencies": "",
			"hidden": 0,
			"is_query_report": 0,
			"label": "Enrollment Statuses",
			"link_count": 0,
			"link_to": "CRM Enrollment Status",
			"link_type": "DocType",
			"onboard": 0,
			"type": "Link",
		},
	)

	workspace.save(ignore_permissions=True)
	frappe.db.commit()
