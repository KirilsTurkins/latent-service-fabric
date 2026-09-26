//! Bounded trusted protocol state and continuations of an existing operation.
use super::{
    Arc, Charge, Kind, PlatformError, PoolAdmission, PoolCall, ProviderClient, ProviderPools,
};

/// Retain after the actual protocol objects it accounts for. Dropping a waiter
/// must never drop this charge while a socket/driver/parser still owns that state.
pub struct ProviderMetadata {
    _charge: Charge,
}
impl ProviderPools {
    /// Reserve before allocating adapter configuration, TLS or decoder state.
    /// This is shared node accounting, not a claim about total process RSS.
    pub fn reserve_protocol_metadata(
        &self,
        bytes: usize,
    ) -> Result<ProviderMetadata, PlatformError> {
        self.inner.check()?;
        if bytes == 0 || bytes > 1024 * 1024 {
            return Err(super::capacity());
        }
        Ok(ProviderMetadata {
            _charge: self.inner.quotas.acquire(Kind::Metadata, bytes)?,
        })
    }
    /// A redirect cannot mint another activation, extend the timeout, or escape
    /// the original tenant/plan. Drop the old operation before awaiting this one.
    pub fn admit_followup<T: Send + 'static>(
        &self,
        client: &Arc<ProviderClient<T>>,
        previous: &PoolCall,
    ) -> Result<PoolAdmission, PlatformError> {
        if !previous.belongs_to(&self.inner) {
            return Err(super::denied());
        }
        previous.io().checkpoint()?;
        previous
            .io()
            .with_session(|session| self.admit_until(client, session, previous.io().deadline()))
    }
}
