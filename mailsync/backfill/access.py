import frappe

CHILDREN = ("Mail Import Message", "Mail Import Address")


def is_admin(user=None):
	return "System Manager" in frappe.get_roles(user or frappe.session.user)


def can_use_account(email_account, user=None):
	user = user or frappe.session.user
	return is_admin(user) or bool(
		frappe.db.exists("User Email", {"parenttype": "User", "parent": user, "email_account": email_account})
	)


def has_permission(doc, ptype=None, user=None, debug=False):
	if doc.doctype in CHILDREN:
		account = frappe.db.get_value("Mail Import", doc.mail_import, "email_account")
	else:
		account = doc.email_account
	return can_use_account(account, user)


def accounts(user):
	return frappe.get_all(
		"User Email", filters={"parenttype": "User", "parent": user}, pluck="email_account", distinct=True
	)


def query_conditions(user=None, doctype=None):
	user = user or frappe.session.user
	if is_admin(user):
		return ""
	allowed = ", ".join(frappe.db.escape(account) for account in accounts(user)) or "''"
	if doctype in CHILDREN:
		table = f"`tab{doctype}`"
		return (
			f"{table}.mail_import in (select name from `tabMail Import` where email_account in ({allowed}))"
		)
	return f"`tabMail Import`.email_account in ({allowed})"


def message_conditions(user=None):
	return query_conditions(user, "Mail Import Message")


def address_conditions(user=None):
	return query_conditions(user, "Mail Import Address")
