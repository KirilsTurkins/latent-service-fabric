use super::{Result, SecretError};
use latent_capabilities::broker::pools::{ProviderMetadata, ProviderPools};
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};

pub(super) struct Plaintext {
    pub bytes: AtomicUsize,
    maximum: usize,
}
pub(super) struct Charge {
    owner: Arc<Plaintext>,
    size: usize,
    _pool: ProviderMetadata,
}
impl Drop for Charge {
    fn drop(&mut self) {
        self.owner.bytes.fetch_sub(self.size, Ordering::AcqRel);
    }
}
impl Plaintext {
    pub fn new(maximum: usize) -> Arc<Self> {
        Arc::new(Self {
            bytes: AtomicUsize::new(0),
            maximum,
        })
    }
    pub fn reserve(self: &Arc<Self>, pools: &ProviderPools, size: usize) -> Result<Charge> {
        let pool = pools.reserve_protocol_metadata(size)?;
        self.bytes
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |n| {
                n.checked_add(size).filter(|n| *n <= self.maximum)
            })
            .map_err(|_| SecretError::Unavailable)?;
        Ok(Charge {
            owner: self.clone(),
            size,
            _pool: pool,
        })
    }
}
