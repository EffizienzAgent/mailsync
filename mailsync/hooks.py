app_name = "mailsync"
app_title = "Mailsync"
app_publisher = "EffizienzAgent (Tobias Mende)"
app_description = "IMAP mail sync: Sent folder import and reply/close status from the mailbox"
app_license = "mit"

before_request = ["mailsync.tls.apply"]
before_job = ["mailsync.tls.apply"]
make_email_body_message = ["mailsync.references.set_references"]

has_permission = {
	"Mail Import": "mailsync.backfill.access.has_permission",
	"Mail Import Message": "mailsync.backfill.access.has_permission",
	"Mail Import Address": "mailsync.backfill.access.has_permission",
}
permission_query_conditions = {
	"Mail Import": "mailsync.backfill.access.query_conditions",
	"Mail Import Message": "mailsync.backfill.access.message_conditions",
	"Mail Import Address": "mailsync.backfill.access.address_conditions",
}

scheduler_events = {
	"cron": {
		"*/2 * * * *": ["mailsync.mail_sync.sync_all"],
	},
}

# Apps can extend mailsync with these hooks:
# mailsync_recipient_links = ["myapp.mail.recipient_links"]
# mailsync_status_changed = ["myapp.mail.status_changed"]
# mailsync_mail_read = ["myapp.mail.mail_read"]
# mailsync_own_address = ["myapp.mail.is_own"]
# mailsync_address_suggestion = ["myapp.mail.suggest"]
# mailsync_contact_link_doctype = "Customer"
