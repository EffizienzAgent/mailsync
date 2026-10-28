import frappe
from frappe.tests import IntegrationTestCase

from mailsync.backfill import addresses
from mailsync.tests.factories import hooks, make_account, make_contact, make_user

OWN_HOOK = "mailsync.tests.test_backfill_addresses.own_partner"
SUGGEST_HOOK = "mailsync.tests.test_backfill_addresses.suggest"
BROKEN_HOOK = "mailsync.tests.test_backfill_addresses.broken"


def own_partner(address):
	return address == "alias@partner.test"


def suggest(address):
	return {"link_name": f"Company of {address}"}


def broken(address):
	raise ValueError("broken")


class TestBackfillAddresses(IntegrationTestCase):
	def setUp(self):
		addresses.clear()

	def test_account_and_system_user_are_own(self):
		account = make_account()
		user = make_user()
		self.assertTrue(addresses.is_own(account.email_id.upper()))
		self.assertTrue(addresses.is_own(user))
		self.assertFalse(addresses.is_own("stranger@customer.test"))

	def test_hook_marks_own(self):
		with hooks("mailsync_own_address", [OWN_HOOK]):
			self.assertTrue(addresses.is_own("alias@partner.test"))
			self.assertFalse(addresses.is_own("other@partner.test"))

	def test_contact_found_case_insensitive(self):
		contact = make_contact("jane@customer.test")
		self.assertEqual(addresses.contact_for("Jane@Customer.test"), contact)
		self.assertIsNone(addresses.contact_for("nobody@customer.test"))

	def test_ignored(self):
		frappe.get_doc({"doctype": "Mail Ignored Address", "email_id": "spam@x.test"}).insert(
			ignore_permissions=True
		)
		self.assertTrue(addresses.is_ignored("Spam@X.test"))
		self.assertFalse(addresses.is_ignored("ham@x.test"))

	def test_suggestion_from_hook(self):
		with hooks("mailsync_address_suggestion", [SUGGEST_HOOK]):
			self.assertEqual(addresses.suggestion("a@b.test"), {"link_name": "Company of a@b.test"})

	def test_failing_suggestion_hook_is_logged_and_empty(self):
		before = frappe.db.count("Error Log")
		with hooks("mailsync_address_suggestion", [BROKEN_HOOK]):
			self.assertEqual(addresses.suggestion("a@b.test"), {})
		self.assertEqual(frappe.db.count("Error Log"), before + 1)

	def test_link_doctype_from_hook(self):
		self.assertIsNone(addresses.link_doctype())
		with hooks("mailsync_contact_link_doctype", ["ToDo"]):
			self.assertEqual(addresses.link_doctype(), "ToDo")
