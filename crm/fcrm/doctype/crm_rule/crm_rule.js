frappe.ui.form.on("CRM Rule", {
	refresh(frm) {
		// Rules belong to an immutable version. Lifecycle transitions are exposed
		// by the CRM Rule Version admin API, never by stale per-rule publish or
		// archive buttons.
		if (["active", "superseded"].includes(frm.doc.status)) {
			frm.set_read_only();
			frm.dashboard.set_headline(
				__("This rule is part of an immutable snapshot. Clone the version to edit it.")
			);
		}
	},
});
