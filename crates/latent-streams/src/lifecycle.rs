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

#[cfg(all(test, unix))]
#[path = "tests/quarantine_usage.rs"]
mod quarantine_usage_tests;

const MAX_RETIRED: usize = 8;

// Keep the original provider available until pool notification has finished.
// If a callback unwinds, retire it after the lifecycle lock is released.
#[cfg(any(test, feature = "development-outbound"))]
struct DeferredRetirement(Option<StreamProvider>);

#[cfg(any(test, feature = "development-outbound"))]
impl DeferredRetirement {
    fn finish(mut self) {
        self.retire();
    }

    fn retire(&mut self) {
        if let Some(provider) = self.0.take() {
            if std::thread::panicking() {
                let _ =
                    std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| provider.retire()));
            } else {
                provider.retire();
            }
        }
    }
}

#[cfg(any(test, feature = "development-outbound"))]
impl Drop for DeferredRetirement {
    fn drop(&mut self) {
        self.retire();
    }
}

fn sum_quarantined(total: usize, next: usize) -> Result<usize, StreamError> {
    total
        .checked_add(next)
        .ok_or_else(|| StreamError::new(StreamErrorCode::Exhausted))
}
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
    /// Already included in `usage.owners` and `usage.connections`.
    pub quarantined_connections: usize,
    pub usage: StreamUsage,
    pub stopped: bool,
    pub current_generation_retired: bool,
    pub maintenance_owners: usize,
}
/// A bounded qualification observer of one original connection and epoch.
/// It does not clone the socket, alter cancellation, or create an owner charge;
/// each retained Arc keeps its already-paid original allocation alive.
#[cfg(feature = "development-read-witness")]
pub struct ReadCancelWitness {
    lifecycle: Arc<StreamLifecycle>,
    provider: StreamProvider,
    connection: crate::connection_registry::ConnectionOwner,
}

#[cfg(feature = "development-read-witness")]
impl ReadCancelWitness {
    /// Fail closed if the same provider generation is no longer current.
    pub fn original_generation_current(&self) -> Result<bool, StreamError> {
        let state = self
            .lifecycle
            .state
            .try_lock()
            .map_err(crate::snapshot_lock_error)?;
        Ok(!state.stopped
            && state.retired.iter().all(Option::is_none)
            && Arc::ptr_eq(&self.provider.inner, &state.current.inner)
            && !self.provider.inner.installed.is_retired())
    }

    /// The exact same connection has completed one read and still owns the
    /// completely constructed second read, whose first drop marker has not
    /// been reached. Its original socket and guard are retained at that edge.
    pub fn original_second_read_live(&self) -> Result<bool, StreamError> {
        Ok(self.original_generation_current()? && self.connection.original_second_read_live()?)
    }

    /// Count first read Pending drop markers, saturated at three. This is a
    /// sequentially consistent observation of the retained original connection.
    pub fn read_drop_starts(&self) -> u8 {
        self.connection.read_drop_starts()
    }
}

fn unavailable() -> StreamError {
    StreamError::new(StreamErrorCode::Revoked)
}

impl StreamLifecycle {
    /// Capture the sole connection in the currently installed development
    /// provider. No locks or callbacks are retained across the returned value.
    #[cfg(feature = "development-read-witness")]
    pub fn read_cancel_witness(self: &Arc<Self>) -> Result<Option<ReadCancelWitness>, StreamError> {
        let provider = {
            let state = self.state.try_lock().map_err(crate::snapshot_lock_error)?;
            if state.stopped
                || state.retired.iter().any(Option::is_some)
                || state.current.inner.installed.is_retired()
            {
                return Ok(None);
            }
            state.current.clone()
        };
        let Some(connection) = provider.inner.connections.sole_owner()? else {
            return Ok(None);
        };
        let witness = ReadCancelWitness {
            lifecycle: Arc::clone(self),
            provider,
            connection,
        };
        if !witness.original_generation_current()? {
            return Ok(None);
        }
        Ok(Some(witness))
    }

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
        // Maintenance can close a connection and wake its waiters. Retain the
        // bounded original provider generations, but release the lifecycle
        // lock before driving their callbacks or destroying any owners.
        let (current, retired, stopped) = {
            let state = match self.state.try_lock() {
                Ok(state) => state,
                Err(std::sync::TryLockError::WouldBlock) => return Ok(false),
                Err(std::sync::TryLockError::Poisoned(_)) => return Err(unavailable()),
            };
            (state.current.clone(), state.retired.clone(), state.stopped)
        };
        #[cfg(all(target_os = "linux", any(test, feature = "development-outbound")))]
        let protected = current.inner.native_bank.is_some()
            || retired
                .iter()
                .flatten()
                .any(|p| p.inner.native_bank.is_some());
        #[cfg(not(all(target_os = "linux", any(test, feature = "development-outbound"))))]
        let protected = false;
        if stopped && !protected {
            return Ok(true); // Original unselected maintenance behavior.
        }
        current.maintenance_step(now);
        for provider in retired.iter().flatten() {
            provider.maintenance_step(now);
        }
        if stopped {
            // No renewed authority or forced timeout-success. Unknown physical
            // retirement keeps the original paid driver and quarantine alive.
            let mut owners = current.usage()?.owners;
            for provider in retired.iter().flatten() {
                owners = owners.saturating_add(provider.usage()?.owners);
            }
            return Ok(owners == 0);
        }
        Ok(false)
    }

    /// Nonproduction logical reference only; no kernel/TLS accounting or
    /// provider-readiness qualification follows from this development install.
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
        self.rotate_with_installer(
            expected_epoch,
            new_epoch,
            config,
            StreamProvider::install_for_rotation,
        )
    }
    #[cfg(test)]
    pub(crate) fn rotate_tls_for_accounting_reference(
        &self,
        expected_epoch: u64,
        new_epoch: u64,
        config: StreamProviderConfig,
    ) -> Result<ProviderReference, StreamError> {
        self.rotate_with_installer(
            expected_epoch,
            new_epoch,
            config,
            StreamProvider::install_tls_for_rotation_reference,
        )
    }
    #[cfg(any(test, feature = "development-outbound"))]
    pub(crate) fn rotate_with_installer(
        &self,
        expected_epoch: u64,
        new_epoch: u64,
        config: StreamProviderConfig,
        install: crate::provider::DeferredProviderInstaller,
    ) -> Result<ProviderReference, StreamError> {
        // Keep removed generations alive until the lifecycle lock has been
        // released, including on a later installation failure.
        let mut removed: [Option<StreamProvider>; MAX_RETIRED] = std::array::from_fn(|_| None);
        let mut retirement = DeferredRetirement(None);
        // Declaration order matters on error/unwind: state drops first, then
        // deferred pool callbacks run without this lifecycle lock held.
        let mut completion = self.pools.defer_install();
        let mut state = self.state.lock().map_err(|_| unavailable())?;
        if state.stopped
            || state.current.reference().configuration_epoch() != expected_epoch
            || new_epoch <= expected_epoch
        {
            return Err(unavailable());
        }
        for (retired, removed) in state.retired.iter_mut().zip(&mut removed) {
            if retired
                .as_ref()
                .is_some_and(StreamProvider::closed_and_empty_for_pruning)
            {
                *removed = retired.take();
            }
        }
        let index = state
            .retired
            .iter()
            .position(Option::is_none)
            .ok_or_else(|| StreamError::new(StreamErrorCode::Exhausted))?;
        let replacement = install(
            Arc::clone(&self.pools),
            &self.id,
            new_epoch,
            expected_epoch,
            config,
            &mut completion,
        )?;
        let retired = std::mem::replace(&mut state.current, replacement);
        state.retired[index] = Some(retired.clone());
        retirement.0 = Some(retired);
        let reference = state.current.reference();
        completion.commit();
        drop(state);
        drop(removed);
        completion.finish();
        // Installation fenced the old epoch first. Wake its accepted work
        // outside the lifecycle lock; the original physical owners are kept.
        retirement.finish();
        Ok(reference)
    }
    pub fn status(&self) -> Result<StreamStatus, StreamError> {
        // A temporary connection observed below may be its last strong
        // owner. Its destructor can wake arbitrary waiters, so inspect only
        // after releasing the lifecycle mutex.
        let (current, retired, stopped) = {
            let state = self.state.try_lock().map_err(crate::snapshot_lock_error)?;
            (state.current.clone(), state.retired.clone(), state.stopped)
        };
        let reference = current.reference();
        let (mut usage, mut quarantined_connections) = current.usage_with_quarantine()?;
        for provider in retired.iter().flatten() {
            let (u, quarantined) = provider.usage_with_quarantine()?;
            quarantined_connections = sum_quarantined(quarantined_connections, quarantined)?;
            usage.owners += u.owners;
            usage.connections += u.connections;
            usage.pending_operations += u.pending_operations;
            usage.retained_chunks += u.retained_chunks;
            usage.accepted_write_bytes += u.accepted_write_bytes;
            #[cfg(any(test, feature = "development-outbound"))]
            {
                usage.input_budget_bytes += u.input_budget_bytes;
            }
            #[cfg(feature = "development-read-witness")]
            {
                usage.read_admissions = usage
                    .read_admissions
                    .saturating_add(u.read_admissions)
                    .min(3);
                usage.pending_reads = usage.pending_reads.saturating_add(u.pending_reads).min(2);
                usage.retired_read_delivered_bytes = usage
                    .retired_read_delivered_bytes
                    .saturating_add(u.retired_read_delivered_bytes);
            }
            usage.delivered_read_bytes += u.delivered_read_bytes;
        }
        let current_generation_retired = current.inner.installed.is_retired();
        let state = self.state.try_lock().map_err(crate::snapshot_lock_error)?;
        let same_retired =
            state
                .retired
                .iter()
                .zip(&retired)
                .all(|(now, snapshot)| match (now, snapshot) {
                    (None, None) => true,
                    (Some(now), Some(snapshot)) => Arc::ptr_eq(&now.inner, &snapshot.inner),
                    _ => false,
                });
        if !Arc::ptr_eq(&state.current.inner, &current.inner)
            || state.stopped != stopped
            || !same_retired
        {
            return Err(StreamError::new(StreamErrorCode::Exhausted));
        }
        let retired_generations = retired.iter().filter(|p| p.is_some()).count();
        drop(state);
        Ok(StreamStatus {
            profile: latent_capabilities::broker::network::STREAM_PROFILE,
            configuration_digest: reference.configuration_digest().into(),
            configuration_epoch: reference.configuration_epoch(),
            retired_generations,
            quarantined_connections,
            usage,
            stopped,
            current_generation_retired,
            maintenance_owners: usize::from(self.maintenance_claimed.load(Ordering::Acquire)),
        })
    }
    pub fn retire(&self) {
        let (current, retired) = {
            let mut state = self
                .state
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            state.stopped = true;
            (state.current.clone(), state.retired.clone())
        };
        // Abort can wake arbitrary waiters; no lifecycle lock is held here.
        current.retire();
        for retired in retired.iter().flatten() {
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
                quarantined_connections: Some(status.quarantined_connections),
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
