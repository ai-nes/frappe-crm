"""Controlled, idempotent synthetic Student cohort seed for production QA.

This module deliberately lives outside ``crm.demo``.  It uses the Student intake,
ownership, assessment, interaction, application and action service boundaries so
the generated records exercise the same contracts as real admissions traffic.
All values are synthetic and carry an explicit ``[DEMO/QA]`` marker.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import frappe


NAMESPACE = "fcas-diverse-cohort-100-v1"
COUNT = 100
STAGE_STATUSES = {
    "Lead": "Mới",
    "MQL": "Có triển vọng",
    "Applicant": "Đã xác nhận",
    "Enrolled": "Đã nhập học",
    "Lost": "Từ chối",
}
STAGE_COUNTS = (("Lead", 40), ("MQL", 25), ("Applicant", 20), ("Enrolled", 10), ("Lost", 5))
MAJOR_ORDER = (
    "Software Engineering",
    "Artificial Intelligence",
    "Data Science",
    "Digital Marketing",
    "Business Administration",
    "Graphic Design",
)
SOURCE_ORDER = (
    "Cold Calling",
    "Facebook",
    "Website",
    "FPTU Open Day",
    "Reference",
    "Advertisement",
    "Email",
    "Walk In",
)
ADMISSION_METHODS = (
    "Combined",
    "Transcript Review",
    "National High School Exam",
    "Language Certificate Review",
    "Direct Admission",
)
CHANNELS = ("phone", "email", "zalo", "facebook", "webchat", "tiktok")
FAMILY_NAMES = ("Nguyễn", "Trần", "Lê", "Phạm", "Huỳnh", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ")
MIDDLE_NAMES = ("Minh", "Hoàng", "Ngọc", "Gia", "Khánh", "Quốc", "Thảo", "Phương", "Thanh", "Bảo")
GIVEN_NAMES = (
    "Anh", "Bình", "Chi", "Duy", "Giang", "Hà", "Hạnh", "Khang", "Linh", "Long",
    "Mai", "Nam", "Nhi", "Phúc", "Quân", "Trang", "Uyên", "Vân", "Vy", "Yến",
)
BARRIERS = ("Cost", "Capability", "Family", "Information", "Geography", "Competition", "None", "Unknown")


def _stage(index: int) -> str:
    cursor = 0
    for name, amount in STAGE_COUNTS:
        cursor += amount
        if index < cursor:
            return name
    return "Lost"


def _school_rows() -> list[dict[str, Any]]:
    rows = frappe.get_all(
        "CRM High School",
        fields=["name", "province", "ward"],
        order_by="name asc",
        limit_page_length=0,
    )
    if len(rows) < COUNT:
        raise RuntimeError(f"Cần ít nhất {COUNT} trường THPT canonical, hiện có {len(rows)}.")
    return [dict(row) for row in rows]


def _topology() -> dict[str, Any]:
    campus = frappe.db.get_value("CRM Campus", {"is_default": 1}, "name")
    if not campus:
        campus = frappe.db.get_value("CRM Campus", {}, "name", order_by="name asc")
    year = frappe.db.get_value("CRM Admission Year", {}, "name", order_by="name desc")
    team = frappe.db.get_value(
        "CRM Team", {"campus": campus, "team_type": "Sales", "is_active": 1}, "name", order_by="name asc"
    )
    pool = frappe.db.get_value(
        "CRM Student Pool", {"campus": campus, "is_active": 1}, "name", order_by="name asc"
    )
    if not campus or not year or not team or not pool:
        raise RuntimeError("Topology CRM (Campus/Admission Year/Sales Team/Student Pool) chưa đầy đủ.")
    staff = frappe.get_all(
        "CRM Staff",
        filters={"campus": campus, "is_active": 1},
        fields=["name"],
        order_by="name asc",
        limit_page_length=100,
    )
    from crm.fcrm.role_policy import resolve_crm_profile

    eligible_staff = []
    for row in staff:
        if resolve_crm_profile(set(frappe.get_roles(frappe.db.get_value("CRM Staff", row.name, "user") or ""))) != "sales":
            continue
        if frappe.db.exists(
            "CRM Team Membership",
            {"parent": row.name, "parenttype": "CRM Staff", "team": team},
        ):
            eligible_staff.append(row.name)
    if not eligible_staff:
        raise RuntimeError("Không có CRM Staff hợp lệ trong Sales Team để phân công cohort.")
    sources = set(frappe.get_all("CRM Lead Source", pluck="name", limit_page_length=0))
    majors = set(frappe.get_all("CRM Major", pluck="name", limit_page_length=0))
    statuses = set(frappe.get_all("CRM Term", filters={"name": ["in", list(STAGE_STATUSES.values())]}, pluck="name"))
    missing = [name for name in MAJOR_ORDER if name not in majors]
    missing += [name for name in SOURCE_ORDER if name not in sources]
    missing += [name for name in STAGE_STATUSES.values() if name not in statuses]
    if missing:
        raise RuntimeError("Thiếu master canonical: " + ", ".join(sorted(set(missing))))
    return {
        "campus": campus,
        "year": year,
        "team": team,
        "pool": pool,
        "staff": eligible_staff,
        "schools": _school_rows(),
        "offering": frappe.db.get_value(
            "CRM Admission Offering",
            {"status": "Active", "admission_year": year, "campus": campus, "major": "Software Engineering"},
            "name",
        ),
    }


def _student_name(index: int) -> str:
    family = FAMILY_NAMES[index % len(FAMILY_NAMES)]
    middle = MIDDLE_NAMES[(index // len(FAMILY_NAMES)) % len(MIDDLE_NAMES)]
    given = GIVEN_NAMES[(index * 7) % len(GIVEN_NAMES)]
    return f"[DEMO/QA] {family} {middle} {given}"


def _payload(index: int, topology: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    stage = _stage(index)
    key = f"student-{index + 1:03d}"
    school = topology["schools"][(index * 13) % len(topology["schools"])]
    major = MAJOR_ORDER[index % len(MAJOR_ORDER)]
    source = SOURCE_ORDER[(index * 3) % len(SOURCE_ORDER)]
    method = ADMISSION_METHODS[(index * 2) % len(ADMISSION_METHODS)]
    grade, study_stage = (("10", "grade_10"), ("11", "grade_11"), ("12", "grade_12_h1"), ("12", "grade_12_h2"), ("post_exam", "post_exam"))[index % 5]
    if stage in {"Applicant", "Enrolled"}:
        grade, study_stage = ("post_exam", "post_exam")
    name = _student_name(index)
    phone = f"090{2600000 + index:07d}"
    payload = {
        "student_name": name,
        "email": f"fcas.diverse.2026.{index + 1:03d}@example.test",
        "phone": phone,
        "gender": "Nam" if index % 2 == 0 else "Nữ",
        "admission_year": topology["year"],
        "campus": topology["campus"],
        "branch": topology["campus"],
        "owning_team": topology["pool"],
        "enrollment_status": STAGE_STATUSES[stage],
        "source": source,
        "high_school": school["name"],
        "province": school["province"],
        "ward": school["ward"],
        "major": major,
        "current_grade": grade,
        "study_stage": study_stage,
        "correlation_id": f"{NAMESPACE}:{key}",
    }
    if index % 2 == 0:
        payload.update(
            {
                "alt_name": f"[DEMO/QA] Phụ huynh của {name}",
                "alt_phone": f"093{2600000 + index:07d}",
            }
        )
    return payload, {
        "key": key,
        "stage": stage,
        "major": major,
        "method": method,
        "source": source,
        "school": school["name"],
        "owner": topology["staff"][index % len(topology["staff"])],
    }


def _save_extended_fields(student: str, meta: dict[str, Any], payload: dict[str, Any], index: int) -> None:
    doc = frappe.get_doc("CRM Student", student)
    values = {
        "import_source_id": f"{NAMESPACE}:{meta['key']}",
        "admission_method": meta["method"],
        "advertising_channel": ("Biểu mẫu Facebook" if index % 4 == 0 else "Zalo OA" if index % 4 == 1 else "Ngày hội tư vấn" if index % 4 == 2 else "Tư vấn qua website"),
        "cohort_start_year": int(payload["admission_year"]),
        "cohort_end_year": int(payload["admission_year"]) + 3,
        "graduation_score": round(6.5 + (index % 28) * 0.12, 2),
        "transcript_score": round(6.8 + (index % 24) * 0.13, 2),
        "english_converted_score": round(5.0 + (index % 31) * 0.1, 2),
        "total_score": round(20.0 + (index % 51) * 0.11, 2),
        "step": 1 + (index % 5),
        "notes": f"[DEMO/QA] Hồ sơ synthetic cohort đa dạng — giai đoạn {meta['stage']}; nguồn {meta['source']}; ngành {meta['major']}. Không dùng để liên hệ thật.",
    }
    if meta["stage"] == "Enrolled":
        values["enrollment_date"] = "2026-08-15"
    changed = any(str(doc.get(field)) != str(value) for field, value in values.items())
    if not changed:
        return
    previous = getattr(frappe.flags, "student_intake_service", False)
    frappe.flags.student_intake_service = True
    try:
        for field, value in values.items():
            setattr(doc, field, value)
        doc.save(ignore_permissions=True)
    finally:
        frappe.flags.student_intake_service = previous


def _ensure_owner(student: str, meta: dict[str, Any], topology: dict[str, Any]) -> None:
    if meta["stage"] == "Lost":
        return
    doc = frappe.get_doc("CRM Student", student)
    if doc.owner_staff == meta["owner"]:
        return
    from crm.fcrm.student_ownership import change_student_ownership

    change_student_ownership(
        student,
        "owner",
        meta["owner"],
        topology["team"],
        f"[DEMO/QA] Phân công hồ sơ synthetic {meta['key']} cho tư vấn viên.",
        f"{NAMESPACE}:owner:{meta['key']}",
        expected_revision=int(doc.ownership_revision or 0),
        correlation_id=f"{NAMESPACE}:owner:{meta['key']}",
        _internal_service=True,
    )


def _ensure_interactions(student: str, meta: dict[str, Any], index: int) -> int:
    from crm.fcrm.interaction_log import create_interaction

    created = 0
    base = frappe.utils.get_datetime("2026-08-01 09:00:00") + timedelta(days=index % 30, hours=index % 8)
    interaction_count = 2 if index % 5 == 0 else 1
    for offset in range(interaction_count):
        direction = "inbound" if (index + offset) % 2 == 0 else "outbound"
        channel = CHANNELS[(index + offset) % len(CHANNELS)]
        external_id = f"{NAMESPACE}:interaction:{meta['key']}:{offset + 1}"
        if frappe.db.exists("CRM Interaction", {"external_id": external_id}):
            continue
        interaction_type = "Connected" if direction == "inbound" else (
            "Email" if channel == "email" else "Cuộc gọi" if channel == "phone" else "Tin nhắn Chatwoot"
        )
        interaction_name = create_interaction(
            interaction_type=interaction_type,
            student=student,
            summary=f"[DEMO/QA] {meta['stage']} — trao đổi về {meta['major']}",
            notes=f"[DEMO/QA] Nội dung mô phỏng bằng tiếng Việt: học sinh hỏi về chương trình, học phí và lộ trình tuyển sinh; nguồn {meta['source']}.",
            interaction_datetime=base + timedelta(hours=offset),
            channel=channel,
            direction=direction,
            source_namespace=NAMESPACE,
            source_record_id=f"{meta['key']}-touch-{offset + 1}",
            external_id=external_id,
        )
        created += int(bool(interaction_name))
    return created


def _ensure_assessment(student: str, meta: dict[str, Any], index: int) -> bool:
    if meta["stage"] not in {"MQL", "Applicant", "Enrolled"}:
        return False
    marker = f"[DEMO/QA] {NAMESPACE} {meta['key']}"
    if frappe.db.exists("CRM Student Assessment", {"student": student, "reason": ["like", marker + "%"]}):
        return False
    from crm.fcrm.student_assessment import record_student_assessment

    interest = ("High", "Medium", "Low")[index % 3]
    fit = ("High", "Medium", "Low")[((index + 1) // 2) % 3]
    barrier = BARRIERS[index % len(BARRIERS)]
    record_student_assessment(
        student,
        {
            "interest": interest,
            "fit": fit,
            "primary_barrier": barrier,
            "interest_confidence": 65 + (index % 31),
            "fit_confidence": 60 + ((index * 3) % 36),
            "barrier_confidence": 55 + ((index * 5) % 41),
            "enrollment_probability": 35 + ((index * 7) % 61),
        },
        source="manual",
        reason=f"{marker}: dựa trên điểm học tập, mức quan tâm và nội dung trao đổi mô phỏng.",
        evidence_references=[f"{NAMESPACE}:{meta['key']}:profile", f"{NAMESPACE}:{meta['key']}:interaction"],
        confirm=True,
    )
    return True


def _ensure_application(student: str, meta: dict[str, Any], topology: dict[str, Any]) -> bool:
    if meta["stage"] not in {"Applicant", "Enrolled"} or meta["major"] != "Software Engineering" or not topology.get("offering"):
        return False
    from crm.fcrm.admission_application import create_application

    doc = frappe.get_doc("CRM Student", student)
    result = create_application(
        student=student,
        expected_revision=int(doc.engagement_revision or 0),
        idempotency_key=f"{NAMESPACE}:application:{meta['key']}",
        values={
            "offering": topology["offering"],
            "preference": "Primary",
            "preference_order": 1,
            "status": "Enrolled" if meta["stage"] == "Enrolled" else "Under Review",
            "document_total": 5,
            "document_completed": 5 if meta["stage"] == "Enrolled" else 2 + (int(meta["key"][-3:]) % 3),
            "scholarship_percentage": 30 if int(meta["key"][-3:]) % 4 == 0 else 0,
            "deadline": "2026-12-31",
            "submitted_at": "2026-08-20 09:00:00",
            "enrolled_at": "2026-08-25 09:00:00" if meta["stage"] == "Enrolled" else None,
            "source_reference": f"{NAMESPACE}:{meta['key']}:application",
        },
    )
    return not bool(result.get("replayed"))


def _ensure_action(student: str, meta: dict[str, Any], topology: dict[str, Any], index: int) -> bool:
    if meta["stage"] not in {"MQL", "Applicant", "Enrolled"} or index % 4 != 0:
        return False
    from crm.fcrm.student_decision import create_manual_action

    marker = f"[DEMO/QA] Liên hệ {meta['key']}:"
    if frappe.db.exists("CRM Action", {"student": student, "objective": ["like", marker + "%"]}):
        return False
    create_manual_action(
        student,
        ("CALL", "COUNSELING", "MESSAGE")[index % 3],
        marker + f" tư vấn {meta['major']} và giải đáp rào cản học phí.",
        f"{NAMESPACE}:action:v2:{meta['key']}",
        due_at="2026-09-05 09:00:00",
        priority="high" if meta["stage"] == "Applicant" else "medium",
        assignee_staff=meta["owner"],
    )
    return True


def seed(count: int = COUNT, namespace: str = NAMESPACE) -> dict[str, Any]:
    """Seed exactly ``count`` synthetic rows; safe to replay with the same namespace."""
    if namespace != NAMESPACE:
        raise ValueError("Namespace đã được cố định để tránh ghi nhầm cohort production.")
    if int(count) != COUNT:
        raise ValueError(f"Cohort này chỉ cho phép seed đúng {COUNT} học sinh.")
    topology = _topology()
    from crm.fcrm.student_intake import submit_intake

    result = {"namespace": namespace, "requested": COUNT, "created": 0, "replayed": 0, "students": [], "interactions": 0, "assessments": 0, "applications": 0, "actions": 0, "errors": []}
    for index in range(COUNT):
        payload, meta = _payload(index, topology)
        source_id = meta["key"]
        try:
            student = frappe.db.get_value("CRM Student", {"import_source_id": f"{namespace}:{source_id}"}, "name")
            replayed = bool(student)
            if not student:
                intake = submit_intake(
                    payload,
                    source_namespace=namespace,
                    source_record_id=source_id,
                    idempotency_key=f"{namespace}:{source_id}",
                    correlation_id=f"{namespace}:{source_id}",
                )
                if intake.get("outcome") not in {"created", "attached"} or not intake.get("student"):
                    raise RuntimeError(f"Student intake không tạo được: {intake}")
                student = intake["student"]
            _save_extended_fields(student, meta, payload, index)
            _ensure_owner(student, meta, topology)
            if replayed:
                result["replayed"] += 1
            else:
                result["created"] += 1
            result["students"].append(student)
            result["interactions"] += _ensure_interactions(student, meta, index)
            result["assessments"] += int(_ensure_assessment(student, meta, index))
            result["applications"] += int(_ensure_application(student, meta, topology))
            result["actions"] += int(_ensure_action(student, meta, topology, index))
            if (index + 1) % 20 == 0:
                frappe.db.commit()
        except Exception as exc:
            frappe.db.rollback()
            result["errors"].append({"key": source_id, "error": str(exc)})
    frappe.db.commit()
    result["verification"] = verify(namespace)
    return result


def verify(namespace: str = NAMESPACE) -> dict[str, Any]:
    rows = frappe.get_all(
        "CRM Student",
        filters={"import_source_id": ["like", namespace + ":%"]},
        fields=["name", "lifecycle_stage", "enrollment_status", "major", "source", "high_school", "province", "ward", "owner_staff", "email"],
        order_by="name asc",
        limit_page_length=0,
    )
    names = [row.name for row in rows]
    interaction_rows = frappe.get_all(
        "CRM Interaction",
        filters={"external_id": ["like", namespace + ":%"]},
        fields=["name", "student", "external_id", "interaction_type", "channel", "direction"],
        limit_page_length=0,
    )
    assessment_rows = frappe.get_all(
        "CRM Student Assessment",
        filters={"reason": ["like", "[DEMO/QA] " + namespace + "%"]},
        fields=["name", "student", "reason"],
        limit_page_length=0,
    )
    return {
        "namespace": namespace,
        "students": len(rows),
        "unique_emails": len({row.email for row in rows if row.email}),
        "stages": {stage: sum(1 for row in rows if row.lifecycle_stage == stage) for stage, _ in STAGE_COUNTS},
        "majors": {major: sum(1 for row in rows if row.major == major) for major in MAJOR_ORDER},
        "sources": {source: sum(1 for row in rows if row.source == source) for source in SOURCE_ORDER},
        "owners": len({row.owner_staff for row in rows if row.owner_staff}),
        "geography_links_valid": sum(1 for row in rows if row.high_school and row.province and row.ward),
        "interactions": len(interaction_rows),
        "interaction_students": len({row.student for row in interaction_rows if row.student}),
        "interaction_orphans": sum(1 for row in interaction_rows if row.student not in names),
        "interaction_missing_students": [
            f"student-{index + 1:03d}"
            for index in range(len(rows))
            if not any(f":interaction:student-{index + 1:03d}:" in (row.external_id or "") for row in interaction_rows)
        ],
        "interaction_sample": [dict(row) for row in interaction_rows[:6]],
        "assessments": len(assessment_rows),
        "assessment_students": len({row.student for row in assessment_rows if row.student}),
        "assessment_orphans": sum(1 for row in assessment_rows if row.student not in names),
        "applications": frappe.db.count("CRM Admission Application", {"student": ["in", names]}) if names else 0,
        "actions": frappe.db.count("CRM Action", {"student": ["in", names]}) if names else 0,
    }
