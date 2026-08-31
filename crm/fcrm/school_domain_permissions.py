"""Permission helpers for the school relationship domain.

School relationship records are owned by Marketing/Offline Marketing.  A
Promoter can work only inside the CRM Staff portfolio assigned to them; the
Sales pipeline scope is intentionally not reused here.
"""

from __future__ import annotations

import frappe

PORTFOLIO_ROLES = frozenset({"Promoter", "Promoter-PR"})
FULL_ACCESS_ROLES = frozenset({"Administrator", "System Manager", "Admissions Director", "Lead Sales"})
READ_ALL_ROLES = frozenset({"Marketing", "Sale"})


def _user_roles(user: str | None = None) -> set[str]:
	return set(frappe.get_roles(user or frappe.session.user))


def is_portfolio_user(user: str | None = None) -> bool:
	return bool(_user_roles(user) & PORTFOLIO_ROLES)


def _staff_name(user: str | None = None) -> str | None:
	return frappe.db.get_value("CRM Staff", {"user": user or frappe.session.user}, "name")


def _team_names(staff_name: str | None) -> list[str]:
	if not staff_name:
		return []
	return frappe.get_all(
		"CRM Team Membership",
		filters={"parent": staff_name, "parenttype": "CRM Staff"},
		pluck="team",
	)


def _in_clause(field: str, values: list[str]) -> str | None:
	values = sorted({value for value in values if value})
	if not values:
		return None
	return f"{field} in ({', '.join(frappe.db.escape(value) for value in values)})"


def portfolio_condition(doctype: str, user: str | None = None, *, owner_field="owner_staff", team_field="owning_team"):
	"""Return the SQL ceiling for a school-domain list query.

	The helper is deliberately role-aware but operation-agnostic.  DocPerm
	still decides whether a caller may read or write; this function only limits
	which rows a scoped Promoter may see.
	"""
	roles = _user_roles(user)
	if roles & FULL_ACCESS_ROLES or roles & READ_ALL_ROLES:
		return None
	if not roles & PORTFOLIO_ROLES:
		return "1=0"
	staff_name = _staff_name(user)
	teams = _team_names(staff_name)
	table = f"`tab{doctype}`"
	parts = []
	owner_clause = _in_clause(f"{table}.`{owner_field}`", [staff_name] if staff_name else [])
	team_clause = _in_clause(f"{table}.`{team_field}`", teams)
	if owner_clause:
		parts.append(owner_clause)
	if team_clause:
		parts.append(team_clause)
	return "(" + " or ".join(parts) + ")" if parts else "1=0"


def person_portfolio_condition(user: str | None = None):
	"""Scope CRM Person through its school-stakeholder associations."""
	roles = _user_roles(user)
	if roles & FULL_ACCESS_ROLES or roles & READ_ALL_ROLES:
		return None
	if not roles & PORTFOLIO_ROLES:
		return "1=0"
	if hasattr(frappe.db, "table_exists") and not frappe.db.table_exists("CRM School Stakeholder"):
		return "1=0"
	staff_name = _staff_name(user)
	teams = _team_names(staff_name)
	parts = []
	owner_clause = _in_clause("association.`owner_staff`", [staff_name] if staff_name else [])
	team_clause = _in_clause("association.`owning_team`", teams)
	if owner_clause:
		parts.append(owner_clause)
	if team_clause:
		parts.append(team_clause)
	if not parts:
		return "1=0"
	return (
		"exists (select 1 from `tabCRM School Stakeholder` association "
		"where association.`person` = `tabCRM Person`.`name` and ("
		+ " or ".join(parts)
		+ "))"
	)


def school_portfolio_condition(doctype: str, user: str | None = None, *, school_field: str = "name") -> str | None:
	"""Scope School-domain roots through authorised stakeholder associations.

	High School and Annual Snapshot do not own a portfolio field.  A scoped
	Promoter therefore receives a row only when an association for that school is
	inside their owner/team portfolio.  This is intentionally an ``exists``
	predicate so list, aggregate, and bounded-DTO queries can reuse it verbatim.
	"""
	roles = _user_roles(user)
	if roles & FULL_ACCESS_ROLES or roles & READ_ALL_ROLES:
		return None
	if not roles & PORTFOLIO_ROLES:
		return "1=0"
	if hasattr(frappe.db, "table_exists") and not frappe.db.table_exists("CRM School Stakeholder"):
		return "1=0"
	staff_name = _staff_name(user)
	teams = _team_names(staff_name)
	parts = []
	owner_clause = _in_clause("association.`owner_staff`", [staff_name] if staff_name else [])
	team_clause = _in_clause("association.`owning_team`", teams)
	if owner_clause:
		parts.append(owner_clause)
	if team_clause:
		parts.append(team_clause)
	if not parts:
		return "1=0"
	return (
		"exists (select 1 from `tabCRM School Stakeholder` association "
		f"where association.`high_school` = `tab{doctype}`.`{school_field}` and ("
		+ " or ".join(parts)
		+ "))"
	)


def has_school_portfolio_permission(doc, user=None, permission_type=None, ptype=None) -> bool:
	"""Direct-record counterpart of :func:`school_portfolio_condition`."""
	permission_type = permission_type or ptype
	if permission_type == "create" and not getattr(doc, "name", None):
		return True
	condition = school_portfolio_condition(
		doc.doctype,
		user,
		school_field="name" if doc.doctype == "CRM High School" else "high_school",
	)
	if condition is None:
		return True
	if condition == "1=0" or not getattr(doc, "name", None):
		return False
	return bool(
		frappe.db.sql(
			f"select name from `tab{doc.doctype}` where name = %s and ({condition}) limit 1",
			(doc.name,),
		)
	)


def has_person_portfolio_permission(doc, user=None, permission_type=None, ptype=None):
	permission_type = permission_type or ptype
	if permission_type == "create" and not getattr(doc, "name", None):
		return True
	condition = person_portfolio_condition(user)
	if condition is None:
		return True
	if condition == "1=0" or not getattr(doc, "name", None):
		return False
	return bool(
		frappe.db.sql(
			"select person.name from `tabCRM Person` person "
			"where person.name = %s and " + condition.replace("`tabCRM Person`", "person"),
			(doc.name,),
		)
	)


def has_portfolio_permission(
	doc,
	user: str | None = None,
	permission_type: str | None = None,
	ptype: str | None = None,
	*,
	owner_field="owner_staff",
	team_field="owning_team",
) -> bool:
	"""Apply the same portfolio ceiling to direct document access."""
	permission_type = permission_type or ptype
	is_bare_name = isinstance(doc, str)
	name = doc if is_bare_name else getattr(doc, "name", None)
	if permission_type == "create" and not name:
		return True
	if is_bare_name:
		# Frappe can hand the hook a bare docname with no doctype, so the
		# owner/team row filter cannot be built. Apply only the role ceiling and
		# fail closed for a scoped Promoter rather than granting blanket access.
		roles = _user_roles(user)
		if roles & FULL_ACCESS_ROLES or roles & READ_ALL_ROLES:
			return True
		return False
	condition = portfolio_condition(
		doc.doctype,
		 user,
		 owner_field=owner_field,
		 team_field=team_field,
	)
	if condition is None:
		return True
	if condition == "1=0" or not getattr(doc, "name", None):
		return False
	return bool(
		frappe.db.sql(
			f"select name from `tab{doc.doctype}` where name = %s and ({condition}) limit 1",
			(doc.name,),
		)
	)


def default_portfolio(doc, user: str | None = None) -> None:
	"""Populate owner/team defaults for a new relationship record."""
	staff_name = _staff_name(user)
	if not staff_name:
		return
	if not doc.get("owner_staff"):
		doc.owner_staff = staff_name
	if not doc.get("owning_team"):
		teams = _team_names(staff_name)
		if teams:
			doc.owning_team = teams[0]


def _values_in_portfolio(owner_staff, owning_team, user=None) -> bool:
	staff_name = _staff_name(user)
	teams = _team_names(staff_name)
	return bool(staff_name and (owner_staff == staff_name or owning_team in teams))


def validate_portfolio_update(
	doc,
	user: str | None = None,
	*,
	owner_field="owner_staff",
	team_field="owning_team",
) -> None:
	"""Prevent a Promoter from escaping their assigned portfolio on update."""
	if not is_portfolio_user(user):
		return
	# Administrator / System Manager (and the other full-access roles) also carry
	# the Promoter role by inheritance; the portfolio ceiling is not meant for
	# them, mirroring portfolio_condition()'s role check.
	if _user_roles(user) & (FULL_ACCESS_ROLES | READ_ALL_ROLES):
		return
	if not _values_in_portfolio(doc.get(owner_field), doc.get(team_field), user):
		frappe.throw("You can only manage school relationship records in your portfolio.", frappe.PermissionError)
	if doc.is_new():
		return

	previous = doc.get_doc_before_save()
	if previous and not _values_in_portfolio(previous.get(owner_field), previous.get(team_field), user):
		frappe.throw("You can only manage school relationship records in your portfolio.", frappe.PermissionError)
	if previous and (
		previous.get(owner_field) != doc.get(owner_field)
		or previous.get(team_field) != doc.get(team_field)
	):
		frappe.throw("Promoters cannot reassign school relationship ownership.", frappe.PermissionError)
