import frappe

from crm.install import add_default_fields_layout


def execute():
    """Recreate all Fields Layout entries with updated field groupings and new High School layouts."""
    doctypes = [
        "CRM Contact",
        "CRM Student",
        "CRM High School",
        "CRM Person",
        "CRM Campaign",
        "CRM Event",
    ]
    layout_types = ["Quick Entry", "Side Panel", "Data Fields"]

    for doctype in doctypes:
        for layout_type in layout_types:
            name = f"{doctype}-{layout_type}"
            if frappe.db.exists("Fields Layout", name):
                frappe.delete_doc("Fields Layout", name, force=True)

    add_default_fields_layout(force=True)
