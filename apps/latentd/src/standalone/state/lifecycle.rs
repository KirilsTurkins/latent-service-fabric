use super::StateRuntime;
use latent_core::PlatformError;
use serde::Serialize;
use std::time::Instant;

/// Actual protected engine and native capacity observations after teardown.
#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StateShutdownReport {
    pub clean: bool,
    pub ordinary_reservations: usize,
    pub ordinary_bytes: u64,
    pub recovery_reservations: usize,
    pub recovery_bytes: u64,
    pub native_quarantined: bool,
    pub store_accepted_jobs: usize,
    pub store_retained_bytes: u64,
    pub store_physical_owners: usize,
    pub store_queued_retirements: usize,
    pub store_live_workers: usize,
    pub store_engine: StoreEngineState,
    pub store_quarantined: bool,
    pub store_threads_joined: usize,
}

#[derive(Debug, Clone, Copy, Serialize)]
#[serde(rename_all = "camelCase")]
pub enum StoreEngineState {
    Owned,
    Finalizing,
    Closed,
}

impl StateRuntime {
    pub(crate) fn close_ordinary(&self) {
        self.0.native.close_ordinary();
    }

    pub(crate) async fn shutdown(
        &self,
        deadline: Instant,
    ) -> Result<StateShutdownReport, PlatformError> {
        self.0.native.close();
        let native = self
            .0
            .native
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .map_err(|_| super::unavailable())?
            .await;
        if !native.clean {
            self.0.store.quarantine();
        }
        let store = self
            .0
            .store
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .map_err(|_| super::unavailable())?
            .await;
        let store_threads_joined = self
            .0
            .store
            .reap_retired_threads()
            .map_err(|_| super::unavailable())?;
        Ok(StateShutdownReport {
            clean: native.clean
                && store.clean
                && native.snapshot.physically_retired()
                && store.snapshot.physically_retired(),
            ordinary_reservations: native.snapshot.ordinary.slots,
            ordinary_bytes: native.snapshot.ordinary.bytes,
            recovery_reservations: native.snapshot.recovery.slots,
            recovery_bytes: native.snapshot.recovery.bytes,
            native_quarantined: native.snapshot.quarantined,
            store_accepted_jobs: store.snapshot.accepted,
            store_retained_bytes: store.snapshot.retained_bytes,
            store_physical_owners: store.snapshot.physical_owners,
            store_queued_retirements: store.snapshot.queued_retirements,
            store_live_workers: store.snapshot.live_workers,
            store_engine: match store.snapshot.engine_phase {
                latent_state::store_io::StoreIoEnginePhase::Owned => StoreEngineState::Owned,
                latent_state::store_io::StoreIoEnginePhase::Finalizing => {
                    StoreEngineState::Finalizing
                }
                latent_state::store_io::StoreIoEnginePhase::Closed => StoreEngineState::Closed,
            },
            store_quarantined: store.snapshot.quarantined,
            store_threads_joined,
        })
    }
}
