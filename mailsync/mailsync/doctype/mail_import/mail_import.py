import frappe
from frappe import _
from frappe.model.document import Document

from mailsync.backfill import access


class MailImport(Document):
	def validate(self):
		if not access.can_use_account(self.email_account):
			frappe.throw(_("You cannot import from {0}").format(self.email_account), frappe.PermissionError)
		if not frappe.db.get_value("Email Account", self.email_account, "use_imap"):
			frappe.throw(_("Only IMAP accounts can be imported from"))
		if self.from_date and self.to_date and self.from_date > self.to_date:
			frappe.throw(_("From Date must be before To Date"))
