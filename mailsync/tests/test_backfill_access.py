import frappe
from frappe.tests import IntegrationTestCase

from mailsync.tests.factories import make_account, make_import, make_user


class TestBackfillAccess(IntegrationTestCase):
	def setUp(self):
		self.account = make_account(enable_incoming=0)
		self.owner = make_user(accounts=[self.account.name])
		self.stranger = make_user()
		self.mail_import = make_import(self.account.name)
		self.message = frappe.get_doc(
			{"doctype": "Mail Import Message", "mail_import": self.mail_import.name, "uid": 1}
		).insert(ignore_permissions=True)
		self.address = frappe.get_doc(
			{"doctype": "Mail Import Address", "mail_import": self.mail_import.name, "email_id": "a@x.test"}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def visible(self, doctype):
		return frappe.get_list(doctype, filters={"name": self.record(doctype).name}, pluck="name")

	def record(self, doctype):
		return {
			"Mail Import": self.mail_import,
			"Mail Import Message": self.message,
			"Mail Import Address": self.address,
		}[doctype]

	def test_assigned_user_sees_own_import(self):
		frappe.set_user(self.owner)
		for doctype in ("Mail Import", "Mail Import Message", "Mail Import Address"):
			with self.subTest(doctype=doctype):
				self.assertTrue(frappe.has_permission(doctype, "read", self.record(doctype)))
				self.assertEqual(self.visible(doctype), [self.record(doctype).name])

	def test_other_user_cannot_read_or_create(self):
		frappe.set_user(self.stranger)
		for doctype in ("Mail Import", "Mail Import Message", "Mail Import Address"):
			with self.subTest(doctype=doctype):
				self.assertFalse(frappe.has_permission(doctype, "read", self.record(doctype)))
				self.assertEqual(self.visible(doctype), [])
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Mail Import", "email_account": self.account.name}).insert()

	def test_assigned_user_can_create(self):
		frappe.set_user(self.owner)
		doc = frappe.get_doc({"doctype": "Mail Import", "email_account": self.account.name}).insert()
		self.assertEqual(doc.status, "Draft")

	def test_system_manager_sees_all(self):
		admin = make_user(roles=["System Manager"])
		frappe.set_user(admin)
		self.assertTrue(frappe.has_permission("Mail Import", "read", self.mail_import))
		self.assertEqual(self.visible("Mail Import Message"), [self.message.name])

	def test_pop3_account_rejected(self):
		pop = make_account(use_imap=0, imap_folder=[])
		with self.assertRaises(frappe.ValidationError):
			make_import(pop.name)

	def test_account_and_dates_locked_after_draft(self):
		self.mail_import.db_set("status", "Review")
		self.mail_import.reload()
		self.mail_import.from_date = "2020-01-01"
		with self.assertRaises(frappe.ValidationError):
			self.mail_import.save(ignore_permissions=True)

	def test_delete_import_removes_rows(self):
		frappe.delete_doc("Mail Import", self.mail_import.name, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Mail Import Message", self.message.name))
		self.assertFalse(frappe.db.exists("Mail Import Address", self.address.name))

	def test_desk_user_cannot_edit_messages_or_read_ignore_list(self):
		frappe.set_user(self.owner)
		self.assertTrue(frappe.has_permission("Mail Import Message", "read", self.message))
		self.assertFalse(frappe.has_permission("Mail Import Message", "write", self.message))
		self.assertFalse(frappe.has_permission("Mail Ignored Address", "read"))
		self.assertTrue(frappe.has_permission("Mail Ignored Address", "create"))
