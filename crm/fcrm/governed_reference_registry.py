"""Declarative governed-reference inventory."""

from __future__ import annotations


REGISTRY_REVISION = "P9-DEC-002"


def _refs(*values):
	return tuple({"doctype": doctype, "fieldname": fieldname} for doctype, fieldname in values)


GOVERNED_REFERENCE_REGISTRY = {
	"CRM Lead Source": {
		"name_field": "source_name", "owner_role": "Marketing", "approver_roles": frozenset({"Marketing"}),
		"additive_requires_approval": False,
		"consumers": _refs(("CRM Contact", "source"), ("CRM Platform", "lead_source"), ("CRM Campaign Spend", "lead_source"), ("CRM Student", "source")),
	},
	"CRM Platform": {
		"name_field": "platform_name", "owner_role": "Marketing", "approver_roles": frozenset({"Marketing"}),
		"additive_requires_approval": False, "required_fields": ("lead_source",),
		"consumers": _refs(("CRM Contact", "platform"), ("CRM Campaign", "platform"), ("CRM Campaign Spend", "platform")),
	},
	"CRM Term": {
		"name_field": "term_name", "owner_role": "Lead Sales", "approver_roles": frozenset({"Lead Sales", "Marketing"}),
		"additive_requires_approval": False,
		"consumers": _refs(
			("CRM Contact", "enrollment_status"), ("CRM Contact", "lead_status"), ("CRM Contact", "aspiration"),
			("CRM Student", "enrollment_status"), ("CRM Student", "aspiration"), ("CRM Campaign", "campaign_type"),
			("CRM Intent", "intent_type"), ("CRM Interaction", "interaction_type"), ("CRM Score Signal", "intent_type"),
			("CRM High School", "school_type"), ("CRM High School", "school_area"),
			("CRM School Stakeholder", "stakeholder_role"),
			("CRM School Activity", "activity_type"), ("CRM Major", "major_group"), ("CRM Province", "region"),
		),
	},
	"CRM Campus": {
		"name_field": "campus_name", "owner_role": "Admissions Director", "approver_roles": frozenset({"Admissions Director"}),
		"additive_requires_approval": False,
		"consumers": _refs(("CRM Contact", "branch"), ("CRM Department", "campus"), ("CRM Staff", "campus"), ("CRM Campaign", "campus"), ("CRM Campaign Spend", "campus"), ("CRM Student Pool", "campus"), ("CRM Student Routing Request", "campus"), ("CRM Student SLA Attempt", "campus"), ("CRM Team", "campus")),
	},
}


def get_governed_config(doctype):
	return GOVERNED_REFERENCE_REGISTRY.get(doctype)


def config_for(doctype):
	config = get_governed_config(doctype)
	if not config:
		raise KeyError(f"{doctype} is not governed")
	return config


def governed_doctypes():
	return tuple(GOVERNED_REFERENCE_REGISTRY)


def reference_fields(doctype):
	return tuple(GOVERNED_REFERENCE_REGISTRY.get(doctype, {}).get("consumers", ()))


def validate_registry():
	for doctype, config in GOVERNED_REFERENCE_REGISTRY.items():
		if not config.get("name_field") or not config.get("owner_role") or not config.get("approver_roles"):
			return False
		seen = set()
		for consumer in config.get("consumers", ()):
			key = (consumer["doctype"], consumer["fieldname"])
			if key in seen:
				return False
			seen.add(key)
	return True


def is_governed(doctype):
	return doctype in GOVERNED_REFERENCE_REGISTRY
