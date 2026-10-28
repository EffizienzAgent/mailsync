# Changelog

## [0.3.0](https://github.com/EffizienzAgent/mailsync/compare/v0.2.3...v0.3.0) (2026-10-28)


### Features

* **import:** add address rules and extension hooks ([4dd34e9](https://github.com/EffizienzAgent/mailsync/commit/4dd34e9adc06d64b50706c12913bf0b112316959))
* **import:** add mail import doctypes and access rules ([b19609f](https://github.com/EffizienzAgent/mailsync/commit/b19609fb69332ddaf7ac68961213c0f90cfa1027))
* **import:** import mails with known contacts as closed communications ([23c958a](https://github.com/EffizienzAgent/mailsync/commit/23c958a81a01512ddd75ebabff3361d8e7a11cb1))
* **import:** list folders and scan headers ([afcc04f](https://github.com/EffizienzAgent/mailsync/commit/afcc04f2dca79c45df75bf2de6327a1afa7bb7e9))
* **import:** review unknown addresses ([9d97f6b](https://github.com/EffizienzAgent/mailsync/commit/9d97f6b3c9bb6a3d0943e8a8ede2c79bf64bb739))
* **import:** review unknown addresses ([2c7115b](https://github.com/EffizienzAgent/mailsync/commit/2c7115b0716939361d4aee9cf1d1617ec693375c))
* **import:** run scan and import as resumable jobs ([a0ce1b2](https://github.com/EffizienzAgent/mailsync/commit/a0ce1b26a77cdb3bbfb14f7045067528b3580305))
* **import:** translate access messages ([eabc14a](https://github.com/EffizienzAgent/mailsync/commit/eabc14a189b279f2c038d69293b9e84ef06e0b24))
* one-off import of past mail from IMAP folders ([9718e9e](https://github.com/EffizienzAgent/mailsync/commit/9718e9e274a9c06c13623569c3e8e123a09f9b9a))


### Bug Fixes

* **import:** keep scan and review going on unusual mail and harden access ([fe1e898](https://github.com/EffizienzAgent/mailsync/commit/fe1e898c104c8db4b89fcb9822c3e1343b3220b4))


### Documentation

* add design for one-off IMAP backfill ([f2396af](https://github.com/EffizienzAgent/mailsync/commit/f2396afdcc2128be88ba6a30e6fdf554dc37acf5))
* add implementation plan for IMAP backfill ([837fcc6](https://github.com/EffizienzAgent/mailsync/commit/837fcc67248f760601619ae049d7c83149c3a639))
* describe importing past mail ([d8d9377](https://github.com/EffizienzAgent/mailsync/commit/d8d93773350a6582423e3caf412f6403efda4caf))

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
