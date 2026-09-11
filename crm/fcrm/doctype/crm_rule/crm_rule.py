"""Frappe-managed rule definition and immutable snapshot boundary."""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe.model.document import Document

from crm.fcrm.rule_engine import normalize_group_catalog, normalize_rule_data

AUTHORING_FLAG = "crm_rule_authoring"


class CRMRule(Document):
    def autoname(self):
        if self.get("rule_version") and self.get("rule_id"):
            self.name = rule_document_name(self.rule_version, self.rule_id)

    def validate(self):
        raw = self.as_dict()
        raw["rule_version"] = self.get("rule_version")
        try:
            data = normalize_rule_data(raw)
        except ValueError as exc:
            frappe.throw(str(exc), frappe.ValidationError)

        if not data["rule_version"]:
            frappe.throw("CRM Rule Version is required.", frappe.ValidationError)
        version = frappe.db.get_value(
            "CRM Rule Version",
            data["rule_version"],
            ["name", "status", "group_catalog"],
            as_dict=True,
        )
        if not version:
            frappe.throw("CRM Rule Version does not exist.", frappe.LinkValidationError)
        if str(version.status or "").lower() != "draft":
            frappe.throw("Rules can only be edited in a draft CRM Rule Version.", frappe.PermissionError)
        try:
            groups = normalize_group_catalog(version.group_catalog)
        except ValueError as exc:
            frappe.throw(str(exc), frappe.ValidationError)
        group = next((item for item in groups if item["code"] == data["group_code"]), None)
        if group is None:
            frappe.throw("CRM Rule group must be declared in the version catalog.", frappe.ValidationError)
        if not group["enabled"]:
            frappe.throw("CRM Rule group is disabled in the version catalog.", frappe.ValidationError)

        before = self.get_doc_before_save()
        if before and data["rule_id"] != str(before.rule_id or "").strip().upper():
            frappe.throw("CRM Rule ID cannot be changed after creation.", frappe.ValidationError)
        if before and data["rule_version"] != str(before.rule_version or "").strip().upper():
            frappe.throw("CRM Rule Version cannot be changed after creation.", frappe.ValidationError)
        if before and not getattr(frappe.flags, AUTHORING_FLAG, False):
            managed_fields = (
                "group_code",
                "rule_name",
                "description",
                "feature",
                "rule_type",
                "outcome",
                "precedence",
                "unknown_policy",
                "reason_code",
                "business_reason_template",
                "target_actions",
                "conditions",
                "enabled",
            )
            if any(before.get(fieldname) != self.get(fieldname) for fieldname in managed_fields):
                frappe.throw("CRM Rules can only be changed through the rule admin API.", frappe.PermissionError)

        if self.is_new():
            if not getattr(frappe.flags, AUTHORING_FLAG, False):
                frappe.throw(
                    "CRM Rules can only be created through the rule admin API.",
                    frappe.PermissionError,
                )
            self.name = rule_document_name(data["rule_version"], data["rule_id"])
            self.status = "draft"
            self.revision = 0
        elif before and str(self.status or "draft").lower() != str(before.status or "draft").lower():
            if not getattr(frappe.flags, "crm_rule_lifecycle", False):
                frappe.throw("CRM Rule lifecycle changes must use the rule admin API.", frappe.PermissionError)

        if before and int(self.revision or 0) != int(before.revision or 0) and not getattr(
            frappe.flags, AUTHORING_FLAG, False
        ):
            frappe.throw("CRM Rule revision can only change through the rule admin API.", frappe.PermissionError)

        self.rule_id = data["rule_id"]
        self.rule_version = data["rule_version"]
        self.group_code = data["group_code"]
        self.rule_name = data["name"]
        self.description = data["description"]
        self.feature = data["feature"]
        self.rule_type = data["rule_type"]
        self.outcome = data["outcome"]
        self.precedence = data["precedence"]
        self.unknown_policy = data["unknown_policy"]
        self.reason_code = data["reason_code"]
        self.business_reason_template = data["business_reason_template"]
        self.conditions = json.dumps(data["conditions"], ensure_ascii=False)
        self.target_actions = json.dumps(data["target_actions"], ensure_ascii=False)
        self.status = str(self.status or data["status"]).lower()
        self.enabled = int(data["enabled"])
        self.revision = int(self.revision or data["revision"])
        self.schema_version = data["schema_version"]

    def on_trash(self):
        if not getattr(frappe.flags, AUTHORING_FLAG, False):
            frappe.throw(
                "CRM Rules can only be deleted through the rule admin API.",
                frappe.PermissionError,
            )
        version_status = frappe.db.get_value("CRM Rule Version", self.rule_version, "status")
        if self.status != "draft" or str(version_status or "").lower() != "draft":
            frappe.throw(
                "Only draft CRM Rules can be deleted. Immutable snapshots cannot be deleted.",
                frappe.PermissionError,
            )


def rule_document_name(rule_version: str, rule_id: str) -> str:
    key = f"{str(rule_version).strip().upper()}\x00{str(rule_id).strip().upper()}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return f"CRM-RULE-{digest}-{str(rule_id).strip().upper()}"
