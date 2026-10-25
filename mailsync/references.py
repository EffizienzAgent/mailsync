import frappe
from frappe import _

MAX_IDS = 20
MAX_DEPTH = 50
MAX_LINE = 998


def set_references(mail):
	"""Frappe sets only In-Reply-To on replies. Add References (RFC 5322 3.6.4) so threads keep their root."""
	try:
		if mail.msg_root["References"]:
			return
		parent = bare(mail.msg_root["In-Reply-To"])
		if parent and (value := header(references(parent))):
			mail.set_header("References", value)
	except Exception:
		frappe.log_error(title=_("References header failed"))


def references(parent_id):
	ids = [parent_id]
	name = parent_communication(parent_id)
	seen = set()
	while name and name not in seen and len(seen) < MAX_DEPTH:
		seen.add(name)
		row = frappe.db.get_value("Communication", name, ["message_id", "in_reply_to"], as_dict=True)
		if not row:
			break
		if (mid := bare(row.message_id)) and mid not in ids:
			ids.append(mid)
		name = row.in_reply_to
	ids.reverse()
	return cap(ids)


def parent_communication(message_id):
	names = frappe.get_all(
		"Communication",
		filters={"message_id": ("in", [message_id, f"<{message_id}>"])},
		pluck="name",
		order_by="creation desc",
		limit=1,
	)
	return names[0] if names else None


def cap(ids):
	if len(ids) > MAX_IDS:
		ids = [ids[0], *ids[-(MAX_IDS - 1) :]]
	while len(ids) > 2 and too_long(ids):
		del ids[1]
	if too_long(ids):
		ids = ids[-1:]
	return [] if too_long(ids) else ids


def header(ids):
	return " ".join(f"<{mid}>" for mid in ids)


def too_long(ids):
	"""Frappe writes headers without folding, so the whole line must fit."""
	return len(f"References: {header(ids)}") > MAX_LINE


def bare(message_id):
	return (message_id or "").strip().strip("<>").strip()
