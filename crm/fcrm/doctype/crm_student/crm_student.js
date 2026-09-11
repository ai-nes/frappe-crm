frappe.ui.form.on("CRM Student", {
	refresh(frm) {
		const field = frm.fields_dict.graduation_score
		if (!field?.$input) return

		field.$input.attr({
			inputmode: "decimal",
			min: 0,
			max: 30,
			step: 0.01,
		})
	},

	validate(frm) {
		const score = frm.doc.graduation_score
		if (score === null || score === undefined || score === "") return
		if (Number(score) < 0 || Number(score) > 30) {
			frappe.throw("Điểm tốt nghiệp THPT phải từ 0 đến 30.")
		}
	},
})
