//! Shared source fixtures are loaded once; tests keep their own identities.

#[path = "host/accounting/tests/support.rs"]
pub(crate) mod accounting;
#[path = "../../latent-packaging/tests/fixtures/host.rs"]
pub(crate) mod host;
#[path = "../../latent-packaging/tests/fixtures/mod.rs"]
pub(crate) mod packaging;
