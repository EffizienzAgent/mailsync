import frappe
from frappe import _

from mailsync.backfill import addresses
from mailsync.backfill.scan import participant_names

SUBJECTS = 3


def refresh(doc):
	found = collect(doc.name)
	rows = {
		r.email_id: r
		for r in frappe.get_all(
			"Mail Import Address", filters={"mail_import": doc.name}, fields=["name", "email_id", "decision"]
		)
	}
	for email, row in rows.items():
		if row.decision == "Open" and (email not in found or resolved(email)):
			frappe.delete_doc("Mail Import Address", row.name, ignore_permissions=True, force=True)
		elif email in found:
			frappe.db.set_value("Mail Import Address", row.name, summary(found[email]), update_modified=False)
	for email, entry in found.items():
		if email not in rows and not resolved(email):
			try:
				add(doc.name, email, entry)
			except Exception:
				frappe.log_error(title=_("Address review failed: {0}").format(email))


def collect(mail_import):
	found = {}
	messages = frappe.get_all(
		"Mail Import Message",
		filters={"mail_import": mail_import, "state": "Pending"},
		fields=["participants", "subject"],
		order_by="mail_date asc, uid asc",
	)
	for message in messages:
		for email, name in participant_names(message).items():
			entry = found.setdefault(email, {"name": "", "count": 0, "subjects": []})
			entry["count"] += 1
			entry["name"] = entry["name"] or name
			if len(entry["subjects"]) < SUBJECTS and message.subject not in entry["subjects"]:
				entry["subjects"].append(message.subject)
	return found


def resolved(email):
	return bool(addresses.contact_for(email) or addresses.is_ignored(email))


def summary(entry):
	return {"mail_count": entry["count"], "subjects": "\n".join(filter(None, entry["subjects"]))}


def add(mail_import, email, entry):
	first_name, last_name = split_name(entry["name"], email)
	suggestion = addresses.suggestion(email)
	link_doctype = addresses.link_doctype()
	frappe.get_doc(
		{
			"doctype": "Mail Import Address",
			"mail_import": mail_import,
			"email_id": email,
			"full_name": entry["name"][:140],
			"first_name": first_name,
			"last_name": last_name,
			"suggested_contact": suggestion.get("contact"),
			"contact": suggestion.get("contact"),
			"link_doctype": link_doctype,
			"link_name": suggestion.get("link_name") if link_doctype else None,
			**summary(entry),
		}
	).insert(ignore_permissions=True)


def split_name(name, email):
	name = (name or "").strip().strip("'\"")
	if "," in name:
		last, first = (part.strip() for part in name.split(",", 1))
		return first[:140], last[:140]
	if " " in name:
		first, last = name.rsplit(" ", 1)
		return first[:140], last[:140]
	return (name or frappe.unscrub(email.split("@")[0]))[:140], ""


def decide(email, decision, contact=None):
	frappe.db.set_value(
		"Mail Import Address",
		{"email_id": email, "decision": "Open"},
		{"decision": decision, "contact": contact},
	)


@frappe.whitelist(methods=["POST"])
def ignore_many(names):
	for name in frappe.parse_json(names) if isinstance(names, str) else names:
		doc = frappe.get_doc("Mail Import Address", name)
		doc.check_permission("write")
		doc.ignore()


def ignore(email):
	email = addresses.normalize(email)
	if not addresses.is_ignored(email):
		frappe.get_doc({"doctype": "Mail Ignored Address", "email_id": email}).insert()
	decide(email, "Ignored")


def create_contact(row):
	contact = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": row.first_name or row.email_id.split("@")[0],
			"last_name": row.last_name,
		}
	)
	contact.add_email(row.email_id, is_primary=True)
	if row.link_doctype and row.link_name:
		contact.append("links", {"link_doctype": row.link_doctype, "link_name": row.link_name})
	contact.insert()
	decide(row.email_id, "Contact", contact.name)
	return contact.name


def add_to_contact(email, contact):
	if not contact:
		frappe.throw(_("Choose a contact"))
	doc = frappe.get_doc("Contact", contact)
	doc.check_permission("write")
	if not any(addresses.normalize(e.email_id) == email for e in doc.email_ids):
		doc.add_email(email, is_primary=not doc.email_ids)
		doc.save()
	decide(email, "Contact", contact)
