app_name = "mailsync"
app_title = "Mailsync"
app_publisher = "EffizienzAgent"
app_description = "IMAP mail sync: Sent folder import and reply/close status from the mailbox"
app_license = "mit"

before_request = ["mailsync.tls.apply"]
before_job = ["mailsync.tls.apply"]

scheduler_events = {
	"cron": {
		"*/2 * * * *": ["mailsync.mail_sync.sync_all"],
	},
}

# Apps can extend mailsync with these hooks:
# mailsync_recipient_links = ["myapp.mail.recipient_links"]
# mailsync_status_changed = ["myapp.mail.status_changed"]
# mailsync_mail_read = ["myapp.mail.mail_read"]
