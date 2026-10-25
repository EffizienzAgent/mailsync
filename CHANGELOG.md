# Changelog

## [0.2.3](https://github.com/EffizienzAgent/mailsync/compare/v0.2.2...v0.2.3) (2026-10-25)


### Bug Fixes

* **outgoing:** harden References header against bad ids and log failures ([ab936e3](https://github.com/EffizienzAgent/mailsync/commit/ab936e3a418cc68725875cdc3ab1ba72f9cf82fa))
* **outgoing:** set References header on replies ([8958572](https://github.com/EffizienzAgent/mailsync/commit/8958572bb1ca75437e273afeb6de8cd941d0240b))

## [0.2.2](https://github.com/EffizienzAgent/mailsync/compare/v0.2.1...v0.2.2) (2026-10-25)


### Bug Fixes

* document mail read hook limits and sensitive raw mail ([c1fc483](https://github.com/EffizienzAgent/mailsync/commit/c1fc483c8a6fe2a32a5cdc091834ae389aa3b2d9))
* keep the Sent sync going when a mail read hook commits and raises ([83500f4](https://github.com/EffizienzAgent/mailsync/commit/83500f430f9563a978de19f26103835902a23774))

## [0.2.1](https://github.com/EffizienzAgent/mailsync/compare/v0.2.0...v0.2.1) (2026-10-25)


### Documentation

* state when mailsync_mail_read is called ([746260c](https://github.com/EffizienzAgent/mailsync/commit/746260c2dc63050d9809a2967b4bf207a15c0963))

## [0.2.0](https://github.com/EffizienzAgent/mailsync/compare/v0.1.2...v0.2.0) (2026-10-25)


### Features

* **hooks:** pass raw mails read from IMAP to mailsync_mail_read ([7cbb807](https://github.com/EffizienzAgent/mailsync/commit/7cbb807f82511703a202fc189c15131102eb51b6))

## [0.1.2](https://github.com/EffizienzAgent/mailsync/compare/v0.1.1...v0.1.2) (2026-10-24)


### Bug Fixes

* **tls:** verify the server certificate on outgoing SMTP ([4379315](https://github.com/EffizienzAgent/mailsync/commit/43793153aad400fbe0d39df936833507825be9d9))

## [0.1.1](https://github.com/EffizienzAgent/mailsync/compare/v0.1.0...v0.1.1) (2026-10-24)


### Bug Fixes

* **sent:** cap the import by size and handle a missing STATUS ([e3accab](https://github.com/EffizienzAgent/mailsync/commit/e3accabcbe7723f3cfcd0a8050ecc43743757cd0))
* **status:** skip unsafe Message-IDs and isolate failed searches ([6882ce3](https://github.com/EffizienzAgent/mailsync/commit/6882ce3df07266dcc0eda7f40634dd23f08582bd))
* **tls:** verify the server certificate on STARTTLS ([22d57f7](https://github.com/EffizienzAgent/mailsync/commit/22d57f76fdff6c88a1393a66432d1c6860e52b21))


### Documentation

* STARTTLS verification, import limits and untrusted hook arguments ([15adf0d](https://github.com/EffizienzAgent/mailsync/commit/15adf0df8591993fac51673eb12ba78e9c37131a))

## 0.1.0 (2026-10-24)


### Features

* IMAP mail sync app ([706a097](https://github.com/EffizienzAgent/mailsync/commit/706a097a4922ee4a8706deb1b07d79f325ad1b8e))

### Documentation

* professional setup and support section ([a5f29b4](https://github.com/EffizienzAgent/mailsync/commit/a5f29b41033f590e05cb3079d5d65a6c9720629f))
