import uuid
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.utils import add_days, now_datetime


def unique(prefix):
	return f"{prefix} {uuid.uuid4().hex[:12]}"


def make_account(**fields):
	return frappe.get_doc(
		{
			"doctype": "Email Account",
			"email_account_name": unique("Mailbox"),
			"email_id": f"{unique('box').replace(' ', '')}@example.test",
			"email_server": "imap.example.test",
			"enable_incoming": 1,
			"use_imap": 1,
			"awaiting_password": 1,
			"imap_folder": [{"folder_name": "INBOX"}],
			**fields,
		}
	).insert(ignore_permissions=True)


def make_mail(account, message_id, days_ago=1):
	return frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Received",
			"subject": message_id,
			"content": "Body",
			"sender": "customer@example.com",
			"email_account": account,
			"message_id": message_id,
			"communication_date": add_days(now_datetime(), -days_ago),
		}
	).insert(ignore_permissions=True)


@contextmanager
def hooks(name, methods):
	original = frappe.get_hooks

	def get_hooks(hook=None, *args, **kwargs):
		if hook == name:
			return list(methods)
		return original(hook, *args, **kwargs)

	with patch.object(frappe, "get_hooks", side_effect=get_hooks):
		yield
