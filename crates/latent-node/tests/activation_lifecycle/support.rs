use std::collections::BTreeMap;
use std::future::{poll_fn, Future};
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::task::Poll;
use std::time::{Duration, Instant};

use latent_activation::{ActivationIdSource, ActivationRequestLimits, ActivationStatus};
use latent_admission::{
    LocalAdmissionController, LocalQuotaProvider, NodeLoadSnapshot, NodeLoadState,
};
use latent_core::{
    ActivationClock, ActivationId, ClockSample, NodeId, PlatformError, PlatformErrorCode, TenantId,
};
use latent_node::{
    ActivationHandle, ActivationReceipt, LocalActivationDependencies, LocalActivationJournalConfig,
    LocalActivationManager, LocalActivationManagerConfig, LocalActivationServices,
};
use latent_scheduler::{CellClass, LocalScheduler, LocalSchedulerConfig};
use tokio::sync::Notify;

use super::backend::Backend;
use super::catalog::{Artifacts, CatalogSource};
use super::model::{self, TENANT};

pub struct Gate {
    open: AtomicBool,
    changed: Notify,
}

impl Gate {
    pub fn new(open: bool) -> Self {
        Self {
            open: AtomicBool::new(open),
            changed: Notify::new(),
        }
    }
    pub fn close(&self) {
        self.open.store(false, Ordering::Release);
    }
    pub fn open(&self) {
        self.open.store(true, Ordering::Release);
        self.changed.notify_waiters();
    }
    pub async fn wait(&self) {
        loop {
            let changed = self.changed.notified();
            tokio::pin!(changed);
            changed.as_mut().enable();
            if self.open.load(Ordering::Acquire) {
                return;
            }
            changed.await;
        }
    }
}

pub struct LiveGuard(Arc<AtomicUsize>);

impl LiveGuard {
    pub fn new(counter: &Arc<AtomicUsize>) -> Self {
        counter.fetch_add(1, Ordering::Relaxed);
        Self(Arc::clone(counter))
    }
}

impl Drop for LiveGuard {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::Relaxed);
    }
}

pub struct Clock(Mutex<ClockSample>);

impl Clock {
    pub fn advance(&self, duration: Duration) {
        let mut sample = self.0.lock().expect("clock");
        *sample = ClockSample::new(
            sample.unix_millis() + u64::try_from(duration.as_millis()).expect("small duration"),
            sample.monotonic() + duration,
        );
    }
}

impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        *self.0.lock().expect("clock")
    }
    fn monotonic_now(&self) -> Instant {
        self.sample().monotonic()
    }
}

#[derive(Default)]
pub struct Ids(pub AtomicUsize);

impl ActivationIdSource for Ids {
    fn next_id(&self) -> Result<ActivationId, PlatformError> {
        Ok(ActivationId(format!(
            "generated-{}",
            self.0.fetch_add(1, Ordering::Relaxed) + 1
        )))
    }
}

pub struct Harness {
    pub manager: LocalActivationManager,
    pub backend: Arc<Backend>,
    pub artifacts: Arc<Artifacts>,
    pub catalog: Arc<CatalogSource>,
    pub scheduler: Arc<LocalScheduler>,
    pub quotas: LocalQuotaProvider,
    pub clock: Arc<Clock>,
    pub ids: Arc<Ids>,
}

impl Harness {
    pub fn new(parallelism: u32, maximum_terminal: usize) -> Self {
        Self::with_observer(parallelism, maximum_terminal, None)
    }

    pub fn with_observer(
        parallelism: u32,
        maximum_terminal: usize,
        observer: Option<Arc<dyn latent_telemetry::ActivationObserver>>,
    ) -> Self {
        let clock = Arc::new(Clock(Mutex::new(ClockSample::system_now())));
        let ids = Arc::new(Ids::default());
        let catalog = Arc::new(CatalogSource::default());
        let artifacts = Arc::new(Artifacts::default());
        let backend = Arc::new(Backend::default());
        let quotas = LocalQuotaProvider::new(model::node_policy(parallelism)).expect("quotas");
        let load = Arc::new(
            NodeLoadState::new(NodeLoadSnapshot {
                accepting: true,
                cpu_pressure_milli: 0,
                memory_pressure_milli: 0,
                queue_delay_millis: 0,
                observed_at: clock.monotonic_now(),
            })
            .expect("load"),
        );
        let admission = LocalAdmissionController::new(catalog.clone(), quotas.clone(), load);
        let scheduler = Arc::new(
            LocalScheduler::new(
                LocalSchedulerConfig {
                    node: NodeId("lifecycle-node".to_owned()),
                    queue_capacity_per_class: BTreeMap::from([(CellClass::Tiny, 8)]),
                    starvation_after: Duration::from_secs(1),
                },
                quotas.clone(),
            )
            .expect("scheduler"),
        );
        let manager = LocalActivationManager::with_services(
            LocalActivationManagerConfig {
                requests: ActivationRequestLimits::default(),
                journal: LocalActivationJournalConfig {
                    maximum_active: 8,
                    maximum_terminal,
                    maximum_record_bytes: 16 * 1024,
                    maximum_retained_bytes: 1024 * 1024,
                    terminal_retention: Duration::from_mins(1),
                },
                maximum_cancellation_reason_bytes: 128,
                ..LocalActivationManagerConfig::default()
            },
            LocalActivationDependencies {
                catalog: catalog.clone(),
                admission,
                scheduler: scheduler.clone(),
                artifacts: artifacts.clone(),
                backend: backend.clone(),
            },
            LocalActivationServices {
                clock: clock.clone(),
                ids: ids.clone(),
                observer,
            },
        )
        .expect("manager");
        Self {
            manager,
            backend,
            artifacts,
            catalog,
            scheduler,
            quotas,
            clock,
            ids,
        }
    }

    pub fn standard() -> Self {
        Self::new(1, 8)
    }

    pub fn status(&self, id: &str) -> ActivationStatus {
        self.manager
            .status(&tenant(), &ActivationId(id.to_owned()))
            .expect("status")
            .expect("retained status")
    }

    pub fn assert_idle(&self) {
        let pool = self.scheduler.observations(CellClass::Tiny);
        assert_eq!(pool.active_leases, 0);
        assert_eq!(pool.queue_depth, 0);
        let quota = self.quotas.snapshot_now(&tenant()).expect("quota snapshot");
        assert_eq!(quota.active_activations, 0);
        assert_eq!(quota.queued_activations, 0);
        assert_eq!(self.manager.cancellation_snapshot().active_registrations, 0);
        assert_eq!(self.manager.journal().snapshot().active, 0);
        assert_eq!(self.artifacts.live.load(Ordering::Relaxed), 0);
        assert_eq!(self.backend.live_calls.load(Ordering::Relaxed), 0);
        assert_eq!(self.backend.live_prepared.load(Ordering::Relaxed), 0);
        assert_eq!(self.catalog.global_policy_reads.load(Ordering::Relaxed), 0);
    }
}

pub fn tenant() -> TenantId {
    TenantId(TENANT.to_owned())
}

pub fn error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

pub async fn pending(handle: Pin<&mut ActivationHandle>) {
    let mut handle = handle;
    let state = poll_fn(|context| Poll::Ready(handle.as_mut().poll(context))).await;
    assert!(state.is_pending(), "controlled phase must remain pending");
}

pub async fn finish(handle: impl Future<Output = ActivationReceipt>) -> ActivationReceipt {
    tokio::time::timeout(Duration::from_secs(5), handle)
        .await
        .expect("lifecycle watchdog")
}
