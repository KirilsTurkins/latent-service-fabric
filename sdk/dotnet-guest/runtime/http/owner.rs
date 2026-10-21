//! Release of one admitted logical owner, after its actual future is dropped.
use super::latent::runtime::activation as runtime;
use std::cell::Cell;

thread_local! {
    static CONTINUATION: Cell<Option<runtime::Token>> = const { Cell::new(None) };
}

pub fn continuation() -> Option<runtime::Token> {
    CONTINUATION.with(Cell::get)
}

pub fn set_continuation(owner: Option<runtime::Token>) {
    CONTINUATION.with(|current| current.set(owner));
}

pub struct Owner(runtime::Token);
impl Owner {
    pub fn new(kind: runtime::OwnerKind) -> Result<Self, runtime::Error> {
        runtime::register(kind, continuation()).map(Self)
    }

    pub(crate) fn token(&self) -> runtime::Token {
        self.0
    }
}
impl Drop for Owner {
    fn drop(&mut self) {
        // Original host retirement remains authoritative if cancellation or
        // revoked policy has already closed this generation. Settle releases
        // bookkeeping; it does not prove completed I/O or an elapsed timer.
        let _ = runtime::settle(self.0);
    }
}
