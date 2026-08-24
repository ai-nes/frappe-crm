frappe.ui.form.on("CRM Score Template", {
	refresh(frm) {
		frm.set_query("signal", "rules", function(doc, cdt, cdn) {
			const used = (doc.rules || [])
				.filter(r => r.name !== cdn)
				.map(r => r.signal)
				.filter(Boolean);

			const filters = [
				["category", "in", ["Fit", "Engagement", "Intent"]],
				["is_active", "=", 1],
			];
			if (used.length) filters.push(["name", "not in", used]);
			return { filters, filter_description: "" };
		});

		frm.set_query("signal", "negative_rules", function(doc, cdt, cdn) {
			const used = (doc.negative_rules || [])
				.filter(r => r.name !== cdn)
				.map(r => r.signal)
				.filter(Boolean);

			const filters = [
				["category", "=", "Negative"],
				["is_active", "=", 1],
			];
			if (used.length) filters.push(["name", "not in", used]);
			return { filters, filter_description: "" };
		});
	},
});
