import re
from datetime import datetime
from email.message import EmailMessage
from email.parser import BytesHeaderParser
from email.utils import format_datetime, parsedate_to_datetime

FETCH_SET = re.compile(r"^[\d,]+$")


def raw_mail(sender, to, subject, message_id=None, cc=None, sent=None, body="Hello", size=None):
	mail = EmailMessage()
	mail["From"] = sender
	mail["To"] = to
	if cc:
		mail["Cc"] = cc
	mail["Subject"] = subject
	mail["Date"] = format_datetime((sent or datetime(2024, 5, 1, 10, 0)).astimezone())
	if message_id:
		mail["Message-ID"] = f"<{message_id}>"
	mail.set_content(body if size is None else "x" * size)
	return mail.as_bytes()


class FakeMailbox:
	"""IMAP double with folders and UIDs; any write to the mailbox fails the test."""

	def __init__(self):
		self.folders = {}
		self.selected = None
		self.readonly = []
		self.fetched = []
		self.sizes = {}

	def folder(self, name, uidvalidity=1, flags="\\HasNoChildren"):
		self.folders[name] = {"uidvalidity": uidvalidity, "flags": flags, "mails": {}}
		return self

	def add(self, folder, uid, raw):
		self.folders[folder]["mails"][uid] = raw
		return self

	def list(self, *args):
		return "OK", [f'({f["flags"]}) "/" "{name}"'.encode() for name, f in self.folders.items()]

	def status(self, folder, items):
		name = folder.strip('"')
		f = self.folders[name]
		uidnext = max(f["mails"], default=0) + 1
		return "OK", [f'"{name}" (UIDVALIDITY {f["uidvalidity"]} UIDNEXT {uidnext})'.encode()]

	def select(self, folder, readonly=False):
		if not readonly:
			raise AssertionError("folders must be selected read-only")
		self.readonly.append(readonly)
		self.selected = folder.strip('"')
		return "OK", [str(len(self.mails)).encode()]

	@property
	def mails(self):
		return self.folders[self.selected]["mails"]

	def uid(self, command, *args):
		if command == "search":
			return "OK", [b" ".join(str(u).encode() for u in self.search(args[1]))]
		if command == "fetch":
			return self.fetch(args[0], args[1])
		raise AssertionError(f"unexpected UID {command}")

	def search(self, criteria):
		tokens = criteria.split()
		start = int(tokens[tokens.index("UID") + 1].split(":")[0])
		since = self.day(tokens, "SENTSINCE")
		before = self.day(tokens, "SENTBEFORE")
		found = []
		for uid in sorted(self.mails):
			sent = parsedate_to_datetime(BytesHeaderParser().parsebytes(self.mails[uid])["Date"]).date()
			if (since and sent < since) or (before and sent >= before):
				continue
			found.append(uid)
		return [u for u in found if u >= start] or ([found[-1]] if found else [])

	def day(self, tokens, key):
		if key not in tokens:
			return None
		return datetime.strptime(tokens[tokens.index(key) + 1], "%d-%b-%Y").date()

	def fetch(self, uids, spec):
		assert FETCH_SET.match(uids), uids
		assert "PEEK" in spec or "[" not in spec, "fetch must not set \\Seen"
		parts = []
		for uid in (int(u) for u in uids.split(",")):
			if uid not in self.mails:
				continue
			raw = self.mails[uid]
			size = self.sizes.get(uid, len(raw))
			if "HEADER.FIELDS" in spec:
				data = raw.split(b"\n\n", 1)[0] + b"\n\n"
				parts += [
					(f"1 (UID {uid} RFC822.SIZE {size} BODY[HEADER] {{{len(data)}}}".encode(), data),
					b")",
				]
			else:
				self.fetched.append(uid)
				parts += [(f"1 (UID {uid} BODY[] {{{len(raw)}}}".encode(), raw), b")"]
		return "OK", parts

	def store(self, *args):
		raise AssertionError("mailbox must not be written")

	copy = move = expunge = append = create = delete = rename = store
