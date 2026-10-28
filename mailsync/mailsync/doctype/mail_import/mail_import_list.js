frappe.listview_settings["Mail Import"] = {
	get_indicator(doc) {
		const colors = {
			Draft: "gray",
			Scanning: "blue",
			Review: "orange",
			Importing: "blue",
			Done: "green",
			Failed: "red",
		};
		return [__(doc.status), colors[doc.status], `status,=,${doc.status}`];
	},
};
