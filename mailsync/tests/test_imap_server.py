import imaplib
import os
import time
import unittest
import uuid
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from mailsync import mail_sync, sent_mail
from mailsync.backfill import addresses, jobs
from mailsync.tests.factories import make_contact, make_import, unique
from mailsync.tests.fake_mailbox import raw_mail

HOST = os.environ.get("MAILSYNC_TEST_IMAP_HOST")
PORT = int(os.environ.get("MAILSYNC_TEST_IMAP_PORT", "3143"))


def message(sender, to, subject, message_id, in_reply_to=None):
	mail = EmailMessage()
	mail["From"] = sender
	mail["To"] = to
	mail["Subject"] = subject
	mail["Date"] = format_datetime(now_datetime().astimezone())
	mail["Message-ID"] = f"<{message_id}>"
	if in_reply_to:
		mail["In-Reply-To"] = f"<{in_reply_to}>"
	mail.set_content("Hello")
	return mail.as_bytes()


@unittest.skipUnless(HOST, "set MAILSYNC_TEST_IMAP_HOST to run against a real IMAP server")
class TestImapServer(IntegrationTestCase):
	def setUp(self):
		frappe.flags.mute_emails = True
		self.address = f"{uuid.uuid4().hex[:10]}@example.test"
		self.imap = imaplib.IMAP4(HOST, PORT)
		self.imap.login(self.address, "secret")
		self.imap.create("Sent")
		self.account = frappe.get_doc(
			{
				"doctype": "Email Account",
				"email_account_name": unique("Server"),
				"email_id": self.address,
				"password": "secret",
				"email_server": HOST,
				"incoming_port": str(PORT),
				"use_imap": 1,
				"use_ssl": 0,
				"use_starttls": 0,
				"enable_incoming": 1,
				"enable_outgoing": 0,
				"create_contact": 0,
				"imap_folder": [{"folder_name": "INBOX"}],
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.flags.mute_emails = False
		self.imap.logout()

	def append(self, folder, raw):
		self.imap.append(folder, None, imaplib.Time2Internaldate(time.time()), raw)

	def sync(self):
		mail_sync.sync_account(self.account.name)

	def communications(self, **filters):
		return frappe.get_all(
			"Communication",
			filters={"email_account": self.account.name, **filters},
			fields=["name", "subject", "status", "sent_or_received", "imap_folder"],
		)

	def test_inbox_sent_and_status_in_one_run(self):
		asked_id = f"{uuid.uuid4().hex}@customer.example"
		moved_id = f"{uuid.uuid4().hex}@customer.example"
		self.append("INBOX", message("customer@customer.example", self.address, "Question", asked_id))
		self.append("INBOX", message("customer@customer.example", self.address, "Moved", moved_id))
		self.sync()

		received = {c.subject: c for c in self.communications(sent_or_received="Received")}
		self.assertEqual(set(received), {"Question", "Moved"})
		self.assertTrue(sent_mail.load_state(self.account.name))

		self.append(
			"Sent",
			message(
				self.address,
				"customer@customer.example",
				"Re: Question",
				f"{uuid.uuid4().hex}@me.example",
				in_reply_to=asked_id,
			),
		)
		self.imap.select("INBOX")
		_, data = self.imap.search(None, f'HEADER Message-ID "<{moved_id}>"')
		self.imap.store(data[0].split()[0], "+FLAGS", "\\Deleted")
		self.imap.expunge()
		self.sync()

		[reply] = self.communications(sent_or_received="Sent")
		self.assertEqual(reply.subject, "Re: Question")
		self.assertEqual(reply.imap_folder, "Sent")
		statuses = {c.subject: c.status for c in self.communications(sent_or_received="Received")}
		self.assertEqual(statuses, {"Question": "Replied", "Moved": "Closed"})

		self.sync()
		self.assertEqual(len(self.communications()), 3)

	def test_backfill_end_to_end(self):
		addresses.clear()
		customer = f"{uuid.uuid4().hex[:10]}@customer.example"
		spammer = f"{uuid.uuid4().hex[:10]}@spam.example"
		make_contact(customer)
		self.imap.create("Kunden")
		self.imap.create("Kunden.Acme")
		recent, old = datetime(2024, 5, 1, 10), datetime(2019, 5, 1, 10)
		wanted = f"{uuid.uuid4().hex}@customer.example"
		self.append("INBOX", raw_mail(customer, self.address, "Wanted", wanted, sent=recent))
		self.append(
			"Kunden.Acme", raw_mail(spammer, self.address, "Spam", f"{uuid.uuid4().hex}@x", sent=recent)
		)
		self.append(
			"Kunden.Acme", raw_mail(customer, self.address, "Too old", f"{uuid.uuid4().hex}@x", sent=old)
		)
		self.account.db_set("enable_incoming", 0)
		doc = make_import(self.account.name, from_date="2020-01-01")
		self.assertIn("Kunden.Acme", doc.load_folders())
		doc.append("folders", {"folder": "INBOX"})
		doc.append("folders", {"folder": "Kunden.Acme"})
		doc.save(ignore_permissions=True)

		def step(name):
			with patch.object(jobs, "enqueue"):
				jobs.start(doc.name, name)
			jobs.work(doc.name, name)
			doc.reload()

		step("scan")
		self.assertEqual((doc.status, doc.total, doc.pending), ("Review", 2, 2))
		[row] = frappe.get_all("Mail Import Address", filters={"mail_import": doc.name}, pluck="name")
		frappe.get_doc("Mail Import Address", row).ignore()
		step("import")
		self.assertEqual((doc.status, doc.imported, doc.filtered), ("Done", 1, 1))
		[communication] = self.communications(message_id=wanted)
		self.assertEqual((communication.status, communication.sent_or_received), ("Closed", "Received"))

		for folder in ("INBOX", "Kunden.Acme"):
			self.imap.select(folder, readonly=True)
			_, data = self.imap.fetch("1:*", "(FLAGS)")
			self.assertFalse(any(b"\\Seen" in part for part in data), folder)
