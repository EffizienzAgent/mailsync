from email import message_from_string
from unittest.mock import patch

import frappe
from frappe.email.email_body import get_email
from frappe.tests import IntegrationTestCase

from mailsync import references
from mailsync.tests.factories import unique


def communication(message_id=None, parent=None):
	return frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Received",
			"subject": unique("Thread"),
			"content": "Body",
			"sender": "customer@example.com",
			"message_id": message_id,
			"in_reply_to": parent,
		}
	).insert(ignore_permissions=True)


def message_id():
	return f"{unique('mail').replace(' ', '.')}@example.com"


def chain(length):
	ids, parent = [], None
	for _ in range(length):
		ids.append(message_id())
		parent = communication(ids[-1], parent).name
	return ids


def raw_reply(in_reply_to=None, bracket=True):
	mail = get_email(
		recipients=["customer@example.com"],
		sender="me@example.test",
		subject="Re: Thread",
		formatted="<p>Reply</p>",
		email_account=frappe._dict(name="Mailbox", email_id="me@example.test"),
	)
	mail.set_message_id(None)
	if in_reply_to:
		mail.set_in_reply_to(f"<{in_reply_to}>" if bracket else in_reply_to)
	return mail.as_string()


def reply(in_reply_to=None, bracket=True):
	return message_from_string(raw_reply(in_reply_to, bracket))


def header(ids):
	return " ".join(f"<{mid}>" for mid in ids)


class TestReferences(IntegrationTestCase):
	def test_simple_reply_references_parent(self):
		ids = chain(1)
		self.assertEqual(reply(ids[0])["References"], header(ids))

	def test_reply_to_reply_starts_with_root(self):
		ids = chain(3)
		self.assertEqual(reply(ids[-1])["References"], header(ids))

	def test_message_id_with_brackets_is_normalized(self):
		root = message_id()
		parent = message_id()
		communication(parent, communication(f"<{root}>").name)
		self.assertEqual(reply(parent)["References"], header([root, parent]))

	def test_ancestor_without_message_id_is_skipped(self):
		root, parent = message_id(), message_id()
		middle = communication(None, communication(root).name)
		communication(parent, middle.name)
		self.assertEqual(reply(parent)["References"], header([root, parent]))

	def test_unknown_parent_references_in_reply_to(self):
		parent = message_id()
		self.assertEqual(reply(parent)["References"], header([parent]))

	def test_no_in_reply_to_no_references(self):
		self.assertIsNone(reply()["References"])

	def test_long_thread_keeps_root_and_newest(self):
		ids = chain(references.MAX_IDS + 5)
		expected = [ids[0], *ids[-(references.MAX_IDS - 1) :]]
		self.assertEqual(reply(ids[-1])["References"].split(), [f"<{mid}>" for mid in expected])

	def test_long_ids_fit_one_line(self):
		ids = [f"{'x' * 200}.{n}@example.com" for n in range(6)]
		parent = None
		for mid in ids:
			parent = communication(mid, parent).name
		raw = raw_reply(ids[-1])
		mail = message_from_string(raw)
		self.assertEqual(mail["References"].split()[0], f"<{ids[0]}>")
		self.assertEqual(mail["References"].split()[-1], f"<{ids[-1]}>")
		self.assertTrue(all(len(line) <= references.MAX_LINE for line in raw.splitlines()))

	def test_cycle_ends(self):
		first, second = message_id(), message_id()
		a = communication(first)
		b = communication(second, a.name)
		frappe.db.set_value("Communication", a.name, "in_reply_to", b.name)
		self.assertEqual(reply(second)["References"], header([first, second]))

	def test_error_sends_without_references(self):
		with patch.object(references, "parent_communication", side_effect=Exception("boom")):
			mail = reply(message_id())
		self.assertIsNone(mail["References"])
		self.assertIsNotNone(mail["In-Reply-To"])

	def test_failing_log_still_builds_mail(self):
		with (
			patch.object(references, "parent_communication", side_effect=Exception("boom")),
			patch.object(frappe, "log_error", side_effect=Exception("db down")),
		):
			mail = reply(message_id())
		self.assertIsNone(mail["References"])
		self.assertIsNotNone(mail["In-Reply-To"])

	def test_invalid_ids_are_skipped(self):
		root, parent = message_id(), message_id()
		bad = [f"in ner{message_id()}", f"a>b{message_id()}", f"\u00fc{message_id()}"]
		name = communication(root).name
		for mid in bad:
			name = communication(mid, name).name
		communication(parent, name)
		self.assertEqual(reply(parent)["References"], header([root, parent]))

	def test_invalid_in_reply_to_adds_nothing(self):
		self.assertIsNone(reply("in ner@example.com")["References"])

	def test_last_of_several_in_reply_to_ids_is_parent(self):
		ids = chain(2)
		other = message_id()
		self.assertEqual(reply(f"<{other}> <{ids[-1]}>", bracket=False)["References"], header(ids))
