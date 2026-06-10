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
                f"Skipped rename {school.name!r}: target {expected!r} already exists",
                "rename_high_school_include_province",
            )
            continue

        try:
            frappe.rename_doc(
                "CRM High School",
                school.name,
                expected,
                update_links=True,
                ignore_permissions=True,
            )
        except Exception as e:
            frappe.log_error(
                f"Could not rename {school.name!r} → {expected!r}: {e}",
                "rename_high_school_include_province",
            )

    frappe.db.commit()
