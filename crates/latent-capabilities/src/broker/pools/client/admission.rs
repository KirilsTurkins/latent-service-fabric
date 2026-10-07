//! Wait only for bookkeeping access, before any socket or dial is allocated.
use super::super::DeferredRequest;
use super::{
    Arc, ConnectionReservation, PlatformError, PoolCall, PooledConnection, ProviderClient,
};
use std::sync::{Mutex, MutexGuard, TryLockError};
use std::time::Duration;

#[cfg(all(test, target_os = "linux"))]
mod tests;

pub(super) enum ClientAccessError {
    Contended,
    Failed(PlatformError),
}
impl ClientAccessError {
    pub(super) fn immediate(self) -> PlatformError {
        match self {
            Self::Contended => super::busy(),
            Self::Failed(error) => error,
        }
    }
}
impl From<PlatformError> for ClientAccessError {
    fn from(error: PlatformError) -> Self {
        Self::Failed(error)
    }
}
pub(super) fn bookkeeping<T>(lock: &Mutex<T>) -> Result<MutexGuard<'_, T>, ClientAccessError> {
    match lock.try_lock() {
        Ok(guard) => Ok(guard),
        Err(TryLockError::WouldBlock) => Err(ClientAccessError::Contended),
        Err(TryLockError::Poisoned(_)) => {
            Err(ClientAccessError::Failed(super::super::super::error(
                latent_core::PlatformErrorCode::Unavailable,
                "provider-client-owner-poisoned",
            )))
        }
    }
}

impl<T: Send + 'static> ProviderClient<T> {
    /// Maintenance may inspect the idle queue concurrently. Wait with the
    /// existing call's deadline and cancellation; never replay protocol work.
    pub async fn checkout_wait(
        self: &Arc<Self>,
        call: &PoolCall,
    ) -> Result<Option<PooledConnection<T>>, PlatformError> {
        loop {
            call.check_client(&self.core)?;
            match self.checkout_owned(Some(call.io.lease()), None) {
                Ok(value) => return Ok(value),
                Err(ClientAccessError::Failed(error)) => return Err(error),
                Err(ClientAccessError::Contended) => {
                    call.io
                        .wait_for(tokio::time::sleep(Duration::from_millis(1)))
                        .await?;
                }
            }
        }
    }

    /// Reserve exactly once after bookkeeping becomes accessible. Actual
    /// capacity exhaustion, an active dial, backoff and poisoned ownership fail
    /// immediately; only unacquired bookkeeping locks may wait.
    pub async fn reserve_connection_wait(
        self: &Arc<Self>,
        call: &PoolCall,
    ) -> Result<ConnectionReservation<T>, PlatformError> {
        loop {
            call.check_client(&self.core)?;
            match self.reserve_owned(Some(call.io.lease()), None, None) {
                Ok(value) => return Ok(value),
                Err(ClientAccessError::Failed(error)) => return Err(error),
                Err(ClientAccessError::Contended) => {
                    call.io
                        .wait_for(tokio::time::sleep(Duration::from_millis(1)))
                        .await?;
                }
            }
        }
    }
}

impl<T: Send + 'static> ProviderClient<T> {
    /// Wait only for unacquired idle bookkeeping under the original request.
    /// Fresh reconciliation never borrows an idle guest connection.
    pub async fn checkout_deferred_wait(
        self: &Arc<Self>,
        request: &DeferredRequest,
    ) -> Result<Option<PooledConnection<T>>, PlatformError> {
        loop {
            let (maintenance, ingress) = request.connection_owners(&self.core)?;
            if maintenance.is_some() {
                return Ok(None);
            }
            match self.checkout_owned(None, ingress) {
                Ok(value) => return Ok(value),
                Err(ClientAccessError::Failed(error)) => return Err(error),
                Err(ClientAccessError::Contended) => {
                    request
                        .wait_for(tokio::time::sleep(Duration::from_millis(1)))
                        .await?;
                }
            }
        }
    }

    /// Reuse the accepted request's immutable deadline while bookkeeping is
    /// held by maintenance/status inspection. Reserve once after access; actual
    /// capacity, active dial, backoff and poison retain their immediate refusals.
    /// This never repeats any protocol operation or allocates another request.
    pub async fn reserve_deferred_connection_wait(
        self: &Arc<Self>,
        request: &DeferredRequest,
    ) -> Result<ConnectionReservation<T>, PlatformError> {
        loop {
            let (maintenance, ingress) = request.connection_owners(&self.core)?;
            match self.reserve_owned(None, maintenance, ingress) {
                Ok(value) => return Ok(value),
                Err(ClientAccessError::Failed(error)) => return Err(error),
                Err(ClientAccessError::Contended) => {
                    request
                        .wait_for(tokio::time::sleep(Duration::from_millis(1)))
                        .await?;
                }
            }
        }
    }
}
