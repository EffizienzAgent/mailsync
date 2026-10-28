frappe.listview_settings["Mail Import Address"] = {
	get_indicator(doc) {
		const colors = { Open: "orange", Contact: "green", Ignored: "gray" };
		return [__(doc.decision), colors[doc.decision], `decision,=,${doc.decision}`];
	},
	onload(listview) {
		listview.page.add_actions_menu_item(__("Ignore"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) return;
			frappe
				.call("mailsync.backfill.review.ignore_many", { names })
				.then(() => listview.refresh());
		});
	},
};
