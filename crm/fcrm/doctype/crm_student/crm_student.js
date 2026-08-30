// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

async function loadProvinceCode(frm) {
	const province = frm.doc.province
	frm.__provinceCode = null
	if (!province) return

	const response = await frappe.db.get_value("CRM Province", province, "province_code")
	if (frm.doc.province === province) {
		frm.__provinceCode = response.message?.province_code || null
	}
}

async function loadWardCode(frm) {
	const ward = frm.doc.ward
	frm.__wardCode = null
	if (!ward) return

	const response = await frappe.db.get_value("CRM Ward", ward, "ward_code")
	if (frm.doc.ward === ward) {
		frm.__wardCode = response.message?.ward_code || null
	}
}

frappe.ui.form.on("CRM Student", {
	setup(frm) {
		// CRM Term is a shared catalogue; this field must not expose intent,
		// aspiration, or lost-reason terms as valid enrollment statuses.
		frm.set_query("enrollment_status", () => ({
			filters: {
				category: "enrollment_status",
				is_active: 1,
			},
		}))

		frm.set_query("aspiration", () => ({
			filters: {
				category: "aspiration",
				is_active: 1,
				term_name: ["in", ["NV1", "NV2", "NV3"]],
			},
		}))

		frm.set_query("ward", () => ({
			filters: frm.doc.province
				? { province: frm.doc.province }
				: { name: ["=", ""] },
		}))

		frm.set_query("high_school", () => {
			if (!frm.__provinceCode || !frm.__wardCode) {
				return { filters: { name: ["=", ""] } }
			}
			return {
				filters: {
					province_code: frm.__provinceCode,
					ward_code: frm.__wardCode,
				},
			}
		})
	},

	refresh(frm) {
		void loadProvinceCode(frm)
		void loadWardCode(frm)
	},

	province(frm) {
		frm.set_value("ward", null)
		frm.set_value("high_school", null)
		frm.__wardCode = null
		void loadProvinceCode(frm)
	},

	ward(frm) {
		frm.set_value("high_school", null)
		void loadWardCode(frm)
	},
})
