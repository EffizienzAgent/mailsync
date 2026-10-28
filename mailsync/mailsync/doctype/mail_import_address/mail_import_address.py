import frappe
from frappe.model.document import Document

from mailsync.backfill import review


class MailImportAddress(Document):
	@frappe.whitelist()
	def create_contact(self):
		self.check_permission("write")
		self.save()
		review.create_contact(self)
		self.reload()

	@frappe.whitelist()
	def add_to_contact(self, contact=None):
		self.check_permission("write")
		review.add_to_contact(self.email_id, contact or self.contact)
		self.reload()

	@frappe.whitelist()
	def ignore(self):
		self.check_permission("write")
		review.ignore(self.email_id)
		self.reload()
