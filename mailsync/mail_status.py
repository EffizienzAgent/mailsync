import re
from email.parser import BytesHeaderParser

import frappe
from frappe.utils import add_days, today

WINDOW_DAYS = 14
OPEN_STATUSES = ["Open", "Linked"]
SENT_NAMES = ["Sent", "INBOX.Sent", "Sent Messages", "Sent Items", "Gesendet", "INBOX.Gesendet"]
CHUNK = 50
INBOX = "INBOX"
MESSAGE_ID = re.compile(r"<([^<>\s]+)>")


class ImapError(Exception):
	pass


def candidates(account):
	return frappe.get_all(
		"Communication",
		filters={
			"email_account": account,
			"communication_medium": "Email",
			"sent_or_received": "Received",
			"status": ("in", OPEN_STATUSES),
			"message_id": ("is", "set"),
			"communication_date": (">=", add_days(today(), -WINDOW_DAYS)),
		},
		fields=["name", "message_id", "imap_folder"],
	)


def sync(account, imap):
	messages = candidates(account.name)
	if not messages:
		return {}
	changes = statuses(imap, account, messages)
	apply(changes)
	return changes


def apply(changes):
	for name, status in changes.items():
		frappe.db.set_value(
			"Communication",
			{"name": name, "status": ("in", OPEN_STATUSES)},
			"status",
			status,
			update_modified=False,
		)
	if changes:
		for method in frappe.get_hooks("mailsync_status_changed"):
			frappe.get_attr(method)(changes)


def statuses(imap, account, messages):
	ids = {m.name: clean(m.message_id) for m in messages}
	replied = answered(imap, sent_folder(imap, account), set(ids.values()))
	present = set()
	folders = {}
	for m in messages:
		folders.setdefault(m.imap_folder or INBOX, set()).add(ids[m.name])
	for folder, wanted in folders.items():
		present |= {(folder, i) for i in found(imap, folder, wanted, ["Message-ID"])}
	changes = {}
	for m in messages:
		if ids[m.name] in replied:
			changes[m.name] = "Replied"
		elif (m.imap_folder or INBOX, ids[m.name]) not in present:
			changes[m.name] = "Closed"
	return changes


def answered(imap, folder, ids):
	if not folder:
		return set()
	return found(imap, folder, ids, ["In-Reply-To", "References"])


def found(imap, folder, ids, headers):
	check(imap.select(quote(folder), readonly=True))
	hits = set()
	ids = sorted(ids)
	for start in range(0, len(ids), CHUNK):
		chunk = ids[start : start + CHUNK]
		criteria = any_of([f"HEADER {h} {quote(f'<{i}>')}" for i in chunk for h in headers])
		numbers = check(imap.search(None, criteria))[0].split()
		if numbers:
			hits |= header_ids(imap, numbers, headers) & set(chunk)
	return hits


def header_ids(imap, numbers, headers):
	fields = " ".join(h.upper() for h in headers)
	data = check(imap.fetch(b",".join(numbers).decode(), f"(BODY.PEEK[HEADER.FIELDS ({fields})])"))
	ids = set()
	for part in data:
		if isinstance(part, tuple):
			parsed = BytesHeaderParser().parsebytes(part[1])
			for header in headers:
				ids |= set(MESSAGE_ID.findall(" ".join(parsed.get_all(header) or [])))
	return ids


def sent_folder(imap, account):
	folders = {}
	for line in check(imap.list()):
		match = re.match(rb'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$', line or b"")
		if match:
			folders[match["name"].decode().strip('"')] = match["flags"].decode()
	for name, flags in folders.items():
		if "\\Sent" in flags.split():
			return name
	for name in [account.sent_folder_name, *SENT_NAMES]:
		if name and name in folders:
			return name


def any_of(criteria):
	expression = criteria[-1]
	for criterion in reversed(criteria[:-1]):
		expression = f"OR {criterion} {expression}"
	return f"({expression})"


def check(response):
	status, data = response
	if status != "OK":
		raise ImapError(data)
	return data


def clean(message_id):
	return message_id.strip().strip("<>")


def quote(value):
	return '"' + value.replace("\\", "").replace('"', "") + '"'
