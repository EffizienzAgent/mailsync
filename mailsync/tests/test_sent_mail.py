import uuid
from email.message import EmailMessage
from email.utils import format_datetime
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import now_datetime

from mailsync import sent_mail
from mailsync.tests.factories import hooks, make_account, make_mail, unique

SENT = "INBOX.Sent"
LINK_HOOK = "mailsync.tests.test_sent_mail.link_to_todo"
READ_HOOK = "mailsync.tests.test_sent_mail.record_read"
FAILING_READ_HOOK = "mailsync.tests.test_sent_mail.failing_read"
ADDRESSES = []
READ = []


def raw_mail(sender, to, subject, message_id, cc=None, in_reply_to=None):
	mail = EmailMessage()
	mail["From"] = f"Me <{sender}>"
	mail["To"] = to
	if cc:
		mail["Cc"] = cc
	mail["Subject"] = subject
	mail["Date"] = format_datetime(now_datetime().astimezone())
	mail["Message-ID"] = f"<{message_id}>"
	if in_reply_to:
		mail["In-Reply-To"] = f"<{in_reply_to}>"
	mail.set_content("Hello")
	return mail.as_bytes()


class FakeImap:
	def __init__(self, sent=(), uidvalidity=7, flags="\\HasNoChildren \\Sent"):
		self.mails = dict(sent)
		self.uidvalidity = uidvalidity
		self.flags = flags
		self.readonly = []
		self.sizes = {}
		self.status_response = None
		self.fetched = []

	def add(self, uid, raw):
		self.mails[uid] = raw

	def list(self):
		return "OK", [b'(\\HasNoChildren) "." "INBOX"', f'({self.flags}) "." "{SENT}"'.encode()]

	def status(self, folder, items):
		if self.status_response is not None:
			return "OK", [self.status_response]
		uidnext = max(self.mails, default=0) + 1
		return "OK", [f"{folder} (UIDVALIDITY {self.uidvalidity} UIDNEXT {uidnext})".encode()]

	def select(self, folder, readonly=False):
		self.readonly.append(readonly)
		return "OK", [str(len(self.mails)).encode()]

	def uid(self, command, *args):
		if command == "search":
			start = int(args[1].split()[1].split(":")[0])
			uids = [u for u in sorted(self.mails) if u >= start] or sorted(self.mails)[-1:]
			return "OK", [b" ".join(str(u).encode() for u in uids)]
		if command == "fetch" and args[1] == "(RFC822.SIZE)":
			lines = []
			for uid in args[0].split(","):
				size = self.sizes.get(int(uid), len(self.mails[int(uid)]))
				if size is not None:
					lines.append(f"1 (UID {uid} RFC822.SIZE {size})".encode())
			return "OK", lines
		if command == "fetch":
			self.fetched.append(int(args[0]))
			raw = self.mails[int(args[0])]
			return "OK", [(f"1 (UID {args[0]} BODY[] {{{len(raw)}}}".encode(), raw), b")"]
		raise AssertionError(f"unexpected UID {command}")

	def store(self, *args):
		raise AssertionError("mailbox must not be written")

	copy = move = expunge = append = store


def link_to_todo(address):
	ADDRESSES.append(address)
	todo = frappe.db.get_value("ToDo", {"description": address})
	return [{"link_doctype": "ToDo", "link_name": todo}] if todo else []


def record_read(**kwargs):
	READ.append(kwargs)


def failing_read(communication, **kwargs):
	frappe.get_doc({"doctype": "ToDo", "description": f"partial {communication.name}"}).insert(
		ignore_permissions=True
	)
	raise ValueError("consumer broken")


class TestSentMail(IntegrationTestCase):
	def setUp(self):
		self.account = make_account()
		self.account.db_set("create_contact", 0)
		self.address = self.account.email_id
		ADDRESSES.clear()
		READ.clear()

	def sync(self, imap):
		return sent_mail.sync(self.account, imap)

	def mail(self, to, subject, cc=None, in_reply_to=None, message_id=None):
		message_id = message_id or f"{uuid.uuid4().hex}@mail.example"
		return raw_mail(self.address, to, subject, message_id, cc=cc, in_reply_to=in_reply_to)

	def started(self, *old):
		imap = FakeImap({uid: self.mail("old@example.com", f"Old {uid}") for uid in old})
		self.assertEqual(self.sync(imap), [])
		return imap

	def test_first_run_starts_at_uidnext(self):
		imap = self.started(1, 2, 3)
		self.assertFalse(frappe.db.exists("Communication", {"subject": ("like", "Old %")}))
		subject = unique("New")
		imap.add(4, self.mail("new@example.com", subject))
		[name] = self.sync(imap)
		self.assertEqual(frappe.db.get_value("Communication", name, "subject"), subject)
		self.assertEqual(self.sync(imap), [])
		self.assertTrue(all(imap.readonly))

	def test_stored_as_sent_with_folder(self):
		imap = self.started()
		imap.add(1, self.mail("someone@example.com", unique("Offer")))
		[name] = self.sync(imap)
		doc = frappe.get_doc("Communication", name)
		self.assertEqual(doc.sent_or_received, "Sent")
		self.assertEqual(doc.imap_folder, SENT)
		self.assertEqual(doc.sender, self.address)
		self.assertEqual(doc.email_account, self.account.name)

	def test_recipient_links_come_from_hooks(self):
		to = f"{uuid.uuid4().hex[:8]}@to.example"
		cc = f"{uuid.uuid4().hex[:8]}@cc.example"
		todo = frappe.get_doc({"doctype": "ToDo", "description": cc}).insert(ignore_permissions=True)
		imap = self.started()
		imap.add(
			1,
			self.mail(
				f"Them <{to}>",
				unique("Linked"),
				cc=f"{cc}, {self.address}, Administrator <admin@example.com>",
			),
		)
		with hooks("mailsync_recipient_links", [LINK_HOOK]):
			[name] = self.sync(imap)
		self.assertEqual(ADDRESSES, [to, cc])
		links = {
			(link.link_doctype, link.link_name)
			for link in frappe.get_doc("Communication", name).timeline_links
		}
		self.assertIn(("ToDo", todo.name), links)

	def test_without_hooks_no_extra_links(self):
		imap = self.started()
		imap.add(1, self.mail("nobody@example.com", unique("Plain")))
		with hooks("mailsync_recipient_links", []):
			[name] = self.sync(imap)
		links = frappe.get_doc("Communication", name).timeline_links
		self.assertFalse([link for link in links if link.link_doctype == "ToDo"])

	def test_known_contacts_are_linked_by_frappe(self):
		address = f"{uuid.uuid4().hex[:8]}@contact.example"
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Known",
				"email_ids": [{"email_id": address, "is_primary": 1}],
			}
		).insert(ignore_permissions=True)
		imap = self.started()
		imap.add(1, self.mail(address, unique("Contact")))
		with hooks("mailsync_recipient_links", []):
			[name] = self.sync(imap)
		links = {
			(link.link_doctype, link.link_name)
			for link in frappe.get_doc("Communication", name).timeline_links
		}
		self.assertIn(("Contact", contact.name), links)

	def test_known_mail_is_not_imported_twice(self):
		existing = frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Sent",
				"subject": "From the app",
				"sender": self.address,
				"recipients": "customer@example.com",
				"message_id": f"{uuid.uuid4().hex}@other.example",
			}
		).insert(ignore_permissions=True)
		imap = self.started()
		imap.add(1, self.mail("customer@example.com", "From the app", message_id=existing.message_id))
		imap.add(2, self.mail("customer@example.com", "Site ID", message_id=f"x@{frappe.local.site}"))
		self.assertEqual(self.sync(imap), [])
		self.assertEqual(frappe.db.count("Communication", {"message_id": existing.message_id}), 1)

	def test_mail_from_email_queue_is_not_imported(self):
		message_id = f"{uuid.uuid4().hex}@queue.example"
		frappe.get_doc(
			{
				"doctype": "Email Queue",
				"sender": self.address,
				"message_id": f"<{message_id}>",
				"status": "Sent",
				"recipients": [{"recipient": "customer@example.com", "status": "Sent"}],
			}
		).db_insert()
		imap = self.started()
		imap.add(1, self.mail("customer@example.com", "Queued", message_id=message_id))
		self.assertEqual(self.sync(imap), [])

	def test_reply_threads_onto_received_mail(self):
		asked = make_mail(self.account.name, f"{uuid.uuid4().hex}@thread.example")
		imap = self.started()
		imap.add(1, self.mail("customer@example.com", f"Re: {asked.subject}", in_reply_to=asked.message_id))
		[name] = self.sync(imap)
		self.assertEqual(frappe.db.get_value("Communication", name, "in_reply_to"), asked.name)

	def test_failing_mail_is_skipped_and_logged(self):
		imap = self.started()
		imap.add(1, self.mail("a@example.com", unique("Broken")))
		good = unique("Good")
		imap.add(2, self.mail("b@example.com", good))
		original = sent_mail.SentMail.process
		calls = []

		def process(mail):
			calls.append(mail.uid)
			if len(calls) == 1:
				raise ValueError("broken")
			return original(mail)

		with patch.object(sent_mail.SentMail, "process", process), patch.object(frappe, "log_error") as log:
			[name] = self.sync(imap)
		self.assertEqual(frappe.db.get_value("Communication", name, "subject"), good)
		log.assert_called_once()
		self.assertEqual(sent_mail.load_state(self.account.name)["uid"], 2)

	def test_uidvalidity_change_restarts_without_backfill(self):
		imap = self.started(1)
		imap.uidvalidity = 8
		imap.add(2, self.mail("new@example.com", unique("After reset")))
		self.assertEqual(self.sync(imap), [])
		imap.add(3, self.mail("new@example.com", unique("Later")))
		self.assertEqual(len(self.sync(imap)), 1)

	def test_batches_of_fifty(self):
		imap = self.started()
		for uid in range(1, 53):
			imap.add(uid, self.mail("bulk@example.com", unique("Bulk")))
		self.assertEqual(len(self.sync(imap)), 50)
		self.assertEqual(len(self.sync(imap)), 2)

	def test_account_without_sent_folder_is_skipped(self):
		imap = FakeImap({1: self.mail("x@example.com", "x")}, flags="\\HasNoChildren")
		with patch("mailsync.sent_mail.sent_folder", return_value=None):
			self.assertEqual(self.sync(imap), [])
		self.assertFalse(sent_mail.load_state(self.account.name))

	def test_state_is_stored_per_account(self):
		self.started(1, 2)
		self.assertEqual(
			sent_mail.load_state(self.account.name), {"folder": SENT, "uidvalidity": 7, "uid": 2}
		)
		self.assertTrue(frappe.db.get_default(f"mailsync_sent_folder:{self.account.name}"))

	def test_missing_status_fields_skip_the_run(self):
		imap = self.started(1)
		before = sent_mail.load_state(self.account.name)
		imap.add(2, self.mail("new@example.com", unique("Hidden")))
		for response in (b"INBOX.Sent (UIDNEXT 3)", b"INBOX.Sent ()", None):
			imap.status_response = response or (b"",)
			with patch.object(frappe, "log_error") as log:
				self.assertEqual(self.sync(imap), [])
			log.assert_called_once()
			self.assertEqual(sent_mail.load_state(self.account.name), before)

	def test_oversized_and_unsized_mails_are_skipped(self):
		imap = self.started()
		imap.add(1, self.mail("a@example.com", unique("Huge")))
		imap.add(2, self.mail("b@example.com", unique("Unsized")))
		small = unique("Small")
		imap.add(3, self.mail("c@example.com", small))
		imap.sizes = {1: sent_mail.MAX_MAIL_BYTES + 1, 2: None}
		with patch.object(frappe, "log_error") as log:
			[name] = self.sync(imap)
		self.assertEqual(frappe.db.get_value("Communication", name, "subject"), small)
		self.assertEqual(imap.fetched, [3])
		self.assertEqual(log.call_count, 2)
		self.assertEqual(sent_mail.load_state(self.account.name)["uid"], 3)

	def test_batch_is_capped_by_size(self):
		imap = self.started()
		for uid in range(1, 4):
			imap.add(uid, self.mail("bulk@example.com", unique("Big")))
		imap.sizes = dict.fromkeys(range(1, 4), 1000)
		with patch.object(sent_mail, "MAX_BATCH_BYTES", 2500):
			self.assertEqual(len(self.sync(imap)), 2)
			self.assertEqual(sent_mail.load_state(self.account.name)["uid"], 2)
			self.assertEqual(len(self.sync(imap)), 1)

	def app_communication(self, message_id):
		return frappe.get_doc(
			{
				"doctype": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Sent",
				"subject": "From the app",
				"sender": self.address,
				"recipients": "customer@example.com",
				"message_id": message_id,
			}
		).insert(ignore_permissions=True)

	def test_read_hook_gets_imported_mail(self):
		imap = self.started()
		raw = self.mail("someone@example.com", unique("Archived"))
		imap.add(1, raw)
		with hooks("mailsync_mail_read", [READ_HOOK]):
			[name] = self.sync(imap)
		[call] = READ
		self.assertEqual(call.pop("communication").name, name)
		self.assertEqual(
			call, {"raw": raw, "account": self.account.name, "folder": SENT, "sent_or_received": "Sent"}
		)

	def test_read_hook_gets_existing_communication(self):
		known = self.app_communication(f"{uuid.uuid4().hex}@other.example")
		site = self.app_communication(f"{uuid.uuid4().hex}@{frappe.local.site}")
		imap = self.started()
		imap.add(1, self.mail("customer@example.com", "From the app", message_id=known.message_id))
		imap.add(2, self.mail("customer@example.com", "From the app", message_id=site.message_id))
		with hooks("mailsync_mail_read", [READ_HOOK]):
			self.assertEqual(self.sync(imap), [])
		self.assertEqual([call["communication"].name for call in READ], [known.name, site.name])
		self.assertEqual(frappe.db.count("Communication", {"message_id": known.message_id}), 1)

	def test_read_hook_skips_queue_only_mails(self):
		message_id = f"{uuid.uuid4().hex}@queue.example"
		frappe.get_doc(
			{
				"doctype": "Email Queue",
				"sender": self.address,
				"message_id": f"<{message_id}>",
				"status": "Sent",
				"recipients": [{"recipient": "customer@example.com", "status": "Sent"}],
			}
		).db_insert()
		imap = self.started()
		imap.add(1, self.mail("customer@example.com", "Queued", message_id=message_id))
		imap.add(2, self.mail("customer@example.com", "Site", message_id=f"x@{frappe.local.site}"))
		with hooks("mailsync_mail_read", [READ_HOOK]):
			self.assertEqual(self.sync(imap), [])
		self.assertEqual(READ, [])

	def test_failing_read_hook_is_rolled_back_and_logged(self):
		imap = self.started()
		imap.add(1, self.mail("a@example.com", unique("First")))
		imap.add(2, self.mail("b@example.com", unique("Second")))
		with (
			hooks("mailsync_mail_read", [FAILING_READ_HOOK, READ_HOOK]),
			patch.object(frappe, "log_error") as log,
		):
			names = self.sync(imap)
		self.assertEqual(len(names), 2)
		self.assertTrue(all(frappe.db.exists("Communication", name) for name in names))
		self.assertEqual([call["communication"].name for call in READ], names)
		self.assertFalse(frappe.db.exists("ToDo", {"description": ("like", "partial %")}))
		self.assertEqual(log.call_count, 2)
		self.assertEqual(sent_mail.load_state(self.account.name)["uid"], 2)

	def test_read_hook_skips_oversized_mails(self):
		imap = self.started()
		imap.add(1, self.mail("a@example.com", unique("Huge")))
		imap.sizes = {1: sent_mail.MAX_MAIL_BYTES + 1}
		with hooks("mailsync_mail_read", [READ_HOOK]), patch.object(frappe, "log_error"):
			self.assertEqual(self.sync(imap), [])
		self.assertEqual(READ, [])
