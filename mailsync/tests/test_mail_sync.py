from unittest.mock import patch

import frappe
from frappe.email.doctype.email_account.email_account import EmailAccount
from frappe.tests import IntegrationTestCase

from mailsync import mail_sync
from mailsync.hooks import scheduler_events
from mailsync.tests.factories import make_account


class FakeServer:
	def __init__(self):
		self.imap = object()
		self.logouts = 0

	def logout(self):
		self.logouts += 1


class TestMailSync(IntegrationTestCase):
	def setUp(self):
		self.account = make_account()
		self.server = FakeServer()

	def run_sync(self, receive=None, sent=None, status=None, login=None):
		calls = []

		def record(name, effect):
			def run(*args):
				calls.append((name, args))
				if effect:
					effect(*args)

			return run

		with (
			patch.object(
				EmailAccount, "get_incoming_server", side_effect=login, return_value=self.server
			) as get,
			patch.object(EmailAccount, "receive", autospec=True, side_effect=record("receive", receive)),
			patch.object(mail_sync.sent_mail, "sync", side_effect=record("sent", sent)),
			patch.object(mail_sync.mail_status, "sync", side_effect=record("status", status)),
			patch.object(type(frappe.local.db), "commit"),
			patch.object(type(frappe.local.db), "rollback"),
			patch.object(frappe, "log_error") as log,
		):
			mail_sync.sync_account(self.account.name)
		return calls, get, log

	def test_scheduled_every_two_minutes(self):
		self.assertEqual(scheduler_events["cron"]["*/2 * * * *"], ["mailsync.mail_sync.sync_all"])

	def test_jobs_are_enqueued_by_dotted_path(self):
		self.assertEqual(mail_sync.SYNC_ACCOUNT, "mailsync.mail_sync.sync_account")
		self.assertIs(frappe.get_attr(mail_sync.SYNC_ACCOUNT), mail_sync.sync_account)
		self.assertIsNotNone(frappe.get_attr(mail_sync.STOCK_PULL))

	def test_one_login_for_all_steps(self):
		calls, get, log = self.run_sync()
		self.assertEqual([name for name, _ in calls], ["receive", "sent", "status"])
		get.assert_called_once()
		self.assertEqual(calls[1][1][1], self.server.imap)
		self.assertEqual(calls[2][1][1], self.server.imap)
		self.assertEqual(self.server.logouts, 1)
		log.assert_not_called()

	def test_receive_reuses_the_open_connection(self):
		def receive(doc):
			self.assertIs(doc.get_incoming_server(in_receive=True), self.server)
			doc.get_incoming_server().logout()
			self.assertEqual(self.server.logouts, 0)

		_, get, _ = self.run_sync(receive=receive)
		get.assert_called_once()
		self.assertEqual(self.server.logouts, 1)

	def test_failing_step_does_not_stop_the_others(self):
		def fail(*args):
			raise OSError("connection reset")

		for failing in ("receive", "sent", "status"):
			with self.subTest(failing=failing):
				calls, _, log = self.run_sync(**{failing: fail})
				self.assertEqual([name for name, _ in calls], ["receive", "sent", "status"])
				title = log.call_args.kwargs["title"]
				self.assertIn(self.account.name, title)
				log.assert_called_once()

	def test_imap_socket_timeout_defaults_to_a_minute(self):
		with patch.dict(frappe.conf, {"imap_timeout": None}):
			self.run_sync()
			self.assertEqual(frappe.conf.imap_timeout, 60)
		with patch.dict(frappe.conf, {"imap_timeout": 120}):
			self.run_sync()
			self.assertEqual(frappe.conf.imap_timeout, 120)

	def test_login_failure_is_logged_and_skips_steps(self):
		calls, _, log = self.run_sync(login=OSError("timeout"))
		self.assertEqual(calls, [])
		self.assertEqual(log.call_args.kwargs["title"], f"Mail sync login failed: {self.account.name}")

	def test_sync_all_enqueues_per_account_on_default_queue_unless_queued(self):
		self.account.db_set("awaiting_password", 0)
		pop = make_account()
		pop.db_set({"awaiting_password": 0, "use_imap": 0})
		hosted = make_account()
		hosted.db_set({"awaiting_password": 0, "service": "Frappe Mail"})
		busy = make_account()
		busy.db_set("awaiting_password", 0)
		queued = {frappe.local.site: [f"pull_from_email_account|{busy.name}"]}
		with (
			patch.object(mail_sync, "get_jobs", return_value=queued),
			patch.object(frappe, "enqueue") as enqueue,
		):
			mail_sync.sync_all()
		jobs = {call.kwargs["email_account"]: call for call in enqueue.call_args_list}
		self.assertNotIn(busy.name, jobs)
		self.assertEqual(jobs[self.account.name].args, (mail_sync.SYNC_ACCOUNT,))
		self.assertEqual(jobs[pop.name].args, (mail_sync.STOCK_PULL,))
		self.assertEqual(jobs[hosted.name].args, (mail_sync.STOCK_PULL,))
		for name in (self.account.name, pop.name, hosted.name):
			self.assertEqual(jobs[name].kwargs["queue"], "default")
			self.assertEqual(jobs[name].kwargs["timeout"], 600)
			self.assertEqual(jobs[name].kwargs["job_name"], f"pull_from_email_account|{name}")

	def test_accounts_awaiting_password_are_skipped(self):
		with patch.object(mail_sync, "get_jobs", return_value={frappe.local.site: []}):
			with patch.object(frappe, "enqueue") as enqueue:
				mail_sync.sync_all()
		names = {call.kwargs["email_account"] for call in enqueue.call_args_list}
		self.assertNotIn(self.account.name, names)

	def test_worker_can_import_module_without_site(self):
		import subprocess
		import sys

		result = subprocess.run(
			[sys.executable, "-c", "import mailsync.mail_sync"], capture_output=True, text=True
		)
		self.assertEqual(result.returncode, 0, result.stderr)
