from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils.background_jobs import get_jobs

from mailsync import mail_status, sent_mail, tls

QUEUE = "default"
JOB_TIMEOUT = 600
IMAP_TIMEOUT = 60
SYNC_ACCOUNT = "mailsync.mail_sync.sync_account"
STOCK_PULL = "frappe.email.doctype.email_account.email_account.pull_from_email_account"


def sync_all():
	"""Every 2 minutes: one IMAP login per account for inbox, Sent folder and status.

	Uses Frappe's pull job name, so neither run overlaps per account.
	"""
	queued = get_jobs(site=frappe.local.site, key="job_name")[frappe.local.site]
	for account in accounts():
		job_name = f"pull_from_email_account|{account.name}"
		if job_name not in queued:
			method = SYNC_ACCOUNT if shared_login(account) else STOCK_PULL
			frappe.enqueue(
				method, queue=QUEUE, timeout=JOB_TIMEOUT, job_name=job_name, email_account=account.name
			)


def shared_login(account):
	return account.use_imap and account.service != "Frappe Mail"


def accounts():
	from frappe.integrations.doctype.connected_app.connected_app import has_token

	rows = frappe.get_all(
		"Email Account",
		filters={"enable_incoming": 1, "awaiting_password": 0},
		fields=[
			"name",
			"use_imap",
			"service",
			"auth_method",
			"backend_app_flow",
			"connected_app",
			"connected_user",
		],
	)
	return [
		row
		for row in rows
		if row.auth_method != "OAuth"
		or row.backend_app_flow
		or has_token(row.connected_app, row.connected_user)
	]


def sync_account(email_account):
	tls.apply()
	doc = frappe.get_doc("Email Account", email_account)
	frappe.conf.imap_timeout = frappe.conf.imap_timeout or IMAP_TIMEOUT
	try:
		server = doc.get_incoming_server(in_receive=True, email_sync_rule=doc.build_email_sync_rule())
	except Exception:
		frappe.log_error(title=_("Mail sync login failed: {0}").format(doc.name))
		return
	with shared(doc, server):
		step(doc.receive, _("Mail pull failed: {0}").format(doc.name))
		step(lambda: sent_mail.sync(doc, server.imap), _("Sent folder sync failed: {0}").format(doc.name))
		step(lambda: mail_status.sync(doc, server.imap), _("Mail status sync failed: {0}").format(doc.name))


@contextmanager
def shared(doc, server):
	logout = server.logout
	server.logout = lambda: None
	doc.get_incoming_server = lambda *args, **kwargs: server
	try:
		yield
	finally:
		try:
			logout()
		except Exception:
			pass


def step(run, title):
	try:
		run()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title=title)
	frappe.db.commit()
