import imaplib
import os
import ssl
import unittest
import uuid
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from mailsync import hooks, mail_sync, tls
from mailsync.tests.factories import unique

HOST = os.environ.get("MAILSYNC_TEST_STARTTLS_HOST")
PORT = os.environ.get("MAILSYNC_TEST_STARTTLS_PORT", "31143")


class FakeConnection:
	host = "imap.example.test"


class TestStarttlsContext(IntegrationTestCase):
	def starttls_context(self, **kwargs):
		tls.apply()
		with patch.object(tls, "_starttls", side_effect=lambda imap, ctx: ctx) as original:
			imaplib.IMAP4.starttls(FakeConnection(), **kwargs)
		return original.call_args.args[1]

	def test_starttls_verifies_certificate_and_hostname(self):
		context = self.starttls_context()
		self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
		self.assertTrue(context.check_hostname)

	def test_opt_out_allows_self_signed(self):
		with patch.dict(frappe.local.conf, {tls.INSECURE_FLAG: 1}):
			context = self.starttls_context()
		self.assertEqual(context.verify_mode, ssl.CERT_NONE)

	def test_explicit_context_is_kept(self):
		mine = ssl.create_default_context()
		self.assertIs(self.starttls_context(ssl_context=mine), mine)

	def test_applied_in_requests_and_jobs(self):
		self.assertIn("mailsync.tls.apply", hooks.before_request)
		self.assertIn("mailsync.tls.apply", hooks.before_job)


@unittest.skipUnless(
	HOST, "set MAILSYNC_TEST_STARTTLS_HOST to a STARTTLS server with a self-signed certificate"
)
class TestStarttlsServer(IntegrationTestCase):
	def setUp(self):
		frappe.flags.mute_emails = True
		self.addCleanup(setattr, frappe.flags, "mute_emails", False)
		tls.apply()
		self.account = frappe.get_doc(
			{
				"doctype": "Email Account",
				"email_account_name": unique("Starttls"),
				"email_id": f"{uuid.uuid4().hex[:10]}@example.test",
				"password": "secret",
				"email_server": HOST,
				"incoming_port": PORT,
				"use_imap": 1,
				"use_ssl": 0,
				"use_starttls": 1,
				"enable_incoming": 1,
				"enable_outgoing": 0,
				"imap_folder": [{"folder_name": "INBOX"}],
			}
		).insert(ignore_permissions=True)

	def connect(self):
		with patch.object(imaplib.IMAP4, "login", autospec=True, return_value=("OK", [b""])) as login:
			try:
				self.account.get_incoming_server(in_receive=True)
			except Exception as error:
				self.error = error
		return login.called

	def test_self_signed_certificate_is_rejected(self):
		self.assertFalse(self.connect())
		self.assertIn(ssl.SSLCertVerificationError, causes(self.error))

	def test_stock_pull_is_verified_too(self):
		with patch.object(imaplib.IMAP4, "login", autospec=True) as login:
			try:
				frappe.get_attr(mail_sync.STOCK_PULL)(self.account.name)
			except Exception:
				pass
		login.assert_not_called()

	def test_opt_out_connects(self):
		with patch.dict(frappe.local.conf, {tls.INSECURE_FLAG: 1}):
			self.assertTrue(self.connect())


def causes(error):
	found = []
	while error:
		found.append(type(error))
		error = error.__cause__ or error.__context__
	return found
