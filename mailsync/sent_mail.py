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
STATUS_FIELD = re.compile(rb"(UIDVALIDITY|UIDNEXT) (\d+)")


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
	return communication.name if communication else None


def fetch_new(imap, account):
	folder = sent_folder(imap, account)
	if not folder:
		return None, []
	uidvalidity, uidnext = folder_status(imap, folder)
	state = load_state(account.name)
	if state.get("folder") != folder or state.get("uidvalidity") != uidvalidity:
		return (folder, uidvalidity, uidnext - 1), []
	check(imap.select(quote(folder), readonly=True))
	last = state["uid"]
	uids = sorted(int(u) for u in check(imap.uid("search", None, f"UID {last + 1}:*"))[0].split())
	uids = [u for u in uids if u > last][:BATCH]
	if not uids:
		return None, []
	mails = [SentMail(fetch_raw(imap, uid), account, str(uid), folder) for uid in uids]
	return (folder, uidvalidity, uids[-1]), mails


def folder_status(imap, folder):
	response = check(imap.status(quote(folder), "(UIDVALIDITY UIDNEXT)"))[0]
	values = {key.decode(): int(value) for key, value in STATUS_FIELD.findall(response)}
	return values["UIDVALIDITY"], values["UIDNEXT"]


def fetch_raw(imap, uid):
	data = check(imap.uid("fetch", str(uid), "(BODY.PEEK[])"))
	return next(part[1] for part in data if isinstance(part, tuple))


def load_state(account):
	value = frappe.db.get_default(STATE_KEY.format(account))
	return json.loads(value) if value else {}


def save_state(account, folder, uidvalidity, uid):
	value = json.dumps({"folder": folder, "uidvalidity": uidvalidity, "uid": uid})
	frappe.db.set_default(STATE_KEY.format(account), value)
