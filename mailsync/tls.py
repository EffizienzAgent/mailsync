import imaplib
import ssl

import frappe

INSECURE_FLAG = "mailsync_allow_self_signed_starttls"
_starttls = imaplib.IMAP4.starttls


def verified_starttls(self, ssl_context=None):
	return _starttls(self, ssl_context or context())


def context():
	if (getattr(frappe.local, "conf", None) or {}).get(INSECURE_FLAG):
		return ssl._create_unverified_context()
	return ssl.create_default_context()


def apply(*args, **kwargs):
	"""Python's IMAP4.starttls skips certificate checks without a context, and Frappe passes none."""
	imaplib.IMAP4.starttls = verified_starttls
