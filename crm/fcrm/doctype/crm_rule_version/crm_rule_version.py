"""Frappe-managed rule version and lifecycle boundary."""

from __future__ import annotations

import json

import frappe
from frappe.model.document import Document

from crm.fcrm.rule_engine import normalize_group_catalog, normalize_rule_version_data

AUTHORING_FLAG = "crm_rule_version_authoring"


class CRMRuleVersion(Document):
    def validate(self):
        # Frappe JSON fields are persisted as text.  During API authoring the
        # normalized value may still be a Python list, and ``as_dict()``
        # rejects that value before this hook can normalize it.
        raw = {
            fieldname: self.get(fieldname)
            for fieldname in (
                "version_id",
                "version_name",
                "description",
                "status",
                "group_catalog",
                "revision",
            )
        }
        try:
            data = normalize_rule_version_data(raw)
        except ValueError as exc:
            frappe.throw(str(exc), frappe.ValidationError)

        before = self.get_doc_before_save()
        if before and data["version_id"] != str(before.version_id or "").strip().upper():
            frappe.throw("CRM Rule Version ID cannot be changed after creation.", frappe.ValidationError)

        if self.is_new():
            if not getattr(frappe.flags, AUTHORING_FLAG, False):
                frappe.throw(
                    "CRM Rule Versions can only be created through the rule admin API.",
                    frappe.PermissionError,
                )
            if data["status"] != "draft" or data["revision"]:
                frappe.throw("A new CRM Rule Version must start as a draft at revision zero.", frappe.ValidationError)
            self.name = data["version_id"]
            self.ruleset_revision = None
            self.ruleset_digest = None
        else:
            previous_status = str(before.status or "draft").lower() if before else "draft"
            current_status = str(data["status"] or "draft").lower()
            lifecycle = getattr(frappe.flags, "crm_rule_version_lifecycle", False)
            authoring = getattr(frappe.flags, "crm_rule_version_authoring", False)
            if current_status != previous_status and not lifecycle:
                frappe.throw(
                    "CRM Rule Version lifecycle changes must use the version admin API.",
                    frappe.PermissionError,
                )
            managed_fields = (
                "version_name",
                "description",
                "group_catalog",
                "revision",
                "schema_version",
                "ruleset_revision",
                "ruleset_digest",
            )
            changed = any(before.get(fieldname) != self.get(fieldname) for fieldname in managed_fields)
            if previous_status in {"active", "superseded"} and changed and not lifecycle:
                frappe.throw(
                    "Active or superseded CRM Rule Versions are immutable. Clone the snapshot to edit.",
                    frappe.PermissionError,
                )
            if previous_status == "draft" and changed and not authoring:
                frappe.throw("CRM Rule Version changes must use the rule admin API.", frappe.PermissionError)

        if data["status"] == "draft" and self.get("ruleset_digest") and not getattr(
            frappe.flags, "crm_rule_version_authoring", False
        ):
            frappe.throw("Draft CRM Rule Versions cannot carry an immutable digest.", frappe.ValidationError)

        self.version_id = data["version_id"]
        self.version_name = data["version_name"]
        self.description = data["description"]
        self.status = data["status"]
        self.group_catalog = json.dumps(data["group_catalog"], ensure_ascii=False, separators=(",", ":"))
        self.revision = data["revision"]
        self.schema_version = data["schema_version"]

    def on_trash(self):
        if not getattr(frappe.flags, AUTHORING_FLAG, False):
            frappe.throw(
                "CRM Rule Versions can only be deleted through the rule admin API.",
                frappe.PermissionError,
            )
        if str(self.status or "").lower() != "draft":
            frappe.throw(
                "Only draft CRM Rule Versions can be deleted. Immutable snapshots cannot be deleted.",
                frappe.PermissionError,
            )
