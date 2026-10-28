import frappe
from frappe import _

from mailsync import tls
from mailsync.mail_status import check, list_entry, quote
from mailsync.mail_sync import IMAP_TIMEOUT
from mailsync.sent_mail import STATUS_FIELD

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def login(account):
	tls.apply()
	frappe.conf.imap_timeout = frappe.conf.imap_timeout or IMAP_TIMEOUT
	server = account.get_incoming_server(in_receive=True)
	if not getattr(server, "imap", None):
		frappe.throw(_("Could not log in to {0}").format(account.name))
	return server


def folders(imap):
	entries = filter(None, (list_entry(part) for part in check(imap.list())))
	return [name for name, flags in entries if "\\noselect" not in flags.lower()]


def select(imap, folder):
	check(imap.select(quote(folder), readonly=True))


def uidvalidity(imap, folder):
	response = check(imap.status(quote(folder), "(UIDVALIDITY)"))[0]
	values = dict(STATUS_FIELD.findall(response if isinstance(response, bytes) else b""))
	if b"UIDVALIDITY" not in values:
		raise ValueError(f"UIDVALIDITY missing for {folder}")
	return int(values[b"UIDVALIDITY"])


def imap_date(value):
	value = frappe.utils.getdate(value)
	return f"{value.day:02d}-{MONTHS[value.month - 1]}-{value.year}"


def criteria(after_uid, from_date, to_date):
	parts = [f"UID {after_uid}:*"]
	if from_date:
		parts.append(f"SENTSINCE {imap_date(from_date)}")
	if to_date:
		parts.append(f"SENTBEFORE {imap_date(frappe.utils.add_days(to_date, 1))}")
	return " ".join(parts)


def search(imap, after_uid, from_date=None, to_date=None):
	data = check(imap.uid("search", None, criteria(after_uid, from_date, to_date)))
	return sorted(u for u in (int(x) for x in (data[0] or b"").split()) if u >= after_uid)
