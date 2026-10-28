import frappe
from frappe.model.document import Document


class MailImportMessage(Document):
	pass


def on_doctype_update():
	frappe.db.add_index(
		"Mail Import Message", ["mail_import", "folder", "uidvalidity", "uid"], "mail_import_folder_uid_index"
	)
	frappe.db.add_index("Mail Import Message", ["mail_import", "state"], "mail_import_state_index")
