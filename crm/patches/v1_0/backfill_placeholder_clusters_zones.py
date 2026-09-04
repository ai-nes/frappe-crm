import frappe


def execute():
	"""Phase 8 geography foundation: CRM Ward.zone is now required. Since CRM
	Cluster/CRM Zone are brand new, every existing Ward needs a Zone before this
	patch finishes. Strategy: one placeholder Cluster + one placeholder Zone per
	distinct existing province, all wards of that province point at that
	placeholder Zone. Marked is_placeholder=1 so they're trivially findable for
	real re-clustering later — not treated as final."""
	provinces = frappe.get_all(
		"CRM Ward",
		filters={"province": ["is", "set"]},
		fields=["province"],
		group_by="province",
		pluck="province",
	)

	existing_clusters = set(frappe.get_all("CRM Cluster", pluck="name"))
	existing_zones = set(frappe.get_all("CRM Zone", pluck="name"))

	for province in provinces:
		cluster_name = f"{province} - Unassigned Cluster"
		if cluster_name not in existing_clusters:
			frappe.get_doc(
				{
					"doctype": "CRM Cluster",
					"cluster_name": cluster_name,
					"province": province,
					"is_placeholder": 1,
				}
			).insert(ignore_permissions=True)
			existing_clusters.add(cluster_name)

		zone_name = f"{province} - Unassigned Zone"
		if zone_name not in existing_zones:
			frappe.get_doc(
				{
					"doctype": "CRM Zone",
					"zone_name": zone_name,
					"cluster": cluster_name,
					"is_placeholder": 1,
				}
			).insert(ignore_permissions=True)
			existing_zones.add(zone_name)

		frappe.db.sql(
			"""
			UPDATE `tabCRM Ward`
			SET zone = %s
			WHERE province = %s AND (zone IS NULL OR zone = '')
			""",
			(zone_name, province),
		)

	frappe.db.commit()
