//! Wait only for bookkeeping access, before any socket or dial is allocated.
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
