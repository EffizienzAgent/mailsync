import frappe
from frappe.tests import IntegrationTestCase

from mailsync.backfill import addresses, review
from mailsync.tests.factories import hooks, make_account, make_contact, make_import, unique

SUGGEST_HOOK = "mailsync.tests.test_backfill_review.suggest"
SUGGESTED = {}


def suggest(address):
	return SUGGESTED.get(address, {})


def address(prefix):
	return f"{unique(prefix).replace(' ', '')}@acme.test"


def add_message(mail_import, participants, subject="Hello", state="Pending"):
	frappe.get_doc(
		{
			"doctype": "Mail Import Message",
			"mail_import": mail_import,
			"subject": subject,
			"state": state,
			"participants": "\n".join(f"{a} {n}".strip() for a, n in participants),
		}
	).db_insert()


class TestBackfillReview(IntegrationTestCase):
	def setUp(self):
		addresses.clear()
		SUGGESTED.clear()
		self.account = make_account(enable_incoming=0)
		self.doc = make_import(self.account.name)
		self.unknown = address("unknown")

	def rows(self, mail_import=None):
		return {
			r.email_id: r
			for r in frappe.get_all(
				"Mail Import Address",
				filters={"mail_import": mail_import or self.doc.name},
				fields=[
					"name",
					"email_id",
					"full_name",
					"mail_count",
					"subjects",
					"decision",
					"first_name",
					"last_name",
					"suggested_contact",
					"link_doctype",
					"link_name",
					"contact",
				],
			)
		}

	def row(self, email):
		return frappe.get_doc("Mail Import Address", self.rows()[email].name)

	def test_refresh_lists_unknown_only(self):
		known = address("known")
		make_contact(known)
		ignored = address("ignored")
		frappe.get_doc({"doctype": "Mail Ignored Address", "email_id": ignored}).insert(
			ignore_permissions=True
		)
		add_message(self.doc.name, [(self.unknown, "Doe, Jane"), (known, ""), (ignored, "")], "First")
		add_message(self.doc.name, [(self.unknown, "")], "Second")
		add_message(self.doc.name, [(address("present"), "")], "Old", state="Present")
		review.refresh(self.doc)
		rows = self.rows()
		self.assertEqual(list(rows), [self.unknown])
		row = rows[self.unknown]
		self.assertEqual((row.mail_count, row.full_name, row.decision), (2, "Doe, Jane", "Open"))
		self.assertEqual((row.first_name, row.last_name), ("Jane", "Doe"))
		self.assertEqual(sorted(row.subjects.split("\n")), ["First", "Second"])

	def test_refresh_keeps_decisions_and_drops_resolved_open_rows(self):
		later_known = address("later")
		add_message(self.doc.name, [(self.unknown, ""), (later_known, "")])
		review.refresh(self.doc)
		self.row(self.unknown).ignore()
		make_contact(later_known)
		review.refresh(self.doc)
		rows = self.rows()
		self.assertEqual(list(rows), [self.unknown])
		self.assertEqual(rows[self.unknown].decision, "Ignored")

	def test_create_contact_with_company_link(self):
		add_message(self.doc.name, [(self.unknown, "Jane Doe")])
		review.refresh(self.doc)
		row = self.row(self.unknown)
		row.link_doctype, row.link_name = "Email Account", self.account.name
		row.save(ignore_permissions=True)
		row.create_contact()
		contact = frappe.get_doc("Contact", row.contact)
		self.assertEqual((contact.first_name, contact.last_name), ("Jane", "Doe"))
		self.assertEqual(contact.email_id, self.unknown)
		self.assertEqual(
			[(link.link_doctype, link.link_name) for link in contact.links],
			[("Email Account", self.account.name)],
		)
		self.assertEqual(row.decision, "Contact")
		self.assertEqual(addresses.contact_for(self.unknown), contact.name)

	def test_add_to_existing_contact(self):
		existing = make_contact(address("main"))
		add_message(self.doc.name, [(self.unknown, "")])
		review.refresh(self.doc)
		row = self.row(self.unknown)
		row.add_to_contact(existing)
		self.assertEqual(addresses.contact_for(self.unknown), existing)
		self.assertEqual((row.decision, row.contact), ("Contact", existing))

	def test_ignore_is_site_wide(self):
		add_message(self.doc.name, [(self.unknown, "")])
		review.refresh(self.doc)
		other = make_import(self.account.name)
		add_message(other.name, [(self.unknown, "")])
		review.refresh(other)
		self.row(self.unknown).ignore()
		self.assertTrue(addresses.is_ignored(self.unknown))
		self.assertEqual(self.rows(other.name)[self.unknown].decision, "Ignored")
		third = make_import(self.account.name)
		add_message(third.name, [(self.unknown, "")])
		review.refresh(third)
		self.assertEqual(self.rows(third.name), {})

	def test_ignore_many(self):
		second = address("second")
		add_message(self.doc.name, [(self.unknown, ""), (second, "")])
		review.refresh(self.doc)
		review.ignore_many([r.name for r in self.rows().values()])
		self.assertTrue(addresses.is_ignored(self.unknown) and addresses.is_ignored(second))

	def test_suggestion_prefilled(self):
		suggested = make_contact(address("suggested"))
		SUGGESTED[self.unknown] = {"contact": suggested, "link_name": self.account.name}
		add_message(self.doc.name, [(self.unknown, "")])
		with (
			hooks("mailsync_address_suggestion", [SUGGEST_HOOK]),
			hooks("mailsync_contact_link_doctype", ["Email Account"]),
		):
			review.refresh(self.doc)
		row = self.rows()[self.unknown]
		self.assertEqual((row.suggested_contact, row.contact), (suggested, suggested))
		self.assertEqual((row.link_doctype, row.link_name), ("Email Account", self.account.name))
