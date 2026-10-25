import json
import re

import frappe
from frappe import _
from frappe.email.receive import InboundMail
from frappe.utils import parse_addr, split_emails
from frappe.utils.user import is_system_user

from mailsync.mail_status import check, quote, sent_folder

STATE_KEY = "mailsync_sent_folder:{}"
BATCH = 50
MAX_MAIL_BYTES = 25 * 1024 * 1024
MAX_BATCH_BYTES = 100 * 1024 * 1024
STATUS_FIELD = re.compile(rb"(UIDVALIDITY|UIDNEXT) (\d+)")
FETCH_UID = re.compile(rb"\bUID (\d+)")
FETCH_SIZE = re.compile(rb"\bRFC822\.SIZE (\d+)")


class SentMail(InboundMail):
	def __init__(self, content, email_account, uid, folder):
		super().__init__(content, email_account, uid, seen_status=1)
		self.folder = folder

	def process(self):
		if self.is_known():
			return None
		self.flags.is_new_communication = True
		return self._build_communication_doc()

	def is_known(self):
		if not self.message_id:
			return False
		return bool(
			self.message_id.endswith(f"@{frappe.local.site}")
			or frappe.db.exists("Communication", {"message_id": self.message_id})
			or frappe.db.exists(
				"Email Queue", {"message_id": ("in", [self.message_id, f"<{self.message_id}>"])}
			)
		)

	def existing_communication(self):
		if not self.message_id:
			return None
		name = frappe.db.get_value(
			"Communication", {"message_id": self.message_id, "sent_or_received": "Sent"}
		)
		return frappe.get_doc("Communication", name) if name else None

	def as_dict(self):
		data = super().as_dict()
		data["sent_or_received"] = "Sent"
		data["imap_folder"] = self.folder
		data["timeline_links"] = recipient_links(self, self.email_account.email_id)
		return data


def recipient_links(mail, own_address):
	methods = [frappe.get_attr(method) for method in frappe.get_hooks("mailsync_recipient_links")]
	links = []
	for address in addresses(mail.mail.get("To"), mail.mail.get("Cc")):
		if address == own_address.lower() or is_system_user(address):
			continue
		for method in methods:
			links += method(address) or []
	return links


def addresses(*headers):
	found = []
	for header in headers:
		for entry in split_emails(InboundMail.decode_email(header or "")):
			address = parse_addr(entry)[1].strip().lower()
			if address and address not in found:
				found.append(address)
	return found


def sync(account, imap):
	position, mails = fetch_new(imap, account)
	names = [name for name in (store(mail) for mail in mails) if name]
	if position:
		save_state(account.name, *position)
	return names


def store(mail):
	frappe.db.savepoint("sent_mail")
	try:
		communication = mail.process()
	except Exception:
		frappe.db.rollback(save_point="sent_mail")
		frappe.log_error(title=_("Sent mail import failed: {0}").format(mail.message_id))
		return None
	if communication:
		mail_read(mail, communication)
		return communication.name
	if frappe.get_hooks("mailsync_mail_read") and (existing := mail.existing_communication()):
		mail_read(mail, existing)
	return None


def mail_read(mail, communication):
	for method in frappe.get_hooks("mailsync_mail_read"):
		frappe.db.savepoint("mail_read")
		try:
			frappe.get_attr(method)(
				communication=communication,
				raw=mail.raw_message,
				account=mail.email_account.name,
				folder=mail.folder,
				sent_or_received="Sent",
			)
		except Exception:
			undo_hook(method)
			frappe.log_error(title=_("Mail read hook failed: {0}").format(method))


def undo_hook(method):
	try:
		frappe.db.rollback(save_point="mail_read")
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title=_("Mail read hook rollback failed: {0}").format(method))


def fetch_new(imap, account):
	folder = sent_folder(imap, account)
	if not folder:
		return None, []
	status = folder_status(imap, folder)
	if not status:
		frappe.log_error(title=_("Sent folder status missing: {0}").format(account.name))
		return None, []
	uidvalidity, uidnext = status
	state = load_state(account.name)
	if state.get("folder") != folder or state.get("uidvalidity") != uidvalidity:
		return (folder, uidvalidity, uidnext - 1), []
	check(imap.select(quote(folder), readonly=True))
	last = state["uid"]
	uids = sorted(int(u) for u in check(imap.uid("search", None, f"UID {last + 1}:*"))[0].split())
	uids = [u for u in uids if u > last][:BATCH]
	if not uids:
		return None, []
	mails, done = [], last
	sizes = mail_sizes(imap, uids)
	total = 0
	for uid in uids:
		size = sizes.get(uid)
		if size is None or size > MAX_MAIL_BYTES:
			frappe.log_error(title=_("Sent mail skipped: {0} UID {1}").format(account.name, uid))
			done = uid
			continue
		if total and total + size > MAX_BATCH_BYTES:
			break
		raw = fetch_raw(imap, uid)
		if raw is None or len(raw) > MAX_MAIL_BYTES:
			frappe.log_error(title=_("Sent mail skipped: {0} UID {1}").format(account.name, uid))
		else:
			mails.append(SentMail(raw, account, str(uid), folder))
		total += size
		done = uid
	return (folder, uidvalidity, done), mails


def folder_status(imap, folder):
	response = check(imap.status(quote(folder), "(UIDVALIDITY UIDNEXT)"))[0]
	if not isinstance(response, bytes):
		return None
	values = {key.decode(): int(value) for key, value in STATUS_FIELD.findall(response)}
	if "UIDVALIDITY" not in values or "UIDNEXT" not in values:
		return None
	return values["UIDVALIDITY"], values["UIDNEXT"]


def mail_sizes(imap, uids):
	data = check(imap.uid("fetch", ",".join(str(u) for u in uids), "(RFC822.SIZE)"))
	sizes = {}
	for part in data:
		line = part[0] if isinstance(part, tuple) else part
		if not isinstance(line, bytes):
			continue
		uid, size = FETCH_UID.search(line), FETCH_SIZE.search(line)
		if uid and size:
			sizes[int(uid[1])] = int(size[1])
	return sizes


def fetch_raw(imap, uid):
	data = check(imap.uid("fetch", str(uid), "(BODY.PEEK[])"))
	return next((part[1] for part in data if isinstance(part, tuple) and isinstance(part[1], bytes)), None)


def load_state(account):
	value = frappe.db.get_default(STATE_KEY.format(account))
	return json.loads(value) if value else {}


def save_state(account, folder, uidvalidity, uid):
	value = json.dumps({"folder": folder, "uidvalidity": uidvalidity, "uid": uid})
	frappe.db.set_default(STATE_KEY.format(account), value)
