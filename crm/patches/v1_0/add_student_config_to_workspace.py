import frappe


def execute():
	workspace = frappe.get_doc("Workspace", "Frappe CRM")

	_ensure_link(
		workspace,
		label="Education Programs",
		link_to="CRM Education Program",
		after_link_to="CRM Admission Year",
	)
	_ensure_link(
		workspace,
		label="Enrollment Statuses",
		link_to="CRM Term",
		after_link_to="CRM High School",
	)

	workspace.save(ignore_permissions=True)
	frappe.db.commit()


def _ensure_link(workspace, label, link_to, after_link_to=None):
	for link in workspace.links:
		if link.link_to == link_to:
			return

	workspace.append(
		"links",
		{
			"dependencies": "",
			"hidden": 0,
			"is_query_report": 0,
			"label": label,
			"link_count": 0,
			"link_to": link_to,
			"link_type": "DocType",
			"onboard": 0,
			"type": "Link",
		},
	)

	if not after_link_to:
		return

	after_idx = next(
		(i for i, link in enumerate(workspace.links) if link.link_to == after_link_to),
		None,
	)
	if after_idx is None:
		return

	new_row = workspace.links.pop()
	workspace.links.insert(after_idx + 1, new_row)
