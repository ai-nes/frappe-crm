import unittest
from types import SimpleNamespace

from crm.api.capability import _build_discovery_contract, _discovery_view


def _meta(*fields, label="Resource", description="<p>Safe description</p>"):
    return SimpleNamespace(
        label=label,
        description=description,
        fields=list(fields),
    )


def _field(name, fieldtype="Data", options=None, label=None):
    return SimpleNamespace(
        fieldname=name,
        fieldtype=fieldtype,
        options=options,
        label=label or name,
        permlevel=0,
    )


def _grant(*fields):
    return {
        "operations": {"read": True, "write": False, "create": False, "delete": False},
        "fields": list(fields),
        "row_scoped": True,
    }


class TestCapabilityDiscovery(unittest.TestCase):
    def test_policy_is_compact_and_permission_filtered(self):
        meta = _meta(
            _field("name"),
            _field("status", "Select"),
            _field("secret", "Password"),
            _field("notes", "Text"),
        )
        catalog, description = _discovery_view("CRM Lead", meta, _grant("name", "status", "secret", "notes"))
        self.assertEqual(catalog["operations"], ["count", "get", "list", "search"])
        self.assertEqual(description["query_policy"]["list"]["filter_fields"], ["name", "status"])
        self.assertNotIn("secret", description["query_policy"]["list"]["filter_fields"])
        self.assertNotIn("secret", {field["name"] for field in description["readable_fields"]})
        self.assertEqual(description["query_policy"]["count"]["count_mode"], "exact")
        self.assertEqual(description["query_policy"]["search"]["search_field"], "name")
        self.assertEqual(catalog["short_description"], "Safe description")

    def test_only_cataloged_static_links_are_projected(self):
        lead_meta = _meta(_field("name"), _field("company", "Link", "CRM Company"))
        company_meta = _meta(_field("name"))
        views = {
            "CRM Lead": (lead_meta, _grant("name", "company")),
            "CRM Company": (company_meta, _grant("name")),
            "CRM Hidden": (_meta(_field("name")), _grant("name")),
        }
        contract = _build_discovery_contract(views)
        lead = contract["descriptions"]["CRM Lead"]
        self.assertEqual(lead["relationships"], [{"source_field": "company", "target_resource": "CRM Company"}])

        lead_meta.fields.append(_field("dynamic", "Dynamic Link", "link_doctype"))
        contract = _build_discovery_contract(views)
        self.assertEqual(
            contract["descriptions"]["CRM Lead"]["relationships"],
            [{"source_field": "company", "target_resource": "CRM Company"}],
        )

    def test_revision_is_deterministic_and_changes_with_disclosed_policy(self):
        views = {"CRM Lead": (_meta(_field("name")), _grant("name"))}
        first = _build_discovery_contract(views)
        second = _build_discovery_contract(views)
        self.assertEqual(first["discovery_revision"], second["discovery_revision"])
        views["CRM Lead"][0].fields.append(_field("status", "Select"))
        views["CRM Lead"] = (views["CRM Lead"][0], _grant("name", "status"))
        self.assertNotEqual(first["discovery_revision"], _build_discovery_contract(views)["discovery_revision"])
