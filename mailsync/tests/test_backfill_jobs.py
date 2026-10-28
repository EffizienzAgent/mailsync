from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_to_date, now_datetime

from mailsync.backfill import addresses, jobs, scan
from mailsync.tests.factories import make_account, make_contact, make_import, unique
from mailsync.tests.fake_mailbox import FakeMailbox, raw_mail

FOLDER = "INBOX"


class Server:
	def __init__(self, imap):
		self.imap = imap
		self.logged_out = False

	def logout(self):
		self.logged_out = True


class TestBackfillJobs(IntegrationTestCase):
	def setUp(self):
		addresses.clear()
		self.account = make_account(enable_incoming=0)
		self.own = self.account.email_id
		self.imap = FakeMailbox().folder(FOLDER)
		self.server = Server(self.imap)
		self.doc = make_import(self.account.name, folders=[{"folder": FOLDER}])
		self.customer = f"{unique('c').replace(' ', '')}@acme.test"
		self.stranger = f"{unique('s').replace(' ', '')}@acme.test"
		make_contact(self.customer)
		self.queued = []

	def add(self, uid, sender):
		self.imap.add(
			FOLDER, uid, raw_mail(sender, self.own, f"m{uid}", f"{unique('id').replace(' ', '')}@x")
		)

	def work(self, step):
		with (
			patch.object(jobs.mailbox, "login", return_value=self.server),
			patch.object(jobs, "enqueue", side_effect=lambda name, step: self.queued.append(step)),
		):
			jobs.work(self.doc.name, step)
		self.doc.reload()

	def start(self, step):
		with patch.object(jobs, "enqueue", side_effect=lambda name, step: self.queued.append(step)):
			jobs.start(self.doc.name, step)
		self.doc.reload()

	def test_work_scan_then_review_status(self):
		self.add(1, self.customer)
		self.add(2, self.stranger)
		self.start("scan")
		self.assertEqual((self.doc.status, self.queued), ("Scanning", ["scan"]))
		self.work("scan")
		self.assertEqual(self.doc.status, "Review")
		self.assertTrue(self.server.logged_out)
		self.assertEqual(
			frappe.get_all("Mail Import Address", filters={"mail_import": self.doc.name}, pluck="email_id"),
			[self.stranger],
		)
		self.assertEqual((self.doc.total, self.doc.pending), (2, 2))

	def test_import_done_or_back_to_review(self):
		self.add(1, self.customer)
		self.add(2, self.stranger)
		self.start("scan")
		self.work("scan")
		self.start("import")
		self.work("import")
		self.assertEqual((self.doc.status, self.doc.imported, self.doc.pending), ("Review", 1, 1))
		frappe.get_doc("Mail Import Address", {"mail_import": self.doc.name}).ignore()
		self.start("import")
		self.work("import")
		self.assertEqual((self.doc.status, self.doc.filtered, self.doc.pending), ("Done", 1, 0))

	def test_work_requeues_when_unfinished(self):
		for uid in range(1, 4):
			self.add(uid, self.customer)
		self.start("scan")
		self.queued.clear()
		with patch.object(scan, "CHUNK", 1), patch.object(jobs, "BUDGET", -1):
			self.work("scan")
		self.assertEqual((self.doc.status, self.queued, self.doc.total), ("Scanning", ["scan"], 1))

	def test_login_failure_sets_failed(self):
		self.start("scan")
		with patch.object(jobs.mailbox, "login", side_effect=Exception("auth failed")):
			jobs.work(self.doc.name, "scan")
		self.doc.reload()
		self.assertEqual(self.doc.status, "Failed")
		self.assertIn("auth failed", self.doc.error)

	def test_start_refuses_while_running(self):
		self.start("scan")
		with self.assertRaises(frappe.ValidationError):
			self.start("import")

	def test_start_allowed_when_running_job_is_stale(self):
		self.start("scan")
		stale = add_to_date(now_datetime(), seconds=-(jobs.TIMEOUT + 60))
		frappe.db.set_value("Mail Import", self.doc.name, "modified", stale, update_modified=False)
		self.start("scan")
		self.assertEqual(self.queued, ["scan", "scan"])

	def test_work_ignores_unexpected_status(self):
		with patch.object(jobs.mailbox, "login") as login:
			jobs.work(self.doc.name, "scan")
		login.assert_not_called()

	def test_rescan_picks_up_new_mail(self):
		self.add(1, self.customer)
		self.start("scan")
		self.work("scan")
		self.add(2, self.customer)
		self.start("scan")
		self.work("scan")
		self.assertEqual(self.doc.total, 2)
