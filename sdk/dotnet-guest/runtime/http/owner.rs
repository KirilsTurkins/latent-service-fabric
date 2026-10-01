//! Release of one admitted logical owner, after its actual future is dropped.
use super::latent::runtime::activation as runtime;

pub struct Owner(runtime::Token);
impl Owner {
    pub fn new(kind: runtime::OwnerKind) -> Result<Self, runtime::Error> {
        runtime::register(kind, None).map(Self)
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
