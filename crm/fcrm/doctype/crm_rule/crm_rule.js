frappe.ui.form.on("CRM Rule", {
	refresh(frm) {
		const canManage = ["System Manager", "Admissions Director", "Business Admin"].some((role) =>
			frappe.user.has_role(role)
		)
		if (!canManage || frm.is_new()) return

		if (["published", "archived"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Edit as Draft"), () => {
				frappe.call({
					method: "crm.api.rule_engine.reopen_rule",
					args: { name: frm.doc.name },
					freeze: true,
					freeze_message: __("Reopening CRM Rule..."),
					callback: () => frm.reload_doc(),
				})
			})
		}

		if (frm.doc.status === "draft") {
			frm.add_custom_button(__("Publish"), () => {
				frappe.call({
					method: "crm.api.rule_engine.publish_rule",
					args: { name: frm.doc.name, expected_revision: frm.doc.revision || 0 },
					freeze: true,
					freeze_message: __("Publishing CRM Rule..."),
					callback: () => frm.reload_doc(),
				})
			})
		}

		if (frm.doc.status === "published") {
			frm.add_custom_button(__("Archive"), () => {
				frappe.prompt(
					[
						{
							fieldname: "reason",
							fieldtype: "Small Text",
							label: __("Reason"),
							reqd: 1,
						}
					],
					(values) => {
						frappe.call({
							method: "crm.api.rule_engine.archive_rule",
							args: { name: frm.doc.name, reason: values.reason },
							freeze: true,
							freeze_message: __("Archiving CRM Rule..."),
							callback: () => frm.reload_doc(),
						})
					},
					__("Archive CRM Rule"),
					__("Archive")
				)
			})
		}
	},
})
