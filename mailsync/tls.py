import imaplib
import smtplib
import ssl

import frappe

INSECURE_FLAG = "mailsync_allow_self_signed_starttls"
SMTP_INSECURE_FLAG = "mailsync_allow_self_signed_smtp"
_starttls = imaplib.IMAP4.starttls
_smtp_starttls = smtplib.SMTP.starttls
_smtp_ssl_init = smtplib.SMTP_SSL.__init__


def verified_starttls(self, ssl_context=None):
	return _starttls(self, ssl_context or context())


def verified_smtp_starttls(self, *, context=None):
	return _smtp_starttls(self, context=context or smtp_context())


def verified_smtp_ssl_init(self, *args, context=None, **kwargs):
	_smtp_ssl_init(self, *args, context=context or smtp_context(), **kwargs)


def context(flag=INSECURE_FLAG):
	if (getattr(frappe.local, "conf", None) or {}).get(flag):
		return ssl._create_unverified_context()
	return ssl.create_default_context()


def smtp_context():
	return context(SMTP_INSECURE_FLAG)


def apply(*args, **kwargs):
	"""Python's imaplib and smtplib skip certificate checks without a context, and Frappe passes none."""
	imaplib.IMAP4.starttls = verified_starttls
	smtplib.SMTP.starttls = verified_smtp_starttls
	smtplib.SMTP_SSL.__init__ = verified_smtp_ssl_init
