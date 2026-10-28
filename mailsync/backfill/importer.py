import time

import frappe
from frappe import _
from frappe.email.receive import InboundMail

from mailsync import sent_mail
from mailsync.backfill import addresses, mailbox
from mailsync.backfill.scan import participant_list


class BackfillMail(InboundMail):
	def __init__(self, content, email_account, row):
		super().__init__(content, email_account, uid=str(row.uid), seen_status=1)
		self.row = row
		self.folder = row.folder

	def as_dict(self):
		data = super().as_dict()
		data["sent_or_received"] = self.direction
		data["imap_folder"] = self.folder
		data["timeline_links"] = links(participant_list(self.row))
		data["unread_notification_sent"] = 1
		data["email_account"] = None
		return data

	@property
	def direction(self):
		return "Sent" if self.row.outgoing else "Received"

	def create(self):
		self.flags.is_new_communication = True
		frappe.flags.mailsync_import = True
		try:
			communication = self._build_communication_doc()
		finally:
			frappe.flags.mailsync_import = False
		communication.db_set(
			{"email_account": self.email_account.name, "status": "Closed", "seen": 1}, update_modified=False
		)
		return communication


def links(participants):
	methods = [frappe.get_attr(method) for method in frappe.get_hooks("mailsync_recipient_links")]
	found = []
	for address in participants:
		for method in methods:
			found += method(address) or []
	return found


def decide(row):
	participants = participant_list(row)
	if any(addresses.contact_for(address) for address in participants):
		return "import"
	if all(addresses.is_ignored(address) for address in participants):
		return "filtered"
	return "wait"


def run(doc, imap, deadline):
	account = frappe.get_doc("Email Account", doc.email_account)
	changed = []
	for folder, uidvalidity in pending_folders(doc.name):
		if mailbox.uidvalidity(imap, folder) != uidvalidity:
			changed.append(folder)
			continue
		mailbox.select(imap, folder)
		for row in pending(doc.name, folder, uidvalidity):
			if time.monotonic() > deadline:
				return False
			handle(account, imap, row)
	doc.db_set(
		"error",
		_("Folders changed on the server, scan again: {0}").format(", ".join(changed)) if changed else None,
	)
	return True


def pending_folders(mail_import):
	return frappe.get_all(
		"Mail Import Message",
		filters={"mail_import": mail_import, "state": "Pending"},
		fields=["folder", "uidvalidity"],
		distinct=True,
		order_by="folder asc",
		as_list=True,
	)


def pending(mail_import, folder, uidvalidity):
	return frappe.get_all(
		"Mail Import Message",
		filters={
			"mail_import": mail_import,
			"state": "Pending",
			"folder": folder,
			"uidvalidity": uidvalidity,
		},
		fields=["name", "folder", "uid", "message_id", "participants", "outgoing"],
		order_by="uid asc",
	)


def handle(account, imap, row):
	decision = decide(row)
	if decision == "filtered":
		update(row, state="Filtered")
	elif decision == "import":
		if already_present(account, row):
			update(row, state="Present")
		else:
			fetch_and_import(account, imap, row)
	frappe.db.commit()


def already_present(account, row):
	if row.message_id:
		return sent_mail.known(row.message_id)
	return bool(
		frappe.db.exists(
			"Communication",
			{
				"email_account": account.name,
				"imap_folder": row.folder,
				"uid": str(row.uid),
				"message_id": ("is", "not set"),
			},
		)
	)


def fetch_and_import(account, imap, row):
	raw = sent_mail.fetch_raw(imap, row.uid)
	if raw is None:
		update(row, state="Failed", error=_("Mail not found on the server"))
		return
	if len(raw) > sent_mail.MAX_MAIL_BYTES:
		update(row, state="Too Large")
		return
	mail = BackfillMail(raw, account, row)
	frappe.db.savepoint("backfill_mail")
	try:
		communication = mail.create()
	except Exception as error:
		frappe.db.rollback(save_point="backfill_mail")
		frappe.log_error(title=_("Mail import failed: {0}").format(row.message_id or row.uid))
		update(row, state="Failed", error=str(error)[:1000])
		return
	update(row, state="Imported", communication=communication.name)
	sent_mail.mail_read(mail, communication, mail.direction)


def update(row, **values):
	frappe.db.set_value("Mail Import Message", row.name, values, update_modified=False)
