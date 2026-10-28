frappe.ui.form.on("Mail Import Address", {
	refresh(frm) {
		if (frm.doc.decision !== "Open") return;
		frm.add_custom_button(__("Create Contact"), () =>
			frm.call("create_contact").then(() => frm.reload_doc())
		);
		frm.add_custom_button(__("Add to Contact"), () => {
			if (!frm.doc.contact) {
				frappe.msgprint(__("Choose a contact"));
				return;
			}
			frm.call("add_to_contact", { contact: frm.doc.contact }).then(() => frm.reload_doc());
		});
		frm.add_custom_button(__("Ignore"), () => frm.call("ignore").then(() => frm.reload_doc()));
	},
});
