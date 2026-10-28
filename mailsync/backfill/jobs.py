import time

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from mailsync.backfill import importer, mailbox, review, scan

QUEUE = "long"
TIMEOUT = 1500
BUDGET = 1200
RUNNING = {"scan": "Scanning", "import": "Importing"}
COUNTERS = {
	"Pending": "pending",
	"Present": "present",
	"Imported": "imported",
	"Filtered": "filtered",
	"Too Large": "too_large",
	"Failed": "failed",
}


def enqueue(name, step):
	frappe.enqueue(
		"mailsync.backfill.jobs.work",
		queue=QUEUE,
		timeout=TIMEOUT,
		enqueue_after_commit=True,
		name=name,
		step=step,
	)


def start(name, step):
	doc = frappe.get_doc("Mail Import", name)
	doc.check_permission("write")
	if doc.status in RUNNING.values() and not stale(doc):
		frappe.throw(_("This import is already running"))
	if step == "scan":
		for row in doc.folders:
			row.db_set("scan_done", 0)
		if not doc.folders:
			frappe.throw(_("Choose at least one folder"))
	doc.db_set({"status": RUNNING[step], "error": None})
	enqueue(name, step)


def stale(doc):
	return get_datetime(doc.modified) < add_to_date(now_datetime(), seconds=-TIMEOUT)


def work(name, step):
	doc = frappe.get_doc("Mail Import", name)
	if doc.status != RUNNING[step]:
		return
	deadline = time.monotonic() + BUDGET
	try:
		server = mailbox.login(frappe.get_doc("Email Account", doc.email_account))
	except Exception as error:
		fail(doc, error)
		return
	try:
		finished = run(doc, step, server.imap, deadline)
	except Exception as error:
		frappe.db.rollback()
		fail(doc, error)
		return
	finally:
		logout(server)
	update_counters(doc)
	if finished:
		doc.db_set("status", "Done" if step == "import" and not doc.pending else "Review")
	else:
		enqueue(name, step)
	frappe.db.commit()
	notify(name)


def run(doc, step, imap, deadline):
	if step == "scan":
		finished = scan.scan(doc, imap, deadline)
	else:
		finished = importer.run(doc, imap, deadline)
	if finished:
		review.refresh(doc)
	return finished


def logout(server):
	try:
		server.logout()
	except Exception:
		pass


def fail(doc, error):
	frappe.log_error(title=_("Mail import failed: {0}").format(doc.name))
	doc.db_set({"status": "Failed", "error": str(error)[:1000]})
	update_counters(doc)
	frappe.db.commit()
	notify(doc.name)


def update_counters(doc):
	counts = dict(
		frappe.get_all(
			"Mail Import Message",
			filters={"mail_import": doc.name},
			fields=["state", {"COUNT": "*", "as": "count"}],
			group_by="state",
			as_list=True,
		)
	)
	values = {field: counts.get(state, 0) for state, field in COUNTERS.items()}
	values["total"] = sum(counts.values())
	doc.db_set(values)


def notify(name):
	frappe.publish_realtime(
		"mailsync_import", {"name": name}, doctype="Mail Import", docname=name, after_commit=True
	)
