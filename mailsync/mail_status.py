import imaplib
import re
from email.parser import BytesHeaderParser

import frappe
from frappe import _
from frappe.utils import add_days, today

WINDOW_DAYS = 14
OPEN_STATUSES = ["Open", "Linked"]
SENT_NAMES = ["Sent", "INBOX.Sent", "Sent Messages", "Sent Items", "Gesendet", "INBOX.Gesendet"]
CHUNK = 50
INBOX = "INBOX"
MESSAGE_ID = re.compile(r"<([^<>\s]+)>")
SAFE_ID = re.compile(r"[\x21-\x7e]+")
UNSAFE_ID_CHARS = set('"\\<>')
LIST_LINE = re.compile(rb'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$')
LIST_LITERAL = re.compile(rb'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) \{\d+\}$')


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
	messages = [m for m in messages if ids[m.name]]
	if not messages:
		return {}
	replied, reply_unknown = answered(imap, sent_folder(imap, account), {ids[m.name] for m in messages})
	present, presence_unknown = set(), set()
	folders = {}
	for m in messages:
		folders.setdefault(m.imap_folder or INBOX, set()).add(ids[m.name])
	for folder, wanted in folders.items():
		hits, failed = found(imap, folder, wanted, ["Message-ID"])
		present |= {(folder, i) for i in hits}
		presence_unknown |= {(folder, i) for i in failed}
	changes = {}
	for m in messages:
		key = (m.imap_folder or INBOX, ids[m.name])
		if ids[m.name] in replied:
			changes[m.name] = "Replied"
		elif ids[m.name] in reply_unknown or key in presence_unknown:
			continue
		elif key not in present:
			changes[m.name] = "Closed"
	return changes


def answered(imap, folder, ids):
	if not folder:
		return set(), set()
	return found(imap, folder, ids, ["In-Reply-To", "References"])


def found(imap, folder, ids, headers):
	"""Return the ids found and the ids whose search failed, so callers leave those unchanged."""
	check(imap.select(quote(folder), readonly=True))
	hits, failed = set(), set()
	ids = sorted(ids)
	for start in range(0, len(ids), CHUNK):
		chunk = ids[start : start + CHUNK]
		try:
			hits |= search_chunk(imap, chunk, headers)
		except (ImapError, imaplib.IMAP4.error) as error:
			if isinstance(error, imaplib.IMAP4.abort):
				raise
			failed |= set(chunk)
			frappe.log_error(title=_("Mail status search failed: {0}").format(folder))
	return hits, failed


def search_chunk(imap, chunk, headers):
	criteria = any_of([f"HEADER {h} {quote(f'<{i}>')}" for i in chunk for h in headers])
	numbers = check(imap.search(None, criteria))[0].split()
	if not numbers:
		return set()
	return header_ids(imap, numbers, headers) & set(chunk)


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
	folders = dict(filter(None, (list_entry(part) for part in check(imap.list()))))
	for name, flags in folders.items():
		if "\\Sent" in flags.split():
			return name
	for name in [account.sent_folder_name, *SENT_NAMES]:
		if name and name in folders:
			return name


def list_entry(part):
	"""Parse one LIST response, where a folder name may come as a literal: (b'(flags) "/" {5}', b'Sent')."""
	if isinstance(part, tuple) and len(part) == 2:
		match = LIST_LITERAL.match(part[0] if isinstance(part[0], bytes) else b"")
		name = part[1]
	else:
		match = LIST_LINE.match(part if isinstance(part, bytes) else b"")
		name = match and match["name"].strip(b'"')
	if not match or not isinstance(name, bytes):
		return None
	return name.decode(errors="replace"), match["flags"].decode(errors="replace")


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
	"""Return the bare Message-ID, or None if it is not safe to put into an IMAP search."""
	value = (message_id or "").strip().removeprefix("<").removesuffix(">")
	if SAFE_ID.fullmatch(value) and not UNSAFE_ID_CHARS & set(value):
		return value
	return None


def quote(value):
	return '"' + value.replace("\\", "").replace('"', "") + '"'
