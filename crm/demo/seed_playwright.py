"""Disposable fixture for the Lead-processing Playwright suite.

This module deliberately owns a small cohort instead of reusing the larger
``seed_e2e`` rehearsal.  It is safe to run repeatedly on the explicitly
marked local site and writes only stable document identifiers to the shared
workspace manifest consumed by Playwright.

Commands::

    bench --site crm.localhost execute crm.demo.seed_playwright.execute
    bench --site crm.localhost execute crm.demo.seed_playwright.reset

The fixture is fail-closed.  It requires the local site name and the
``crm_playwright_disposable`` site config flag; production or shared sites
cannot be seeded accidentally.
"""

from __future__ import annotations

import json
import os
import re
from datetime import timedelta
from pathlib import Path

import frappe
from frappe.utils import now_datetime

from crm.demo import seed_demo, seed_student
from crm.fcrm.student_intake import submit_intake


PREFIX = "PW-LEAD"
_RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{5,63}$")
_LEASE_KEY = "crm_playwright_e2e_lease"


def _run_id() -> str:
    """Return the explicitly configured supervisor run id, fail-closed otherwise."""
    run_id = str(frappe.conf.get("crm_playwright_e2e_run_id") or os.environ.get("E2E_RUN_ID") or "").strip()
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise frappe.ValidationError("E2E_RUN_ID must be 6-64 characters of letters, digits, _ or -.")
    return run_id


def _prefix() -> str:
    return f"{PREFIX}-{_run_id()}"


def _emails() -> dict[str, str]:
    namespace = _run_id().lower()
    return {
        "detail": f"pw-{namespace}-detail@example.test",
        "lifecycle": f"pw-{namespace}-lifecycle@example.test",
        "non_enrolled": f"pw-{namespace}-non-enrolled@example.test",
        "enrolled": f"pw-{namespace}-enrolled@example.test",
    }


def _manifest_path() -> Path:
    # The bench container mounts the repository at /workspace.  Deriving from
    # the app path also works for a non-Docker bench checkout.
    app_root = Path(frappe.get_app_path("crm"))
    return app_root.parent / "frontend" / f"playwright-fixture.{_run_id()}.json"


def _require_disposable() -> None:
    site = getattr(getattr(frappe, "local", None), "site", None)
    if site != "crm.localhost":
        raise frappe.ValidationError(
            "Playwright fixture is restricted to site crm.localhost."
        )
    if frappe.conf.get("crm_playwright_disposable") not in (1, "1", True):
        raise frappe.ValidationError(
            "Set crm_playwright_disposable=1 before provisioning the fixture."
        )
    if frappe.conf.get("crm_playwright_test_seam_enabled") not in (1, "1", True):
        raise frappe.ValidationError("Enable crm_playwright_test_seam_enabled only on the disposable site.")


def _lease() -> dict:
    return frappe.cache().get_value(_LEASE_KEY) or {}


def acquire_lease(ttl_minutes: int = 60) -> dict[str, str]:
    """Claim the one local disposable instance without mutating business data."""
    _require_disposable()
    run_id = _run_id()
    lease = _lease()
    now = now_datetime()
    expires_at = lease.get("expires_at")
    if lease and lease.get("run_id") != run_id and expires_at and str(expires_at) > str(now):
        raise frappe.ValidationError("E2E_SITE_LEASED: another run currently owns the disposable site.")
    ttl = min(max(int(ttl_minutes), 5), 240)
    value = {"run_id": run_id, "site": frappe.local.site, "expires_at": str(now + timedelta(minutes=ttl))}
    frappe.cache().set_value(_LEASE_KEY, value, expires_in_sec=ttl * 60)
    return value


def release_lease() -> dict[str, object]:
    _require_disposable()
    lease = _lease()
    if lease and lease.get("run_id") != _run_id():
        raise frappe.ValidationError("E2E_LEASE_MISMATCH: refusing to release another run's lease.")
    frappe.cache().delete_value(_LEASE_KEY)
    return {"released": bool(lease), "run_id": _run_id()}


def preflight() -> dict[str, object]:
    """Verify the guarded local topology before any seed or browser mutation."""
    _require_disposable()
    run_id = _run_id()
    lease = _lease()
    if not lease or lease.get("run_id") != run_id:
        raise frappe.ValidationError("E2E_LEASE_REQUIRED: acquire the disposable-site lease first.")
    if frappe.conf.get("crm_agents_url"):
        raise frappe.ValidationError("E2E_EGRESS_BLOCKED: crm_agents_url must be empty for the disposable test run.")
    return {"site": frappe.local.site, "run_id": run_id, "lease": lease, "egress": "blocked"}


def _context() -> dict[str, str]:
	base = seed_student._ensure_context()
	preferred_campus = frappe.db.get_value(
		"CRM Campus", {"campus_name": "FPTU Ho Chi Minh Campus"}, "name"
	) or base["campus"]
	preferred_team, pool = _ensure_fixture_team_and_pool(preferred_campus)
	context = {**base, "campus": preferred_campus, "team": preferred_team}
	_ensure_fixture_policies(context["campus"], pool)
	_ensure_role_scope(context["campus"], context["team"])
	return {**context, "pool": pool}


def _ensure_fixture_policies(campus: str, pool: str) -> None:
	"""Publish run-scoped active routing/SLA policies for the isolated pool."""
	from crm.demo.seed_student import _publish_demo_policy

	now = now_datetime() - timedelta(minutes=5)
	keys = {
		"routing": f"{_prefix()}:routing-v1",
		"sla": f"{_prefix()}:sla-v1",
	}
	if not frappe.db.exists("CRM Student Routing Policy", {"policy_key": keys["routing"]}):
		_publish_demo_policy(
			{
				"doctype": "CRM Student Routing Policy",
				"policy_key": keys["routing"],
				"policy_version": 1,
				"status": "active",
				"campus": campus,
				"student_pool": pool,
				"strategy": "round_robin",
				"effective_from": now,
			}
		)
	if not frappe.db.exists("CRM Student SLA Policy", {"policy_key": keys["sla"]}):
		_publish_demo_policy(
			{
				"doctype": "CRM Student SLA Policy",
				"policy_key": keys["sla"],
				"policy_version": 1,
				"status": "active",
				"campus": campus,
				"student_pool": pool,
				"warning_minutes": 60,
				"breach_minutes": 120,
				"escalation_minutes": 240,
				"pause_reasons": json.dumps(["awaiting_student", "approved_document_wait"]),
				"maximum_pause_minutes": 120,
				"recipient_strategy": "owner_warning_lead_breach_director_escalation",
				"effective_from": now,
			}
		)


def _ensure_fixture_team_and_pool(campus: str) -> tuple[str, str]:
	team_name = f"{_prefix()} Team"
	if not frappe.db.exists("CRM Team", team_name):
		frappe.get_doc(
			{
				"doctype": "CRM Team",
				"team_name": team_name,
				"team_type": "Sales",
				"campus": campus,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
	pool_name = f"{_prefix()} Pool"
	if not frappe.db.exists("CRM Student Pool", pool_name):
		frappe.get_doc(
			{
				"doctype": "CRM Student Pool",
				"pool_name": pool_name,
				"team": team_name,
				"campus": campus,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
	return team_name, pool_name


def _ensure_role_scope(campus: str, team: str) -> None:
	"""Put the canonical local Sale personas in the fixture's real scope."""
	for email, function, is_team_lead in (
		("sale@gmail.com", "Sale", 0),
		("leadsale@gmail.com", "Lead Sales", 1),
	):
		staff_name = frappe.db.get_value("CRM Staff", {"user": email}, "name")
		if not staff_name:
			continue
		staff = frappe.get_doc("CRM Staff", staff_name)
		staff.campus = campus
		for row in staff.team_memberships:
			if row.function == function:
				row.is_primary = 0
		membership = next((row for row in staff.team_memberships if row.team == team), None)
		if membership:
			membership.function = function
			membership.is_primary = 0
			membership.is_team_lead = is_team_lead
		else:
			staff.append(
				"team_memberships",
				{
					"team": team,
					"function": function,
					"is_primary": 0,
					"is_team_lead": is_team_lead,
				},
			)
		staff.save(ignore_permissions=True)


def _cohort_exists() -> bool:
    return bool(
        frappe.db.exists(
            "CRM Student",
            {"email": ["in", list(_emails().values())]},
        )
    )


def _intake(context: dict[str, str], key: str, name: str) -> str:
    email = _emails()[key]
    existing = frappe.db.get_value("CRM Student", {"email": email}, "name")
    if existing:
        return existing
    result = submit_intake(
        {
            "student_name": f"{_prefix()} {name}",
            "email": email,
            "phone": f"0909000{len(key):02d}0"[:10],
            "campus": context["campus"],
            "owning_team": context["pool"],
            "admission_year": context["admission_year"],
            "enrollment_status": "Mới",
        },
        source_namespace=f"playwright-lead:{_run_id()}",
        source_record_id=f"{_run_id()}:{key}",
        idempotency_key=f"{_prefix()}:{key}:intake",
        correlation_id=f"{_prefix()}:{key}:intake",
    )
    student = result.get("student")
    if result.get("outcome") != "created" or not student:
        raise frappe.ValidationError(f"Could not create fixture {key}: {result}")
    return student


def _route(student: str) -> dict[str, str | None]:
    from crm.fcrm.student_routing import enqueue_student_routing, process_routing_request

    doc = frappe.get_doc("CRM Student", student)
    request = frappe.db.get_value(
        "CRM Student Routing Request", {"student": student}, "name", order_by="creation desc"
    )
    if not request:
        request = enqueue_student_routing(student, trigger="playwright_fixture").name
    result = process_routing_request(request)
    if result.get("status") != "applied":
        raise frappe.ValidationError(f"Fixture routing failed for {student}: {result}")
    # The browser rehearsal runs as the canonical Sale account.  Keep the
    # fixture's active owner deterministic even when other local demo members
    # are present in the round-robin team.
    sale_staff = frappe.db.get_value("CRM Staff", {"user": "sale@gmail.com"}, "name")
    if sale_staff:
        frappe.db.set_value(
            "CRM Student",
            student,
            {"owner_staff": sale_staff, "assigned_to": sale_staff},
            update_modified=False,
        )
    return {
        "ownership_event": frappe.db.get_value(
            "CRM Student Ownership Event", {"student": student}, "name", order_by="event_at desc"
        ),
        "sla_attempt": frappe.db.get_value(
            "CRM Student SLA Attempt", {"student": student}, "name", order_by="creation desc"
        ),
    }


def _interaction(student: str, key: str) -> str:
    summary = f"{_prefix()} evidence {key}"
    existing = frappe.db.get_value("CRM Interaction", {"student": student, "summary": summary}, "name")
    if existing:
        return existing
    interaction_type = frappe.db.get_value("CRM Term", {}, "name")
    if not interaction_type:
        interaction_type = frappe.get_doc(
            {"doctype": "CRM Term", "term_name": "Playwright evidence", "category": "interaction_type"}
        ).insert(ignore_permissions=True).name
    return frappe.get_doc(
        {
            "doctype": "CRM Interaction",
            "student": student,
            "interaction_type": interaction_type,
            "interaction_datetime": now_datetime(),
            "outcome": "Captured",
            "summary": summary,
            "notes": f"{_prefix()}: deterministic lifecycle evidence",
        }
    ).insert(ignore_permissions=True).name


def _document(student: str, key: str) -> str:
    file_name = f"{_prefix()}-{key}.txt"
    existing = frappe.db.get_value(
        "File",
        {
            "attached_to_doctype": "CRM Student",
            "attached_to_name": student,
            "file_name": file_name,
        },
        "name",
    )
    if existing:
        return existing
    return frappe.get_doc(
        {
            "doctype": "File",
            "file_name": file_name,
            "content": b"Playwright qualification evidence\n",
            "attached_to_doctype": "CRM Student",
            "attached_to_name": student,
            "is_private": 1,
        }
    ).insert(ignore_permissions=True).name


def _outcome(student: str, interaction: str) -> str:
    source_key = f"{_prefix()}:{student}:qualified"
    existing = frappe.db.get_value(
        "CRM Student Outcome", {"source_key": source_key}, "name"
    )
    if existing:
        return existing
    from crm.fcrm.student_engagement import record_outcome

    result = record_outcome(
        student=student,
        interaction=interaction,
        outcome_code="qualified",
        continuity_kind="terminal",
        continuity_reason="Playwright fixture qualification evidence.",
        qualification_evidence=[],
        source_key=source_key,
        expected_revision=int(
            frappe.db.get_value("CRM Student", student, "engagement_revision") or 0
        ),
        idempotency_key=f"{_prefix()}:{student}:qualified",
        correlation_id=f"{_prefix()}:{student}:qualified",
    )
    return result["event"]


def _recommendation(student: str) -> str:
    """Create one Sale-readable recommendation for the worklist journey."""
    rule_key = f"{_prefix()}:playwright-recommendation"
    existing = frappe.db.get_value(
        "CRM Recommendation", {"student": student, "rule_key": rule_key}, "name"
    )
    if existing:
        return existing
    interaction = _interaction(student, "recommendation")
    intent_type = frappe.db.get_value("CRM Term", {}, "name")
    if not intent_type:
        intent_type = frappe.get_doc(
            {"doctype": "CRM Term", "term_name": "Playwright intent", "category": "intent_type"}
        ).insert(ignore_permissions=True).name
    intent = frappe.get_doc(
        {
            "doctype": "CRM Intent",
            "interaction": interaction,
            "student": student,
            "intent_type": intent_type,
            "intent_role": "Support",
            "polarity": "Positive",
            "confidence": 90,
            "notes": f"{_prefix()}: recommendation evidence",
        }
    ).insert(ignore_permissions=True)
    recommendation = frappe.get_doc(
        {
            "doctype": "CRM Recommendation",
            "student": student,
            "rule_key": rule_key,
            "source_intent_id": intent.name,
            "condition_version": 1,
            "context_hash": f"{_prefix()}:recommendation",
            "policy_version": "playwright-v1",
            "producer_revision": 1,
            "priority": "medium",
            "status": "new",
            "created_at": now_datetime(),
            "recommended_action": "FOLLOW_UP",
            "reason": f"{_prefix()}: recommendation coverage",
            "evidence": {"fixture_run_id": _run_id()},
        }
    )
    recommendation.run_method("autoname")
    recommendation.flags.from_phase6_command = True
    recommendation.insert(ignore_permissions=True)
    return recommendation.name


def _event(context: dict[str, str]) -> str:
    """Create a run-scoped Event for the Lead Sales read-only attribution UI."""
    title = f"{_prefix()} Attribution Event"
    if frappe.db.exists("CRM Event", title):
        return title
    campaign = seed_demo._ensure_campaign(context["campus"])
    return frappe.get_doc(
        {
            "doctype": "CRM Event",
            "title": title,
            "crm_campaign": campaign,
            "event_date": now_datetime().date(),
            "location": context["campus"],
            "start_datetime": now_datetime(),
            "owner_staff": frappe.db.get_value("CRM Staff", {"user": "sale@gmail.com"}, "name"),
        }
    ).insert(ignore_permissions=True).name


def _enroll(student: str, interaction: str, document: str, outcome: str) -> None:
    current = frappe.db.get_value("CRM Student", student, ["lifecycle_stage", "lifecycle_revision"], as_dict=True)
    if current.lifecycle_stage == "Enrolled":
        return
    from crm.fcrm.student_lifecycle import request_transition

    request_transition(
        student=student,
        target_stage="Enrolled",
        reason="Playwright conversion fixture has qualifying evidence.",
        evidence_refs=[
            {"category": "interaction", "doctype": "CRM Interaction", "name": interaction},
            {"category": "document", "doctype": "File", "name": document},
            {"category": "outcome", "doctype": "CRM Student Outcome", "name": outcome},
        ],
        outcome_code="qualified",
        expected_revision=int(current.lifecycle_revision or 0),
        idempotency_key=f"{_prefix()}:enrolled:lifecycle",
        correlation_id=f"{_prefix()}:enrolled:lifecycle",
    )


def execute() -> dict[str, str]:
    """Create/refresh the four isolated records and write the manifest."""
    _require_disposable()
    preflight()
    frappe.set_user("Administrator")
    # A clean cohort is part of provisioning.  This removes only the four
    # namespaced records and prevents a previous conversion from poisoning a
    # rerun with an already-created Contact.
    # A failed provisioning attempt may leave immutable audit rows behind.
    # Reuse that namespaced cohort instead of deleting audit history on retry.
    if not _cohort_exists():
        reset()
    context = _context()
    detail = _intake(context, "detail", "Detail SLA")
    lifecycle = _intake(context, "lifecycle", "Lifecycle")
    non_enrolled = _intake(context, "non_enrolled", "Not Enrolled")
    enrolled = _intake(context, "enrolled", "Enrolled")
    detail_meta = _route(detail)
    _route(lifecycle)
    _route(non_enrolled)
    _route(enrolled)
    lifecycle_evidence = _interaction(lifecycle, "lifecycle")
    lifecycle_document = _document(lifecycle, "lifecycle")
    lifecycle_outcome = _outcome(lifecycle, lifecycle_evidence)
    enrolled_evidence = _interaction(enrolled, "enrolled")
    enrolled_document = _document(enrolled, "enrolled")
    enrolled_outcome = _outcome(enrolled, enrolled_evidence)
    _enroll(enrolled, enrolled_evidence, enrolled_document, enrolled_outcome)
    # Keep the detail case as the stable Sale-owned worklist/audit fixture.
    # The lifecycle case is intentionally mutated by the Lead Sales ownership test.
    recommendation = _recommendation(detail)
    event = _event(context)
    manifest = {
        "E2E_RUN_ID": _run_id(),
        "PLAYWRIGHT_SITE": frappe.local.site,
        "PLAYWRIGHT_MANIFEST_VERSION": "phase-01",
        "PLAYWRIGHT_INITIAL_CAMPUS_ID": context["campus"],
        "PLAYWRIGHT_INITIAL_POOL_ID": context["pool"],
        "PLAYWRIGHT_DETAIL_STUDENT_ID": detail,
        "PLAYWRIGHT_DETAIL_SLA_ATTEMPT_ID": detail_meta["sla_attempt"],
        "PLAYWRIGHT_LIFECYCLE_STUDENT_ID": lifecycle,
        "PLAYWRIGHT_LIFECYCLE_EVIDENCE_REF": f"interaction:CRM Interaction:{lifecycle_evidence}",
        "PLAYWRIGHT_LIFECYCLE_DOCUMENT_REF": f"document:File:{lifecycle_document}",
        "PLAYWRIGHT_LIFECYCLE_OUTCOME_REF": f"outcome:CRM Student Outcome:{lifecycle_outcome}",
        "PLAYWRIGHT_NON_ENROLLED_STUDENT_ID": non_enrolled,
        "PLAYWRIGHT_ENROLLED_STUDENT_ID": enrolled,
        "PLAYWRIGHT_ENROLLED_LIFECYCLE_REVISION": str(
            frappe.db.get_value("CRM Student", enrolled, "lifecycle_revision") or 0
        ),
        "PLAYWRIGHT_LEAD_SALES_EVENT_ID": event,
        "PLAYWRIGHT_SALE_AUDIT_STUDENT_ID": detail,
        "PLAYWRIGHT_SALE_RECOMMENDATION_ID": recommendation,
        "PLAYWRIGHT_SALE_RECOMMENDATION_STUDENT_ID": detail,
        "PLAYWRIGHT_SALE_RECOMMENDATION_STUDENT_LABEL": frappe.db.get_value("CRM Student", detail, "student_name"),
        "PLAYWRIGHT_SLA_ENGAGEMENT_STUDENT_ID": detail,
        "PLAYWRIGHT_SALE_OWNERSHIP_STUDENT_ID": detail,
        "PLAYWRIGHT_LEAD_SALES_STUDENT_ID": lifecycle,
        "PLAYWRIGHT_LEAD_SALES_OWNERSHIP_TARGET_POOL_ID": context["pool"],
    }
    missing = [key for key, value in manifest.items() if not value]
    if missing:
        raise frappe.ValidationError(f"Playwright fixture is incomplete: {', '.join(missing)}")
    path = _manifest_path()
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    frappe.db.commit()
    print(manifest)
    return manifest


def _delete(doctype: str, names: list[str]) -> None:
    retained_audit_doctypes = {
        "CRM Student SLA Attempt",
        "CRM Student Routing Request",
        "CRM Student Ownership Event",
        "CRM Student Outcome",
        "CRM Student Lifecycle Event",
        "CRM Student Command Receipt",
    }
    if doctype in retained_audit_doctypes:
        # A local shared site is not a disposable database.  Never silently
        # erase immutable audit evidence: the full supervisor must destroy
        # the dedicated site instead.
        if names:
            raise frappe.ValidationError(
                f"E2E_IMMUTABLE_AUDIT: cannot reset {doctype}; destroy the disposable site instead."
            )
        return
    for name in names:
        if frappe.db.exists(doctype, name):
            frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)


def reset() -> dict[str, object]:
    """Remove only records keyed by this fixture's email namespace."""
    _require_disposable()
    preflight()
    frappe.set_user("Administrator")
    students = frappe.get_all(
        "CRM Student", filters={"email": ["in", list(_emails().values())]}, pluck="name", ignore_permissions=True
    )
    if not students:
        _manifest_path().unlink(missing_ok=True)
        return {"prefix": _prefix(), "deleted_students": 0, "reset": True}
    identities = frappe.get_all("CRM Student", filters={"name": ["in", students]}, pluck="identity", ignore_permissions=True)
    cases = frappe.get_all("CRM Student", filters={"name": ["in", students]}, pluck="case_key", ignore_permissions=True)
    conversions = frappe.get_all("CRM Student Contact Conversion", filters={"student": ["in", students]}, pluck="name", ignore_permissions=True)
    contacts = frappe.get_all("CRM Student Contact Conversion", filters={"student": ["in", students]}, pluck="contact", ignore_permissions=True)
    interactions = frappe.get_all("CRM Interaction", filters={"student": ["in", students]}, pluck="name", ignore_permissions=True)
    files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "CRM Student",
            "attached_to_name": ["in", students],
        },
        pluck="name",
        ignore_permissions=True,
    )
    for doctype, field in (
        ("CRM Student SLA Attempt", "student"),
        ("CRM Student Routing Request", "student"),
        ("CRM Student Ownership Event", "student"),
        ("CRM Student Outcome", "student"),
        ("CRM Student Lifecycle Event", "student"),
        ("Task", "student"),
        ("CRM Interaction", "student"),
    ):
        if frappe.db.exists("DocType", doctype):
            _delete(doctype, frappe.get_all(doctype, filters={field: ["in", students]}, pluck="name", ignore_permissions=True))
    if interactions and frappe.db.exists("DocType", "CRM Intent"):
        _delete("CRM Intent", frappe.get_all("CRM Intent", filters={"interaction": ["in", interactions]}, pluck="name", ignore_permissions=True))
    _delete("CRM Student Contact Conversion", conversions)
    _delete("CRM Contact", contacts)
    _delete("File", files)
    _delete("CRM Student Command Receipt", frappe.get_all("CRM Student Command Receipt", filters={"target_student": ["in", students]}, pluck="name", ignore_permissions=True))
    _delete("CRM Student", students)
    _delete("CRM Student Case Key", [name for name in cases if name])
    _delete("CRM Student Identity", [name for name in identities if name])
    _manifest_path().unlink(missing_ok=True)
    frappe.db.commit()
    result = {"prefix": _prefix(), "deleted_students": len(students), "reset": True}
    print(result)
    return result
