from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from mailsync.backfill import addresses, importer, review, scan
from mailsync.tests.factories import hooks, make_account, make_contact, make_import, make_mail, unique
from mailsync.tests.fake_mailbox import FakeMailbox, raw_mail

LATER = 10**12
FOLDER = "Kunden/Acme"
LINK_HOOK = "mailsync.tests.test_backfill_import.link_hook"
READ_HOOK = "mailsync.tests.test_backfill_import.read_hook"
LINKED = []
READ = []


def link_hook(address):
	LINKED.append(address)
	return [{"link_doctype": "Email Account", "link_name": frappe.db.get_value("Email Account", {})}]


def read_hook(**kwargs):
	READ.append(kwargs)


def address(prefix):
	return f"{unique(prefix).replace(' ', '')}@acme.test"


class TestBackfillImport(IntegrationTestCase):
	def setUp(self):
		addresses.clear()
		LINKED.clear()
		READ.clear()
		self.account = make_account(enable_incoming=0)
		self.account.db_set("create_contact", 1)
		self.own = self.account.email_id
		self.imap = FakeMailbox().folder(FOLDER, uidvalidity=9)
		self.doc = make_import(self.account.name, folders=[{"folder": FOLDER}])
		self.customer = address("jane")
		self.contact = make_contact(self.customer, links=[("Email Account", self.account.name)])
		self.uid = 0

	def add(self, sender, to, subject="Hello", message_id="auto", cc=None):
		self.uid += 1
		if message_id == "auto":
			message_id = f"{unique('m').replace(' ', '')}@acme.test"
		self.imap.add(FOLDER, self.uid, raw_mail(sender, to, subject, message_id, cc=cc))
		return message_id

	def run_import(self, doc=None):
		doc = doc or self.doc
		doc.reload()
		scan.scan(doc, self.imap, LATER)
		doc.reload()
		return importer.run(doc, self.imap, LATER)

	def states(self, doc=None):
		return frappe.get_all(
			"Mail Import Message",
			filters={"mail_import": (doc or self.doc).name},
			order_by="uid asc",
			pluck="state",
		)

	def communication(self, message_id):
		name = frappe.db.get_value("Communication", {"message_id": message_id})
		return name and frappe.get_doc("Communication", name)

	def test_imports_mail_with_contact_as_closed_received(self):
		message_id = self.add(f"Jane <{self.customer}>", self.own)
		self.assertTrue(self.run_import())
		communication = self.communication(message_id)
		self.assertEqual(self.states(), ["Imported"])
		self.assertEqual(
			(communication.status, communication.seen, communication.sent_or_received),
			("Closed", 1, "Received"),
		)
		self.assertEqual(
			(communication.email_account, communication.imap_folder), (self.account.name, FOLDER)
		)
		links = {(link.link_doctype, link.link_name) for link in communication.timeline_links}
		self.assertIn(("Contact", self.contact), links)
		self.assertIn(("Email Account", self.account.name), links)
		self.assertEqual(
			frappe.db.get_value("Mail Import Message", {"mail_import": self.doc.name}, "communication"),
			communication.name,
		)

	def test_outgoing_mail_is_sent(self):
		message_id = self.add(self.own, self.customer)
		self.run_import()
		self.assertEqual(self.communication(message_id).sent_or_received, "Sent")

	def test_all_ignored_is_filtered(self):
		spam = address("spam")
		frappe.get_doc({"doctype": "Mail Ignored Address", "email_id": spam}).insert(ignore_permissions=True)
		message_id = self.add(spam, self.own)
		self.run_import()
		self.assertEqual(self.states(), ["Filtered"])
		self.assertFalse(self.communication(message_id))

	def test_mail_to_self_is_filtered(self):
		self.add(self.own, self.own)
		self.run_import()
		self.assertEqual(self.states(), ["Filtered"])

	def test_undecided_waits_then_imports_after_decision(self):
		stranger = address("stranger")
		message_id = self.add(stranger, self.own)
		self.run_import()
		self.assertEqual(self.states(), ["Pending"])
		review.refresh(self.doc)
		row = frappe.get_doc("Mail Import Address", {"mail_import": self.doc.name, "email_id": stranger})
		row.create_contact()
		self.doc.reload()
		importer.run(self.doc, self.imap, LATER)
		self.assertEqual(self.states(), ["Imported"])
		self.assertTrue(self.communication(message_id))

	def test_no_contact_created_with_create_contact_on(self):
		stranger = address("stranger")
		self.add(self.customer, self.own, cc=stranger)
		self.run_import()
		self.assertEqual(self.states(), ["Imported"])
		self.assertIsNone(addresses.contact_for(stranger))

	def test_present_skipped_and_rerun_idempotent(self):
		known = f"{unique('known').replace(' ', '')}@acme.test"
		make_mail(self.account.name, known)
		self.add(self.customer, self.own, message_id=known)
		fresh = self.add(self.customer, self.own)
		self.run_import()
		self.assertEqual(self.states(), ["Present", "Imported"])
		second = make_import(self.account.name, folders=[{"folder": FOLDER}])
		self.run_import(second)
		self.assertEqual(self.states(second), ["Present", "Present"])
		self.assertEqual(frappe.db.count("Communication", {"message_id": fresh}), 1)

	def test_mail_without_message_id_imported_once(self):
		self.add(self.customer, self.own, subject="No id", message_id=None)
		self.run_import()
		self.run_import()
		second = make_import(self.account.name, folders=[{"folder": FOLDER}])
		self.run_import(second)
		self.assertEqual(
			frappe.db.count("Communication", {"email_account": self.account.name, "subject": "No id"}), 1
		)
		self.assertEqual(self.states(second), ["Present"])

	def test_recipient_links_and_mail_read_hooks_called(self):
		message_id = self.add(self.customer, self.own)
		with hooks("mailsync_recipient_links", [LINK_HOOK]), hooks("mailsync_mail_read", [READ_HOOK]):
			self.run_import()
		self.assertEqual(LINKED, [self.customer])
		self.assertEqual(len(READ), 1)
		self.assertEqual(READ[0]["communication"].name, self.communication(message_id).name)
		self.assertEqual((READ[0]["folder"], READ[0]["sent_or_received"]), (FOLDER, "Received"))
		self.assertEqual(READ[0]["account"], self.account.name)

	def test_import_flag_set_during_insert(self):
		seen = []
		original = frappe.get_doc

		message_id = self.add(self.customer, self.own)
		self.doc.reload()
		scan.scan(self.doc, self.imap, LATER)
		self.doc.reload()

		def spy(*args, **kwargs):
			doc = original(*args, **kwargs)
			if getattr(doc, "doctype", None) == "Communication":
				seen.append(frappe.flags.mailsync_import)
			return doc

		frappe.get_doc = spy
		try:
			importer.run(self.doc, self.imap, LATER)
		finally:
			frappe.get_doc = original
		self.assertTrue(self.communication(message_id))
		self.assertIn(True, seen)
		self.assertFalse(frappe.flags.mailsync_import)

	def test_uidvalidity_changed_folder_skipped_with_error(self):
		self.add(self.customer, self.own)
		self.doc.reload()
		scan.scan(self.doc, self.imap, LATER)
		self.imap.folders[FOLDER]["uidvalidity"] = 10
		self.doc.reload()
		importer.run(self.doc, self.imap, LATER)
		self.assertEqual(self.states(), ["Pending"])
		self.assertIn(FOLDER, self.doc.error)
		self.assertEqual(self.imap.fetched, [])

	def test_broken_mail_marked_failed_others_continue(self):
		self.add(self.customer, self.own, subject="Broken")
		good = self.add(self.customer, self.own, subject="Good")
		original = importer.BackfillMail.create

		def create(mail):
			if mail.subject == "Broken":
				raise ValueError("broken mail")
			return original(mail)

		importer.BackfillMail.create = create
		try:
			self.run_import()
		finally:
			importer.BackfillMail.create = original
		self.assertEqual(self.states(), ["Failed", "Imported"])
		self.assertTrue(self.communication(good))
		self.assertIn(
			"broken mail",
			frappe.db.get_value(
				"Mail Import Message", {"state": "Failed", "mail_import": self.doc.name}, "error"
			),
		)

	def test_removed_folder_not_imported(self):
		self.imap.folder("Privat", uidvalidity=3)
		self.imap.add("Privat", 1, raw_mail(self.customer, self.own, "Private", "p@acme.test"))
		wanted = self.add(self.customer, self.own)
		self.doc.append("folders", {"folder": "Privat"})
		self.doc.save(ignore_permissions=True)
		self.doc.reload()
		scan.scan(self.doc, self.imap, LATER)
		self.doc.reload()
		self.doc.folders = [row for row in self.doc.folders if row.folder == FOLDER]
		self.doc.save(ignore_permissions=True)
		self.assertEqual(
			frappe.db.count("Mail Import Message", {"mail_import": self.doc.name, "folder": "Privat"}), 0
		)
		importer.run(self.doc, self.imap, LATER)
		self.assertTrue(self.communication(wanted))
		self.assertFalse(self.communication("p@acme.test"))

	def test_failing_link_hook_does_not_fail_mail(self):
		message_id = self.add(self.customer, self.own)
		with hooks("mailsync_recipient_links", ["mailsync.tests.test_backfill_import.broken_hook"]):
			self.run_import()
		self.assertEqual(self.states(), ["Imported"])
		self.assertTrue(self.communication(message_id))

	def test_import_flag_set_during_status_update(self):
		from frappe.model.document import Document

		seen = []
		original = Document.run_method

		def spy(doc, method, *args, **kwargs):
			if doc.doctype == "Communication" and method == "before_change":
				seen.append((doc.status, frappe.flags.mailsync_import))
			return original(doc, method, *args, **kwargs)

		self.add(self.customer, self.own)
		with patch.object(Document, "run_method", spy):
			self.run_import()
		self.assertIn(("Closed", True), seen)
		self.assertFalse(frappe.flags.mailsync_import)


def broken_hook(address):
	raise ValueError("broken hook")
