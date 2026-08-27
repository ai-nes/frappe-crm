frappe.ui.form.on("CRM Score Template", {
	refresh(frm) {
		frm.set_query("signal", "rules", function(doc, cdt, cdn) {
			const used = (doc.rules || [])
				.filter(r => r.name !== cdn)
				.map(r => r.signal)
				.filter(Boolean);

			const kind = doc.rules?.find(r => r.name === cdn)?.rule_kind || "positive";
			const filters = [["is_active", "=", 1]];
			filters.push(kind === "negative"
				? ["category", "=", "Negative"]
				: ["category", "in", ["Fit", "Engagement", "Intent"]]);
			if (used.length) filters.push(["name", "not in", used]);
			return { filters, filter_description: "" };
		});
	},
});
