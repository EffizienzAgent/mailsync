import frappe
from frappe import _
from frappe.utils import cstr

CACHE_KEY = "mailsync_own_addresses"


def normalize(address):
	return cstr(address).strip().lower()


def clear():
	setattr(frappe.local, CACHE_KEY, None)


def own_addresses():
	cached = getattr(frappe.local, CACHE_KEY, None)
	if cached is None:
		accounts = frappe.get_all("Email Account", pluck="email_id")
		users = frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"}, pluck="email")
		cached = {normalize(a) for a in (*accounts, *users)} - {""}
		setattr(frappe.local, CACHE_KEY, cached)
	return cached


def is_own(address):
	address = normalize(address)
	if address in own_addresses():
		return True
	return any(frappe.get_attr(method)(address) for method in frappe.get_hooks("mailsync_own_address"))


def contact_for(address):
	return frappe.db.get_value(
		"Contact Email", {"parenttype": "Contact", "email_id": normalize(address)}, "parent"
	)


def is_ignored(address):
	return bool(frappe.db.exists("Mail Ignored Address", normalize(address)))


def suggestion(address):
	found = {}
	for method in frappe.get_hooks("mailsync_address_suggestion"):
		try:
			found.update(frappe.get_attr(method)(normalize(address)) or {})
		except Exception:
			frappe.log_error(title=_("Address suggestion failed: {0}").format(method))
	return found


def link_doctype():
	doctypes = frappe.get_hooks("mailsync_contact_link_doctype")
	return doctypes[-1] if doctypes else None
