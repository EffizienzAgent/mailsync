import re

import frappe
from frappe import _

MAX_IDS = 20
MAX_DEPTH = MAX_IDS * 2
MAX_LINE = 998
VALID_ID = re.compile(r"[\x21-\x3b\x3d\x3f-\x7e]+")
BRACKETED = re.compile(r"<([^<>]*)>")


def set_references(mail):
	"""Frappe sets only In-Reply-To on replies. Add References (RFC 5322 3.6.4) so threads keep their root."""
	try:
		if mail.msg_root["References"]:
			return
		parent = last_id(mail.msg_root["In-Reply-To"])
		if parent and (value := header(references(parent))):
			mail.set_header("References", value)
	except Exception:
		log_failure()


def log_failure():
	try:
		frappe.log_error(title=_("References header failed"))
	except Exception:
		pass


def last_id(value):
	value = str(value or "")
	candidates = BRACKETED.findall(value) or [value]
	return next((mid for mid in map(bare, reversed(candidates)) if mid), "")


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
	"""Message.as_string() defaults to maxheaderlen=0, so Frappe's headers are not folded and must fit one line."""
	return len(f"References: {header(ids)}") > MAX_LINE


def bare(message_id):
	mid = (message_id or "").strip().strip("<>").strip()
	return mid if VALID_ID.fullmatch(mid) else ""
