//! Stable trusted invoker across explicit immutable provider epochs. No guest
//! can rotate this owner or mint the replacement publication/binding grants.
#[cfg(any(test, feature = "development-outbound"))]
use crate::StreamProviderConfig;
use crate::{StreamError, StreamErrorCode, StreamProvider, StreamUsage};
#[cfg(any(test, feature = "development-outbound"))]
use latent_capabilities::broker::pools::ProviderPools;
use latent_capabilities::broker::{
    network::{OutboundStreamInvoker, StreamConnectRequest, StreamInvocation},
    pools::ProviderMetadata,
    CapabilitySession, ProviderReference,
};
use std::sync::Arc;
use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Mutex,
    },
    time::Instant,
};

const MAX_RETIRED: usize = 8;
struct State {
    current: StreamProvider,
    retired: [Option<StreamProvider>; MAX_RETIRED],
    stopped: bool,
}
/// Its installation remains explicitly restricted to qualification builds.
pub struct StreamLifecycle {
    state: Mutex<State>,
    maintenance_claimed: AtomicBool,
    #[cfg(any(test, feature = "development-outbound"))]
    pools: Arc<ProviderPools>,
    #[cfg(any(test, feature = "development-outbound"))]
    id: String,
    _metadata: ProviderMetadata,
}
#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StreamStatus {
    pub profile: &'static str,
    pub configuration_digest: String,
    pub configuration_epoch: u64,
    pub retired_generations: usize,
    pub usage: StreamUsage,
    pub stopped: bool,
    pub maintenance_owners: usize,
}
fn unavailable() -> StreamError {
    StreamError::new(StreamErrorCode::Revoked)
}

impl StreamLifecycle {
    /// One maintained-node future scans bounded weak slots on the existing
    /// control runtime. The node owns and joins it; installation spawns nothing.
    pub fn maintenance(self: &Arc<Self>) -> Result<crate::StreamMaintenance, StreamError> {
        let state = self.state.lock().map_err(|_| unavailable())?;
        if state.stopped {
            return Err(unavailable());
        }
        let metadata = state
            .current
            .inner
            .pools
            .reserve_protocol_metadata(8 * 1024)?;
        self.maintenance_claimed
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .map_err(|_| StreamError::new(StreamErrorCode::Exhausted))?;
        Ok(crate::StreamMaintenance::new(
            Arc::downgrade(self),
            metadata,
        ))
    }

    pub(crate) fn release_maintenance(&self) {
        self.maintenance_claimed.store(false, Ordering::Release);
    }

    pub(crate) fn maintenance_step(&self, now: Instant) -> Result<bool, StreamError> {
        let state = match self.state.try_lock() {
            Ok(state) => state,
            Err(std::sync::TryLockError::WouldBlock) => return Ok(false),
            Err(std::sync::TryLockError::Poisoned(_)) => return Err(unavailable()),
        };
        if state.stopped {
            return Ok(true);
        }
        state.current.maintenance_step(now);
        for retired in state.retired.iter().flatten() {
            retired.maintenance_step(now);
        }
        Ok(false)
    }

    #[cfg(any(test, feature = "development-outbound"))]
    pub fn install_for_qualification(
        pools: Arc<ProviderPools>,
        id: &str,
        epoch: u64,
        config: StreamProviderConfig,
    ) -> Result<Self, StreamError> {
        if id.is_empty() || id.len() > 128 {
            return Err(StreamError::new(StreamErrorCode::InvalidInput));
        }
        let current = StreamProvider::install_for_qualification(pools, id, epoch, 0, config)?;
        Self::from_installed_for_qualification(id, current)
    }
    #[cfg(any(test, feature = "development-outbound"))]
    pub fn from_installed_for_qualification(
        id: &str,
        current: StreamProvider,
    ) -> Result<Self, StreamError> {
        if id.is_empty() || id.len() > 128 || current.inner.installed.is_retired() {
            return Err(StreamError::new(StreamErrorCode::InvalidInput));
        }
        let pools = Arc::clone(&current.inner.pools);
        let metadata = pools.reserve_protocol_metadata(16 * 1024)?;
        Ok(Self {
            state: Mutex::new(State {
                current,
                retired: std::array::from_fn(|_| None),
                stopped: false,
            }),
            maintenance_claimed: AtomicBool::new(false),
            pools,
            id: id.into(),
            _metadata: metadata,
        })
    }
    pub fn reference(&self) -> Result<ProviderReference, StreamError> {
        let state = self.state.lock().map_err(|_| unavailable())?;
        if state.stopped {
            return Err(unavailable());
        }
        Ok(state.current.reference())
    }
    /// Every change forces retirement, including trust/credential changes. A
    /// caller must separately issue exact new digest/epoch grants and bindings.
    #[cfg(any(test, feature = "development-outbound"))]
    pub fn rotate(
        &self,
        expected_epoch: u64,
        new_epoch: u64,
        config: StreamProviderConfig,
    ) -> Result<ProviderReference, StreamError> {
        let mut state = self.state.lock().map_err(|_| unavailable())?;
        if state.stopped
            || state.current.reference().configuration_epoch() != expected_epoch
            || new_epoch <= expected_epoch
        {
            return Err(unavailable());
        }
        for retired in &mut state.retired {
            if retired
                .as_ref()
                .is_some_and(|p| p.usage().is_ok_and(|u| u.owners == 0))
            {
                *retired = None;
            }
        }
        let index = state
            .retired
            .iter()
            .position(Option::is_none)
            .ok_or_else(|| StreamError::new(StreamErrorCode::Exhausted))?;
        let replacement = StreamProvider::install_for_qualification(
            Arc::clone(&self.pools),
            &self.id,
            new_epoch,
            expected_epoch,
            config,
        )?;
        // Installation fenced the old epoch first; abort now wakes accepted
        // original work and retains physical charges through its final Drop.
        state.current.retire();
        let retired = std::mem::replace(&mut state.current, replacement);
        state.retired[index] = Some(retired);
        Ok(state.current.reference())
    }
    pub fn status(&self) -> Result<StreamStatus, StreamError> {
        let state = self
            .state
            .try_lock()
            .map_err(|_| StreamError::new(StreamErrorCode::Exhausted))?;
        let reference = state.current.reference();
        let mut usage = state.current.usage()?;
        for retired in state.retired.iter().flatten() {
            let u = retired.usage()?;
            usage.owners += u.owners;
            usage.connections += u.connections;
            usage.pending_operations += u.pending_operations;
            usage.retained_chunks += u.retained_chunks;
            usage.accepted_write_bytes += u.accepted_write_bytes;
            usage.delivered_read_bytes += u.delivered_read_bytes;
        }
        Ok(StreamStatus {
            profile: latent_capabilities::broker::network::STREAM_PROFILE,
            configuration_digest: reference.configuration_digest().into(),
            configuration_epoch: reference.configuration_epoch(),
            retired_generations: state.retired.iter().filter(|p| p.is_some()).count(),
            usage,
            stopped: state.stopped,
            maintenance_owners: usize::from(self.maintenance_claimed.load(Ordering::Acquire)),
        })
    }
    pub fn retire(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.stopped = true;
        state.current.retire();
        for retired in state.retired.iter().flatten() {
            retired.retire();
        }
    }
    /// No cleanup task is spawned. A bounded waiter observes actual retained
    /// owners; timeout returns outstanding/quarantined work without refund.
    pub async fn drain(&self, deadline: Instant) -> Result<StreamStatus, StreamError> {
        self.retire();
        loop {
            let status = self.status()?;
            if status.usage.owners == 0 || Instant::now() >= deadline {
                return Ok(status);
            }
            tokio::time::sleep_until(
                (Instant::now() + std::time::Duration::from_millis(5))
                    .min(deadline)
                    .into(),
            )
            .await;
        }
    }
}
impl OutboundStreamInvoker for StreamLifecycle {
    fn inspect_node_usage(
        &self,
    ) -> Result<
        Option<latent_capabilities::broker::network::StreamNodeUsage>,
        latent_core::PlatformError,
    > {
        let status = self.status().map_err(crate::inspection_unavailable)?;
        Ok(Some(
            latent_capabilities::broker::network::StreamNodeUsage {
                configuration_epoch: status.configuration_epoch,
                retired_generations: status.retired_generations,
                stopped: status.stopped,
                owners: status.usage.owners,
                connections: status.usage.connections,
                pending_operations: status.usage.pending_operations,
                retained_chunks: status.usage.retained_chunks,
                maintenance_owners: status.maintenance_owners,
                live_accepted_write_bytes: status.usage.accepted_write_bytes,
                live_delivered_read_bytes: status.usage.delivered_read_bytes,
            },
        ))
    }

    fn start(
        &self,
        session: &CapabilitySession,
        request: StreamConnectRequest,
    ) -> Result<StreamInvocation, StreamError> {
        let provider = {
            let state = self.state.lock().map_err(|_| unavailable())?;
            if state.stopped {
                return Err(unavailable());
            }
            state.current.clone()
        };
        provider.start(session, request)
    }
}
impl Drop for StreamLifecycle {
    fn drop(&mut self) {
        self.retire();
    }
}
