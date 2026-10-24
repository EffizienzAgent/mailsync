import re

import frappe
from frappe.tests import IntegrationTestCase

from mailsync import mail_status
from mailsync.tests.factories import hooks, make_account, make_mail


class FakeImap:
	def __init__(self, folders, flags=None, fail=False):
		self.folders = folders
		self.flags = flags or {}
		self.fail = fail
		self.selected = None
		self.readonly = []
		self.searches = 0

	def list(self):
		return "OK", [f'({self.flags.get(name, "")}) "/" "{name}"'.encode() for name in self.folders]

	def select(self, folder, readonly=False):
		if self.fail:
			raise OSError("connection reset")
		self.readonly.append(readonly)
		self.selected = folder.strip('"')
		return "OK", [b"1"]

	def search(self, charset, criteria):
		self.searches += 1
		wanted = set(re.findall(r'"<([^>]+)>"', criteria))
		numbers = [
			str(index + 1).encode()
			for index, headers in enumerate(self.folders[self.selected])
			if wanted & set(re.findall(r"<([^>]+)>", " ".join(headers.values())))
		]
		return "OK", [b" ".join(numbers)]

	def fetch(self, numbers, query):
		mails = self.folders[self.selected]
		data = []
		for number in numbers.split(","):
			headers = mails[int(number) - 1]
			raw = "".join(f"{k}: {v}\r\n" for k, v in headers.items()).encode()
			data += [(f"{number} (BODY[HEADER] {{{len(raw)}}}".encode(), raw), b")"]
		return "OK", data

	def store(self, *args):
		raise AssertionError("mailbox must not be written")

	copy = move = expunge = append = store


def status(mail):
	return frappe.db.get_value("Communication", mail.name, "status")


class TestMailStatus(IntegrationTestCase):
	def setUp(self):
		self.account = make_account().name
		CHANGES.clear()

	def sync(self, imap):
		return mail_status.sync(frappe.get_doc("Email Account", self.account), imap)

	def test_moved_mail_is_closed(self):
		kept = make_mail(self.account, "kept@example.com")
		moved = make_mail(self.account, "moved@example.com")
		imap = FakeImap({"INBOX": [{"Message-ID": "<kept@example.com>"}], "Sent": []})
		self.sync(imap)
		self.assertEqual(status(moved), "Closed")
		self.assertEqual(status(kept), "Open")
		self.assertTrue(all(imap.readonly))

	def test_answered_in_sent_folder_is_replied(self):
		answered = make_mail(self.account, "asked@example.com")
		threaded = make_mail(self.account, "thread@example.com")
		imap = FakeImap(
			{
				"INBOX": [{"Message-ID": "<asked@example.com>"}, {"Message-ID": "<thread@example.com>"}],
				"Gesendete Objekte": [
					{"Message-ID": "<r1@me>", "In-Reply-To": "<asked@example.com>"},
					{"Message-ID": "<r2@me>", "References": "<x@y> <thread@example.com>"},
				],
			},
			flags={"Gesendete Objekte": "\\HasNoChildren \\Sent"},
		)
		self.sync(imap)
		self.assertEqual(status(answered), "Replied")
		self.assertEqual(status(threaded), "Replied")

	def test_sent_folder_found_by_name(self):
		answered = make_mail(self.account, "named@example.com")
		imap = FakeImap(
			{
				"INBOX": [{"Message-ID": "<named@example.com>"}],
				"INBOX.Sent": [{"Message-ID": "<r@me>", "In-Reply-To": "<named@example.com>"}],
			}
		)
		self.sync(imap)
		self.assertEqual(status(answered), "Replied")

	def test_mail_still_in_inbox_unchanged(self):
		mail = make_mail(self.account, "inbox@example.com")
		self.sync(FakeImap({"INBOX": [{"Message-ID": "<inbox@example.com>"}], "Sent": []}))
		self.assertEqual(status(mail), "Open")

	def test_imap_error_changes_nothing(self):
		mail = make_mail(self.account, "error@example.com")
		with self.assertRaises(OSError):
			self.sync(FakeImap({"INBOX": [], "Sent": []}, fail=True))
		self.assertEqual(status(mail), "Open")

	def test_older_than_window_ignored(self):
		old = make_mail(self.account, "old@example.com", days_ago=20)
		self.sync(FakeImap({"INBOX": [], "Sent": []}))
		self.assertEqual(status(old), "Open")

	def test_closed_mail_never_reopened(self):
		mail = make_mail(self.account, "closed@example.com")
		frappe.db.set_value("Communication", mail.name, "status", "Closed")
		self.sync(
			FakeImap(
				{
					"INBOX": [{"Message-ID": "<closed@example.com>"}],
					"Sent": [{"Message-ID": "<r@me>", "In-Reply-To": "<closed@example.com>"}],
				}
			)
		)
		self.assertEqual(status(mail), "Closed")

	def test_searches_batched(self):
		for i in range(5):
			make_mail(self.account, f"batch{i}@example.com")
		imap = FakeImap({"INBOX": [], "Sent": []})
		self.sync(imap)
		self.assertEqual(imap.searches, 2)

	def test_changes_are_passed_to_hooks(self):
		mail = make_mail(self.account, "hook@example.com")
		with hooks("mailsync_status_changed", ["mailsync.tests.test_mail_status.record"]):
			self.sync(FakeImap({"INBOX": [], "Sent": []}))
		self.assertEqual(CHANGES, [{mail.name: "Closed"}])

	def test_no_changes_no_hook_call(self):
		make_mail(self.account, "stays@example.com")
		with hooks("mailsync_status_changed", ["mailsync.tests.test_mail_status.record"]):
			self.sync(FakeImap({"INBOX": [{"Message-ID": "<stays@example.com>"}], "Sent": []}))
		self.assertEqual(CHANGES, [])


CHANGES = []


def record(changes):
	CHANGES.append(changes)
