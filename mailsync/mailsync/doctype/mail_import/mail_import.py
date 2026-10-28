import frappe
from frappe import _
from frappe.model.document import Document

from mailsync.backfill import access, jobs, mailbox


class MailImport(Document):
	def validate(self):
		if not access.can_use_account(self.email_account):
			frappe.throw(_("You cannot import from {0}").format(self.email_account), frappe.PermissionError)
		if not frappe.db.get_value("Email Account", self.email_account, "use_imap"):
			frappe.throw(_("Only IMAP accounts can be imported from"))
		if self.from_date and self.to_date and self.from_date > self.to_date:
			frappe.throw(_("From Date must be before To Date"))

	@frappe.whitelist()
	def load_folders(self):
		self.check_permission("write")
		server = mailbox.login(frappe.get_doc("Email Account", self.email_account))
		try:
			return mailbox.folders(server.imap)
		finally:
			jobs.logout(server)

	@frappe.whitelist()
	def start_scan(self):
		jobs.start(self.name, "scan")

	@frappe.whitelist()
	def start_import(self):
		jobs.start(self.name, "import")
