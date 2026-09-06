"""Clarify production Cluster/Zone labels without changing geography references.

This is intentionally limited to the seven geography rows created by the
assignment setup. It updates display labels only; technical names, codes,
and all Ward, Student, assignment, and routing-history links remain unchanged.
"""

from __future__ import annotations

import frappe


PROVINCES = [
	("Đắk Lắk", "DLK"),
	("Đồng Tháp", "DTH"),
	("Ho Chi Minh City", "HCM"),
	("Khánh Hoà", "KHA"),
	("Lâm Đồng", "LDO"),
	("Tây Ninh", "TNI"),
	("TP. Đồng Nai", "DNI"),
]

DISPLAY_PROVINCES = {
	"Đắk Lắk": "Đắk Lắk",
	"Đồng Tháp": "Đồng Tháp",
	"Ho Chi Minh City": "TP.HCM",
	"Khánh Hoà": "Khánh Hòa",
	"Lâm Đồng": "Lâm Đồng",
	"Tây Ninh": "Tây Ninh",
	"TP. Đồng Nai": "Đồng Nai",
}


def run(*, apply: bool = False):
	changes = []
	for province, code in PROVINCES:
		cluster_name = f"{province} - Unassigned Cluster"
		zone_name = f"{province} - Unassigned Zone"
		cluster = frappe.db.get_value(
			"CRM Cluster", {"name": cluster_name, "province": province}, ["name", "cluster_name"], as_dict=True
		)
		zone = frappe.db.get_value(
			"CRM Zone", {"name": zone_name, "cluster": cluster_name}, ["name", "zone_name"], as_dict=True
		)
		if not cluster or not zone:
			frappe.throw(f"Expected production geography is missing for {province}")

		province_label = DISPLAY_PROVINCES.get(province, province)
		cluster_values = {
			"cluster_name": province_label,
		}
		zone_values = {
			"zone_name": f"{province_label} - Toàn địa bàn",
		}
		changes.append(
			{
				"province": province,
				"cluster": {"name": cluster.name, "values": cluster_values},
				"zone": {"name": zone.name, "values": zone_values},
			}
		)
		if apply:
			frappe.db.set_value("CRM Cluster", cluster.name, cluster_values)
			frappe.db.set_value("CRM Zone", zone.name, zone_values)

	if apply:
		frappe.db.commit()
	return {"mode": "apply" if apply else "dry-run", "changes": changes}
