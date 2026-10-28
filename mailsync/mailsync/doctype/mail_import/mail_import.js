frappe.ui.form.on("Mail Import", {
	setup(frm) {
		frappe.realtime.on("mailsync_import", (data) => {
			if (data.name === frm.doc.name && !frm.is_dirty()) frm.reload_doc();
		});
	},

	refresh(frm) {
		if (frm.is_new()) return;
		const running = ["Scanning", "Importing"].includes(frm.doc.status);
		if (running && !frm.doc.__onload?.stale) return;
		frm.add_custom_button(__("Choose Folders"), () => choose_folders(frm));
		if (!frm.doc.folders.length) return;
		frm.add_custom_button(__("Scan"), () => run(frm, "start_scan"));
		if (frm.doc.status === "Draft") return;
		frm.add_custom_button(__("Review Addresses"), () =>
			frappe.set_route("List", "Mail Import Address", { mail_import: frm.doc.name, decision: "Open" })
		);
		frm.add_custom_button(__("Mails"), () =>
			frappe.set_route("List", "Mail Import Message", { mail_import: frm.doc.name })
		);
		frm.add_custom_button(__("Import"), () => run(frm, "start_import")).addClass("btn-primary");
	},
});

function run(frm, method) {
	const call = () => frm.call(method).then(() => frm.reload_doc());
	frm.is_dirty() ? frm.save().then(call) : call();
}

function choose_folders(frm) {
	frm.call("load_folders").then(({ message: folders }) => {
		const chosen = new Set(frm.doc.folders.map((row) => row.folder));
		const dialog = new frappe.ui.Dialog({
			title: __("Choose Folders"),
			fields: [
				{
					fieldname: "folders",
					fieldtype: "MultiCheck",
					columns: 1,
					options: folders.map((folder) => ({
						label: folder,
						value: folder,
						checked: chosen.has(folder),
					})),
				},
			],
			primary_action_label: __("Apply"),
			primary_action({ folders: picked }) {
				frm.doc.folders = frm.doc.folders.filter((row) => picked.includes(row.folder));
				picked
					.filter((folder) => !chosen.has(folder))
					.forEach((folder) => frm.add_child("folders", { folder }));
				frm.refresh_field("folders");
				dialog.hide();
				frm.save();
			},
		});
		dialog.show();
	});
}
