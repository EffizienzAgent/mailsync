import time
from email.utils import getaddresses

import frappe
from frappe.email.receive import Email, InboundMail

from mailsync import sent_mail
from mailsync.backfill import addresses, mailbox
from mailsync.mail_status import check
from mailsync.sent_mail import FETCH_SIZE, FETCH_UID

CHUNK = 200
HEADERS = "FROM TO CC MESSAGE-ID DATE SUBJECT"


def scan(doc, imap, deadline):
	for row in doc.folders:
		if not row.scan_done and not scan_folder(doc, row, imap, deadline):
			return False
	return True


def scan_folder(doc, row, imap, deadline):
	current = mailbox.uidvalidity(imap, row.folder)
	if row.uidvalidity != current:
		forget(doc.name, row.folder)
		row.uidvalidity, row.scanned_uid = current, 0
	mailbox.select(imap, row.folder)
	uids = mailbox.search(imap, row.scanned_uid + 1, doc.from_date, doc.to_date)
	for start in range(0, len(uids), CHUNK):
		if time.monotonic() > deadline and start:
			return False
		chunk = uids[start : start + CHUNK]
		for uid, size, headers in fetch_headers(imap, chunk):
			record(doc, row, uid, size, headers)
		row.scanned_uid = chunk[-1]
		row.db_update()
		frappe.db.commit()
	row.scan_done = 1
	row.db_update()
	frappe.db.commit()
	return True


def forget(mail_import, folder):
	frappe.db.delete(
		"Mail Import Message",
		{"mail_import": mail_import, "folder": folder, "state": ("!=", "Imported")},
	)


def fetch_headers(imap, uids):
	spec = f"(UID RFC822.SIZE BODY.PEEK[HEADER.FIELDS ({HEADERS})])"
	for part in check(imap.uid("fetch", ",".join(str(u) for u in uids), spec)):
		if isinstance(part, tuple) and isinstance(part[1], bytes):
			uid, size = FETCH_UID.search(part[0]), FETCH_SIZE.search(part[0])
			if uid:
				yield int(uid[1]), int(size[1]) if size else 0, part[1]


def record(doc, row, uid, size, headers):
	key = {"mail_import": doc.name, "folder": row.folder, "uidvalidity": row.uidvalidity, "uid": uid}
	if frappe.db.exists("Mail Import Message", key):
		return
	mail = Email(headers)
	sender = first_address(mail.mail.get("From"))
	frappe.get_doc(
		{
			"doctype": "Mail Import Message",
			**key,
			"size": size,
			"message_id": mail.message_id or None,
			"subject": mail.subject,
			"sender": (InboundMail.decode_email(mail.mail.get("From")) or "")[:140],
			"mail_date": mail.date,
			"outgoing": int(bool(sender) and addresses.is_own(sender)),
			"participants": "\n".join(f"{a} {n}".strip() for a, n in participants(mail.mail)),
			"state": state(mail.message_id, size),
		}
	).db_insert()


def state(message_id, size):
	if size > sent_mail.MAX_MAIL_BYTES:
		return "Too Large"
	if message_id and sent_mail.known(message_id):
		return "Present"
	return "Pending"


def named_addresses(*headers):
	found = {}
	for header in headers:
		for name, address in getaddresses([str(header or "")]):
			address = addresses.normalize(address)
			if "@" in address and address not in found:
				found[address] = (InboundMail.decode_email(name) or "").strip()
	return found


def first_address(header):
	return next(iter(named_addresses(header)), None)


def participants(mail):
	found = named_addresses(mail.get("From"), mail.get("To"), mail.get("Cc"))
	return [(address, name) for address, name in found.items() if not addresses.is_own(address)]


def participant_list(message):
	return [line.split(" ", 1)[0] for line in (message.participants or "").splitlines() if line]


def participant_names(message):
	return dict(
		(parts[0], parts[1] if len(parts) > 1 else "")
		for parts in (line.split(" ", 1) for line in (message.participants or "").splitlines() if line)
	)
