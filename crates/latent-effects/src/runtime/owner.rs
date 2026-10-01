use std::sync::Arc;
use std::time::Instant;

use crate::authority::EffectAuthorityOwner;
use latent_state::protected_store::ProtectedStoreOwner;
use latent_state::store_io::StoreIoOwner;

use super::state::Shared;
use super::worker::Services;
use super::{
    store, DeferredEffectAdapter, DispatcherConfig, DispatcherError, DispatcherShutdown,
    DispatcherSnapshot, EffectTimeSource, RequiredProfilePage,
};

/// Retain this owner through node lifecycle. Drop closes logical admission;
/// accepted physical work remains in fixed workers and the scheduling owner.
pub struct DispatcherOwner {
    pub(super) services: Arc<Services>,
    jobs: StoreIoOwner<Arc<Services>>,
    driver: Option<tokio::task::JoinHandle<()>>,
    workers: usize,
    joined_workers: usize,
}

impl DispatcherOwner {
    pub async fn start(
        config: DispatcherConfig,
        store: Arc<ProtectedStoreOwner>,
        authority: EffectAuthorityOwner,
        adapters: Vec<Arc<dyn DeferredEffectAdapter>>,
        time: Arc<dyn EffectTimeSource>,
        minimum_checkpoint: Option<(u64, u64)>,
    ) -> Result<Self, DispatcherError> {
        let runtime = tokio::runtime::Handle::try_current()
            .map_err(|_| DispatcherError::InvalidConfiguration)?;
        Self::start_with_runtime(
            config,
            store,
            authority,
            adapters,
            time,
            minimum_checkpoint,
            runtime,
        )
        .await
    }

    pub async fn start_with_runtime(
        config: DispatcherConfig,
        store: Arc<ProtectedStoreOwner>,
        authority: EffectAuthorityOwner,
        adapters: Vec<Arc<dyn DeferredEffectAdapter>>,
        time: Arc<dyn EffectTimeSource>,
        minimum_checkpoint: Option<(u64, u64)>,
        runtime: tokio::runtime::Handle,
    ) -> Result<Self, DispatcherError> {
        config.validate()?;
        if adapters.len() > 32
            || adapters.iter().enumerate().any(|(index, adapter)| {
                let profile = adapter.profile();
                profile.intent_format == 0
                    || [
                        &profile.provider,
                        &profile.destination,
                        &profile.adapter,
                        &profile.payload_format,
                        &profile.idempotency_profile,
                    ]
                    .into_iter()
                    .any(|identity| {
                        identity.is_empty()
                            || identity.len() > 256
                            || identity.chars().any(char::is_control)
                    })
                    || adapters[..index]
                        .iter()
                        .any(|other| other.profile() == profile)
            })
        {
            return Err(DispatcherError::InvalidAdapter);
        }
        let role = store.reserve_dispatcher()?.await??;
        let startup_time = time.observe();
        let epoch = match store::startup(&store, startup_time, minimum_checkpoint).await {
            Ok(epoch) => epoch,
            Err(error) => {
                role.retire().await;
                return Err(error);
            }
        };
        let restored = match store::control_startup(&store, epoch).await {
            Ok(restored) => restored,
            Err(error) => {
                role.retire().await;
                return Err(error);
            }
        };
        let (was_paused, review) = restored.unwrap_or((false, false));
        let shared = Arc::new(Shared::new(
            config.start_paused || was_paused,
            epoch,
            config.start_in_restore_review || review,
            config.maximum_command_owners,
            startup_time.unix_millis,
        ));
        let (receipts, receiver) = tokio::sync::mpsc::channel(config.accepted_jobs);
        let services = Arc::new(Services {
            store,
            authority,
            adapters: adapters.into(),
            time,
            epoch,
            runtime: runtime.clone(),
            shared,
            receipts,
        });
        let jobs =
            match StoreIoOwner::new(Arc::clone(&services), config.worker_limits(), |_| Ok(())) {
                Ok(jobs) => jobs,
                Err(error) => {
                    if let Some(owner) = error.owner {
                        owner.close();
                    }
                    role.retire().await; // No attempt/network operation was admitted.
                    return Err(error.reason.into());
                }
            };
        let workers = config.workers;
        let driver = runtime.spawn(super::driver::drive(
            Arc::clone(&services),
            jobs.clone(),
            config,
            role,
            receiver,
        ));
        Ok(Self {
            services,
            jobs,
            driver: Some(driver),
            workers,
            joined_workers: 0,
        })
    }

    pub fn pause(&self) {
        let mut state = self
            .services
            .shared
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.paused = true;
        match state.control_generation.next() {
            Ok(next) => state.control_generation = next,
            Err(_) => {
                state.closed = true;
            }
        }
        drop(state);
        self.wake();
    }

    pub fn resume(&self) -> Result<(), DispatcherError> {
        let mut state = self
            .services
            .shared
            .state
            .lock()
            .map_err(|_| DispatcherError::AdmissionClosed)?;
        if state.closed || state.pending_control.is_some() {
            return Err(DispatcherError::AdmissionClosed);
        }
        if state.restore_review.is_required() {
            return Err(DispatcherError::CheckpointRequired);
        }
        if let Some(error) = state.failure {
            return Err(error);
        }
        if !self.services.time.observe().continuity_proven {
            return Err(crate::authority::AuthorityError::ClockDiscontinuity.into());
        }
        state.control_generation = state
            .control_generation
            .next()
            .map_err(|_| DispatcherError::InvalidConfiguration)?;
        state.paused = false;
        drop(state);
        self.wake();
        Ok(())
    }

    pub fn wake(&self) {
        self.services.shared.notify.notify_one();
    }

    pub fn close(&self) {
        self.services
            .shared
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .closed = true;
        self.jobs.close();
        self.wake();
    }

    pub fn snapshot(&self) -> Result<DispatcherSnapshot, DispatcherError> {
        Ok(self
            .services
            .shared
            .snapshot(self.jobs.snapshot()?, self.services.authority.owners()?))
    }

    pub async fn refresh_counts(&self) -> Result<DispatcherSnapshot, DispatcherError> {
        let counts = store::counts(&self.services.store).await?;
        let mut state = self
            .services
            .shared
            .state
            .lock()
            .map_err(|_| DispatcherError::AdmissionClosed)?;
        state.counts = counts;
        state.counts_time = self.services.time.observe().unix_millis;
        drop(state);
        self.snapshot()
    }

    pub async fn required_profile_page(
        &self,
        cursor: Option<Vec<u8>>,
        rows: usize,
        bytes: usize,
    ) -> Result<RequiredProfilePage, DispatcherError> {
        store::profiles(&self.services.store, cursor, rows, bytes).await
    }

    /// One absolute cutoff. Expiry retains the driver, provider jobs and root
    /// pins; later actual retirement remains distinguishable from clean drain.
    pub async fn shutdown(
        &mut self,
        deadline: Instant,
    ) -> Result<DispatcherShutdown, DispatcherError> {
        self.close();
        let report = self
            .jobs
            .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
            .map_err(DispatcherError::from)?
            .await;
        if let Some(driver) = &mut self.driver {
            match tokio::time::timeout_at(deadline.into(), driver).await {
                Ok(Ok(())) => {
                    self.driver.take();
                }
                Ok(Err(_)) => self
                    .services
                    .shared
                    .fail(latent_state::store_io::StoreIoError::RecoveryRequired.into()),
                Err(_) => {}
            }
        }
        self.joined_workers += self.jobs.reap_retired_threads()?;
        while report.snapshot.physically_retired()
            && self.joined_workers < self.workers
            && Instant::now() < deadline
        {
            tokio::task::yield_now().await;
            self.joined_workers += self.jobs.reap_retired_threads()?;
        }
        let snapshot = self.snapshot()?;
        let scheduling_owner_retired = self
            .services
            .shared
            .state
            .lock()
            .is_ok_and(|state| state.scheduling_retired);
        let physically_retired = report.snapshot.physically_retired()
            && snapshot.physical_owners == 0
            && snapshot.accepted_effects == 0
            && snapshot.command_owners == 0
            && scheduling_owner_retired
            && self.joined_workers == self.workers;
        Ok(DispatcherShutdown {
            clean: report.clean && physically_retired && !snapshot.quarantined,
            physically_retired,
            scheduling_owner_retired,
            worker_threads_joined: self.joined_workers,
            worker_threads_remaining: self.workers - self.joined_workers,
            snapshot,
        })
    }
}

impl Drop for DispatcherOwner {
    fn drop(&mut self) {
        self.close();
    }
}
