"""Bounded, allowlisted Student predicates shared by every Segment consumer."""

import json
import math

import frappe

FIELDS = {
	"potential": {"label": "Potential", "fieldtype": "Select", "options": "HIGH\nMEDIUM\nLOW"},
	"intent": {"label": "Intent", "fieldtype": "Select", "options": "HIGH\nMEDIUM\nLOW"},
	"need": {"label": "Need", "fieldtype": "Term", "options": "CRM Need"},
	"tag": {"label": "Tag", "fieldtype": "Term", "options": "CRM Tag"},
	"lifecycle_stage": {
		"label": "Lifecycle Stage",
		"fieldtype": "Select",
		"options": "Lead\nMQL\nApplicant\nEnrolled\nLost",
	},
	"enrollment_status": {
		"label": "Enrollment Status",
		"fieldtype": "Link",
		"options": "CRM Enrollment Status",
	},
	"source": {"label": "Source", "fieldtype": "Link", "options": "CRM Lead Source"},
	"platform": {"label": "Platform", "fieldtype": "Link", "options": "CRM Platform"},
	"branch": {"label": "Branch", "fieldtype": "Link", "options": "CRM Campus"},
	"province": {"label": "Province", "fieldtype": "Link", "options": "CRM Province"},
	"major": {"label": "Major", "fieldtype": "Link", "options": "CRM Major"},
	"admission_year": {"label": "Admission Year", "fieldtype": "Link", "options": "CRM Admission Year"},
	"quality_bucket": {
		"label": "Quality Bucket",
		"fieldtype": "Select",
		"options": "Hot\nWarm\nCool\nSai số\nKhông liên lạc được\nKhông quan tâm",
	},
	"is_opted_out": {"label": "Opted Out", "fieldtype": "Check"},
	"latest_score": {"label": "Latest Score", "fieldtype": "Float"},
	"graduation_score": {"label": "Graduation Score", "fieldtype": "Float"},
	"transcript_score": {"label": "Transcript Score", "fieldtype": "Float"},
	"total_score": {"label": "Total Score", "fieldtype": "Float"},
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
	if filters.get("logic", "OR") != "OR":
		fail("The outer Segment logic must be OR.")
	groups = filters.get("groups")
	if not isinstance(groups, list) or not 1 <= len(groups) <= MAX_GROUPS:
		fail(f"Segment requires 1 to {MAX_GROUPS} non-empty filter groups.")
	result = []
	for group in groups:
		if not isinstance(group, dict) or set(group) - {"logic", "conditions"}:
			fail("Each group must contain conditions and optional AND logic.")
		if group.get("logic", "AND") != "AND":
			fail("Each group must use AND logic.")
		conditions = group.get("conditions")
		if not isinstance(conditions, list) or not 1 <= len(conditions) <= MAX_CONDITIONS:
			fail(f"Each group requires 1 to {MAX_CONDITIONS} conditions.")
		result.append({"logic": "AND", "conditions": [_condition(c) for c in conditions]})
	return {"groups": result}


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


def scoped_rule_query(filters):
	"""UNION DB-generated, permission-checked SELECTs; never interpolate user SQL.

	Every branch uses Frappe's field sanitization, DocPerm, permission hooks and
	User Permissions. UNION deduplicates overlapping groups at the database.
	"""
	filters = validate_filters(filters)
	queries = []
	for group in filters["groups"]:
		conditions = [
			[c["field"], c["operator"], c["value"]]
			for c in group["conditions"]
			if c["field"] not in ("need", "tag")
		]
		query = frappe.get_list(
			"CRM Student",
			fields=["name"],
			filters=conditions,
			limit_page_length=0,
			order_by="",
			run=False,
			ignore_ifnull=True,
		)
		predicates = []
		for condition in group["conditions"]:
			if condition["field"] not in ("need", "tag"):
				continue
			values = ",".join(frappe.db.escape(v) for v in condition["value"])
			negation = "NOT " if condition["operator"] == "not in" else ""
			assignment_table = (
				"CRM Student Need Assignment"
				if condition["field"] == "need"
				else "CRM Student Tag Assignment"
			)
			assignment_field = condition["field"]
			predicates.append(
				f"{negation}EXISTS (SELECT 1 FROM `tab{assignment_table}` c "
				"WHERE c.parent = allowed.name AND c.parenttype = 'CRM Student' "
				f"AND c.parentfield = '{'needs' if condition['field'] == 'need' else 'tags'}' "
				f"AND c.{assignment_field} IN ({values}))"
			)
		if predicates:
			query = f"SELECT allowed.name FROM ({query}) allowed WHERE " + " AND ".join(predicates)
		queries.append(f"({query})")
	return " UNION ".join(queries)
