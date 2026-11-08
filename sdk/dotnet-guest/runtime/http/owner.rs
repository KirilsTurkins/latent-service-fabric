//! Release of one admitted logical owner, after its actual future is dropped.
use super::latent::runtime::activation as runtime;
use std::cell::Cell;

#[derive(Clone, Copy)]
enum Continuation {
    None,
    Fenced,
    Owned(runtime::Token),
}

thread_local! {
    static CONTINUATION: Cell<Continuation> = const { Cell::new(Continuation::None) };
}

pub fn continuation() -> Result<Option<runtime::Token>, runtime::Error> {
    match CONTINUATION.with(Cell::get) {
        Continuation::None => Ok(None),
        Continuation::Fenced => Err(runtime::Error::InvalidState),
        Continuation::Owned(token) => Ok(Some(token)),
    }
}

pub fn set_continuation(owner: Option<runtime::Token>) {
    CONTINUATION.with(|current| {
        current.set(match owner {
            Some(token) => Continuation::Owned(token),
            None => Continuation::None,
        })
    });
}

pub fn fence_continuation() {
    CONTINUATION.with(|current| current.set(Continuation::Fenced));
}

pub struct Owner(runtime::Token);
impl Owner {
    pub fn new(kind: runtime::OwnerKind) -> Result<Self, runtime::Error> {
        runtime::register(kind, continuation()?).map(Self)
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
