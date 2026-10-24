import os
import smtplib
import ssl
import unittest
from unittest.mock import patch

import frappe
from frappe.email.smtp import SMTPServer
from frappe.tests import IntegrationTestCase

from mailsync import tls

HOST = os.environ.get("MAILSYNC_TEST_SMTP_HOST")
STARTTLS_PORT = os.environ.get("MAILSYNC_TEST_SMTP_STARTTLS_PORT", "31587")
SSL_PORT = os.environ.get("MAILSYNC_TEST_SMTP_SSL_PORT", "31465")
CA_HOST = os.environ.get("MAILSYNC_TEST_CA_SMTP_HOST")


class FakeSMTP:
	_host = "smtp.example.test"


class TestSmtpContext(IntegrationTestCase):
	def setUp(self):
		tls.apply()

	def starttls_context(self, **kwargs):
		with patch.object(tls, "_smtp_starttls", side_effect=lambda smtp, context: context) as original:
			smtplib.SMTP.starttls(FakeSMTP(), **kwargs)
		return original.call_args.kwargs["context"]

	def ssl_context(self, **kwargs):
		with patch.object(tls, "_smtp_ssl_init") as original:
			smtplib.SMTP_SSL("smtp.example.test", 465, **kwargs)
		return original.call_args.kwargs["context"]

	def test_starttls_and_ssl_verify_certificate_and_hostname(self):
		for context in (self.starttls_context(), self.ssl_context()):
			self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
			self.assertTrue(context.check_hostname)

	def test_smtp_opt_out_is_its_own_flag(self):
		with patch.dict(frappe.local.conf, {tls.INSECURE_FLAG: 1}):
			self.assertEqual(self.starttls_context().verify_mode, ssl.CERT_REQUIRED)
		with patch.dict(frappe.local.conf, {tls.SMTP_INSECURE_FLAG: 1}):
			self.assertEqual(self.starttls_context().verify_mode, ssl.CERT_NONE)
			self.assertEqual(self.ssl_context().verify_mode, ssl.CERT_NONE)

	def test_explicit_context_is_kept(self):
		mine = ssl.create_default_context()
		self.assertIs(self.starttls_context(context=mine), mine)
		self.assertIs(self.ssl_context(context=mine), mine)


@unittest.skipUnless(HOST, "set MAILSYNC_TEST_SMTP_HOST to an SMTP server with a self-signed certificate")
class TestSmtpServer(IntegrationTestCase):
	def setUp(self):
		tls.apply()

	def servers(self):
		return [
			SMTPServer(server=HOST, port=STARTTLS_PORT, use_tls=1),
			SMTPServer(server=HOST, port=SSL_PORT, use_ssl=1),
		]

	def test_self_signed_certificate_is_rejected(self):
		for server in self.servers():
			with self.subTest(port=server.port):
				with self.assertRaisesRegex(Exception, "CERTIFICATE_VERIFY_FAILED"):
					_ = server.session

	def test_opt_out_connects(self):
		with patch.dict(frappe.local.conf, {tls.SMTP_INSECURE_FLAG: 1}):
			for server in self.servers():
				with self.subTest(port=server.port):
					server.session.quit()


@unittest.skipUnless(CA_HOST, "set MAILSYNC_TEST_CA_SMTP_HOST to a public SMTP host with a CA-signed certificate")
class TestCaSignedServer(IntegrationTestCase):
	def test_verified_connection_works(self):
		tls.apply()
		with smtplib.SMTP_SSL(CA_HOST, 465, timeout=10) as smtp:
			self.assertEqual(smtp.ehlo()[0], 250)
		with smtplib.SMTP(CA_HOST, 587, timeout=10) as smtp:
			smtp.ehlo()
			smtp.starttls()
			self.assertEqual(smtp.ehlo()[0], 250)
