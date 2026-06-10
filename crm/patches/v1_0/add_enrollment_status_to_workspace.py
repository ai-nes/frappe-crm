import frappe


def execute():
	workspace = frappe.get_doc("Workspace", "Frappe CRM")

	for link in workspace.links:
		if link.link_to == "CRM Enrollment Status":
			return

	workspace.append(
		"links",
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

	# Move to right after CRM School Type if it exists
	school_type_idx = next(
		(i for i, l in enumerate(workspace.links) if l.link_to == "CRM School Type"), None
	)
	if school_type_idx is not None:
		new_row = workspace.links.pop()
		workspace.links.insert(school_type_idx + 1, new_row)

	workspace.save(ignore_permissions=True)
	frappe.db.commit()
