"""Bounded, allowlisted Student predicates shared by every Segment consumer."""

import json
import math

import frappe

FIELDS = {
	"student_stage": {
		"label": "Student Stage",
		"fieldtype": "Select",
		"options": "New\nAttempting\nConnected\nQualified\nDisqualified",
	},
	"potential": {"label": "Potential", "fieldtype": "Select", "options": "HIGH\nMEDIUM\nLOW"},
	"intent": {"label": "Intent", "fieldtype": "Select", "options": "HIGH\nMEDIUM\nLOW"},
	"need": {"label": "Need", "fieldtype": "Term", "options": "CRM Need"},
	"tag": {"label": "Tag", "fieldtype": "Term", "options": "CRM Tag"},
}
OPERATORS = {
	"Term": ("in", "not in"),
	"Select": ("=", "!=", "in", "not in"),
	"Link": ("=", "!=", "in", "not in"),
	"Check": ("=", "!="),
	"Float": ("=", "!=", ">", ">=", "<", "<="),
}
MAX_GROUPS = 10
MAX_CONDITIONS = 20
FILTER_LOGIC = ("AND", "OR")


def student_scope_or_filters():
	"""Keep parent-only CRM Student contacts out of student segments."""
	return [
		["decision_maker", "in", ["", "Student", "Both"]],
		["decision_maker", "is", "not set"],
	]


def fail(message, code="INVALID_INPUT", *, permission=False):
	frappe.throw(f"{code}: {message}", frappe.PermissionError if permission else frappe.ValidationError)


def bounded_text(value, field, *, limit=140, optional=False):
	if optional and value is None:
		return ""
	if not isinstance(value, str) or len(value) > limit or (not optional and not value.strip()):
		fail(f"{field} must be text of at most {limit} characters.")
	return value.strip()


def integer(value, field, *, maximum=2147483647):
	if (
		isinstance(value, bool)
		or len(str(value)) > 10
		or not str(value).isascii()
		or not str(value).isdigit()
	):
		fail(f"{field} must be a non-negative integer.")
	number = int(value)
	if number > maximum:
		fail(f"{field} cannot exceed {maximum}.")
	return number


def validate_filters(filters):
	if isinstance(filters, str):
		if len(filters) > 65536:
			fail("Segment filters exceed the maximum size.")
		try:
			filters = json.loads(filters)
		except ValueError:
			fail("Segment filters must be valid JSON.")
	if not isinstance(filters, dict) or set(filters) - {"groups", "logic"}:
		fail("Segment filters must be an object containing groups.")
	logic = filters.get("logic", "OR")
	if logic not in FILTER_LOGIC:
		fail("The outer Segment logic must be AND or OR.")
	groups = filters.get("groups")
	if not isinstance(groups, list) or not 1 <= len(groups) <= MAX_GROUPS:
		fail(f"Segment requires 1 to {MAX_GROUPS} non-empty filter groups.")
	result = []
	for index, group in enumerate(groups):
		if not isinstance(group, dict) or set(group) - {"logic", "name", "conditions"}:
			fail("Each group may include a name and must contain conditions and optional AND logic.")
		group_logic = group.get("logic", "AND")
		if group_logic not in FILTER_LOGIC:
			fail("Each group logic must be AND or OR.")
		conditions = group.get("conditions")
		if not isinstance(conditions, list) or not 1 <= len(conditions) <= MAX_CONDITIONS:
			fail(f"Each group requires 1 to {MAX_CONDITIONS} conditions.")
		name = bounded_text(group.get("name"), "group name", optional=True) or f"Nhóm {index + 1}"
		result.append({"logic": group_logic, "name": name, "conditions": [_condition(c) for c in conditions]})
	return {"logic": logic, "groups": result}


def _condition(condition):
	if not isinstance(condition, dict) or set(condition) != {"field", "operator", "value"}:
		fail("Each condition requires exactly field, operator and value.")
	field, operator, value = (condition[key] for key in ("field", "operator", "value"))
	if not isinstance(field, str) or field not in FIELDS:
		fail("Field is not allowed in Segment conditions.")
	kind = FIELDS[field]["fieldtype"]
	if operator not in OPERATORS[kind]:
		fail(f"Operator is not allowed for {field}.")
	if kind == "Float":
		if (
			isinstance(value, bool)
			or not isinstance(value, (int, float))
			or abs(value) > 1e100
			or not math.isfinite(value)
		):
			fail(f"{field} requires a finite JSON number.")
	elif kind == "Check":
		if value not in (0, 1, "0", "1", True, False):
			fail(f"{field} only accepts 0 or 1.")
		value = int(value)
	else:
		values = value if operator in ("in", "not in") else [value]
		if not isinstance(values, list) or not 1 <= len(values) <= 100:
			fail("Set conditions require 1 to 100 values.")
		values = [bounded_text(item, field) for item in values]
		if kind == "Select" and any(item not in FIELDS[field]["options"].splitlines() for item in values):
			fail(f"Unknown option for {field}.")
		if kind == "Term":
			doctype = FIELDS[field]["options"]
			for item in values:
				if not frappe.db.exists(doctype, item):
					fail(f"Unknown {field} term identifier.")
		value = list(dict.fromkeys(values)) if operator in ("in", "not in") else values[0]
	return {"field": field, "operator": operator, "value": value}


def _visible_student_query():
	return frappe.get_list(
		"CRM Student",
		fields=["name"],
		or_filters=student_scope_or_filters(),
		limit_page_length=0,
		order_by="",
		run=False,
	)


def _condition_filter(condition):
	return [condition["field"], condition["operator"], condition["value"]]


def _classification_predicate(condition):
	values = ",".join(frappe.db.escape(v) for v in condition["value"])
	negation = "NOT " if condition["operator"] == "not in" else ""
	assignment_table = (
		"CRM Student Need Assignment" if condition["field"] == "need" else "CRM Student Tag Assignment"
	)
	parent_field = "needs" if condition["field"] == "need" else "tags"
	return (
		f"{negation}EXISTS (SELECT 1 FROM `tab{assignment_table}` c "
		"WHERE c.parent = allowed.name AND c.parenttype = 'CRM Student' "
		f"AND c.parentfield = '{parent_field}' "
		f"AND c.{condition['field']} IN ({values}))"
	)


def _condition_query(condition):
	if condition["field"] not in ("need", "tag"):
		return frappe.get_list(
			"CRM Student",
			fields=["name"],
			filters=[_condition_filter(condition)],
			or_filters=student_scope_or_filters(),
			limit_page_length=0,
			order_by="",
			run=False,
		)

	query = _visible_student_query()
	return f"SELECT allowed.name FROM ({query}) allowed WHERE {_classification_predicate(condition)}"


def _group_query(group):
	conditions = group["conditions"]
	if group["logic"] == "OR":
		return " UNION ".join(f"({query})" for query in map(_condition_query, conditions))

	student_conditions = [
		_condition_filter(condition)
		for condition in conditions
		if condition["field"] not in ("need", "tag")
	]
	query = frappe.get_list(
		"CRM Student",
		fields=["name"],
		filters=student_conditions,
		or_filters=student_scope_or_filters(),
		limit_page_length=0,
		order_by="",
		run=False,
	)
	predicates = [
		_classification_predicate(condition)
		for condition in conditions
		if condition["field"] in ("need", "tag")
	]
	if predicates:
		query = f"SELECT allowed.name FROM ({query}) allowed WHERE " + " AND ".join(predicates)
	return query


def scoped_rule_query(filters):
	"""Build permission-checked queries for nested AND/OR segment rules.

	Every condition branch uses Frappe's field sanitization, DocPerm, permission
	hooks and User Permissions. UNION and inner joins implement the selected
	logic while keeping overlapping results deduplicated.
	"""
	filters = validate_filters(filters)
	queries = [_group_query(group) for group in filters["groups"]]
	if filters["logic"] == "OR":
		return " UNION ".join(f"({query})" for query in queries)

	query = queries[0]
	for index, group_query in enumerate(queries[1:], start=1):
		query = (
			f"SELECT current.name FROM ({query}) current "
			f"INNER JOIN ({group_query}) required_{index} "
			f"ON required_{index}.name = current.name"
		)
	return query
