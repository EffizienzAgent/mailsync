import frappe
from frappe import _
from frappe.model.document import Document

from mailsync.backfill import access, jobs, mailbox, review


class MailImport(Document):
	def validate(self):
		if not access.can_use_account(self.email_account):
			frappe.throw(_("You cannot import from {0}").format(self.email_account), frappe.PermissionError)
		if not frappe.db.get_value("Email Account", self.email_account, "use_imap"):
			frappe.throw(_("Only IMAP accounts can be imported from"))
		if self.from_date and self.to_date and self.from_date > self.to_date:
			frappe.throw(_("From Date must be before To Date"))
		if self.status != "Draft" and any(
			self.has_value_changed(field) for field in ("email_account", "from_date", "to_date")
		):
			frappe.throw(_("Account and dates cannot change after the first scan. Create a new import."))

	def on_update(self):
		chosen = [row.folder for row in self.folders]
		removed = {"mail_import": self.name, "state": ("!=", "Imported")}
		if chosen:
			removed["folder"] = ("not in", chosen)
		if frappe.db.exists("Mail Import Message", removed):
			frappe.db.delete("Mail Import Message", removed)
			review.refresh(self)

	def on_trash(self):
		frappe.db.delete("Mail Import Message", {"mail_import": self.name})
		frappe.db.delete("Mail Import Address", {"mail_import": self.name})

	def onload(self):
		self.set_onload("stale", self.status in jobs.RUNNING.values() and jobs.stale(self))

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
