from datetime import datetime

import frappe
from frappe.tests import IntegrationTestCase

from mailsync import sent_mail
from mailsync.backfill import addresses, mailbox, scan
from mailsync.tests.factories import make_account, make_import, make_mail, unique
from mailsync.tests.fake_mailbox import FakeMailbox, raw_mail

LATER = 10**12


class TestBackfillScan(IntegrationTestCase):
	def setUp(self):
		addresses.clear()
		self.account = make_account(enable_incoming=0)
		self.own = self.account.email_id
		self.imap = FakeMailbox().folder("INBOX").folder("Kunden/Acme", uidvalidity=5)
		self.doc = make_import(self.account.name, folders=[{"folder": "Kunden/Acme"}])

	def messages(self, **filters):
		return frappe.get_all(
			"Mail Import Message",
			filters={"mail_import": self.doc.name, **filters},
			fields=["uid", "state", "participants", "outgoing", "subject", "message_id", "sender", "size"],
			order_by="uid asc",
		)

	def run_scan(self, deadline=LATER):
		self.doc.reload()
		return scan.scan(self.doc, self.imap, deadline)

	def test_folders_listed_without_noselect(self):
		self.imap.folder("Archiv", flags="\\Noselect \\HasChildren")
		self.assertEqual(mailbox.folders(self.imap), ["INBOX", "Kunden/Acme"])

	def test_criteria(self):
		self.assertEqual(
			mailbox.criteria(5, "2024-01-01", "2024-03-31"),
			"UID 5:* SENTSINCE 01-Jan-2024 SENTBEFORE 01-Apr-2024",
		)
		self.assertEqual(mailbox.criteria(1, None, None), "UID 1:*")

	def test_scan_records_headers_and_participants(self):
		self.imap.add(
			"Kunden/Acme",
			3,
			raw_mail(
				'"Doe, Jane" <Jane@Acme.test>',
				f"Me <{self.own}>, bob@partner.test",
				"Angebot",
				"m1@acme.test",
				cc="CC@Acme.test",
			),
		)
		self.imap.add("Kunden/Acme", 4, raw_mail(self.own, "jane@acme.test", "Antwort", "m2@x.test"))
		self.assertTrue(self.run_scan())
		first, second = self.messages()
		self.assertEqual(first.state, "Pending")
		self.assertEqual(first.subject, "Angebot")
		self.assertEqual(first.message_id, "m1@acme.test")
		self.assertEqual(scan.participant_list(first), ["jane@acme.test", "bob@partner.test", "cc@acme.test"])
		self.assertEqual(scan.participant_names(first)["jane@acme.test"], "Doe, Jane")
		self.assertFalse(first.outgoing)
		self.assertTrue(second.outgoing)
		self.assertEqual(scan.participant_list(second), ["jane@acme.test"])

	def test_scan_marks_present_and_too_large(self):
		known = f"{unique('known').replace(' ', '')}@acme.test"
		make_mail(self.account.name, known)
		self.imap.add("Kunden/Acme", 1, raw_mail("a@acme.test", self.own, "Known", known))
		self.imap.add("Kunden/Acme", 2, raw_mail("a@acme.test", self.own, "Big", "big@acme.test"))
		self.imap.sizes[2] = sent_mail.MAX_MAIL_BYTES + 1
		self.run_scan()
		self.assertEqual([m.state for m in self.messages()], ["Present", "Too Large"])

	def test_scan_respects_date_range(self):
		self.doc.db_set({"from_date": "2024-02-01", "to_date": "2024-02-29"})
		for uid, sent in enumerate(
			[datetime(2024, 1, 31, 12), datetime(2024, 2, 29, 23), datetime(2024, 3, 1, 1)]
		):
			self.imap.add(
				"Kunden/Acme", uid + 1, raw_mail("a@acme.test", self.own, f"m{uid}", f"d{uid}@x", sent=sent)
			)
		self.run_scan()
		self.assertEqual([m.uid for m in self.messages()], [2])

	def test_scan_resumes_after_deadline(self):
		for uid in range(1, scan.CHUNK + 6):
			self.imap.add("Kunden/Acme", uid, raw_mail("a@acme.test", self.own, f"m{uid}", f"r{uid}@x"))
		self.assertFalse(self.run_scan(deadline=0))
		self.assertEqual(len(self.messages()), scan.CHUNK)
		self.assertTrue(self.run_scan())
		self.assertEqual(len(self.messages()), scan.CHUNK + 5)
		self.assertTrue(self.run_scan())
		self.assertEqual(len(self.messages()), scan.CHUNK + 5)

	def test_uidvalidity_change_rescans(self):
		self.imap.add("Kunden/Acme", 1, raw_mail("a@acme.test", self.own, "old", "old@x"))
		self.run_scan()
		self.imap.folder("Kunden/Acme", uidvalidity=6)
		self.imap.add("Kunden/Acme", 1, raw_mail("a@acme.test", self.own, "new", "new@x"))
		self.doc.reload()
		self.doc.folders[0].db_set("scan_done", 0)
		self.run_scan()
		self.assertEqual([m.subject for m in self.messages()], ["new"])

	def test_mailbox_never_written(self):
		self.imap.add("Kunden/Acme", 1, raw_mail("a@acme.test", self.own, "x", "w@x"))
		self.run_scan()
		self.assertTrue(self.imap.readonly)
		self.assertTrue(all(self.imap.readonly))
