import frappe


def execute():
    schools = frappe.get_all(
        "CRM High School",
        fields=["name", "school_name", "province_code"],
        order_by="name asc",
    )

    for school in schools:
        if not school.province_code:
            continue

        expected = f"{school.school_name} - {school.province_code}"
        if school.name == expected:
            continue

        if frappe.db.exists("CRM High School", expected):
            frappe.log_error(
                title="rename_high_school: skip",
                message=f"Target already exists: {school.name!r} → {expected!r}",
            )
            continue

        try:
            frappe.rename_doc(
                "CRM High School",
                school.name,
                expected,
                ignore_permissions=True,
            )
        except Exception as e:
            frappe.log_error(
                title="rename_high_school: failed",
                message=f"{school.name!r} → {expected!r}\n{e}",
            )

    frappe.db.commit()
