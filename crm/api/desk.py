"""CRM access controls for Frappe Desk workspaces."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.desk.desktop import get_desktop_page as _get_desktop_page
from frappe.utils import has_common


def _may_read_workspace(workspace) -> bool:
	allowed_roles = [row.role for row in workspace.roles]
	if not allowed_roles:
		return True
	user_roles = frappe.get_roles()
	return "Workspace Manager" in user_roles or has_common(user_roles, allowed_roles)


@frappe.whitelist()
@frappe.read_only()
def get_desktop_page(page: str):
	"""Enforce Workspace roles before loading Desk content by direct URL."""
	page_data = frappe.parse_json(page)
	workspace_name = page_data.get("name") if isinstance(page_data, dict) else None
	if workspace_name:
		workspace = frappe.get_cached_doc("Workspace", workspace_name)
		if not _may_read_workspace(workspace):
			frappe.throw(_("You do not have permission to access this workspace."), frappe.PermissionError)
	return _get_desktop_page(page)
