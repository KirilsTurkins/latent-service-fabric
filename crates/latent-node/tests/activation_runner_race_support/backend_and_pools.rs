use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use latent_activation::{ActivationEnvelope, ActivationManager, ActivationOutcome, TraceContext};
use latent_artifacts::CapsuleArtifact;
use latent_core::{
    ActivationId, ActivationTerminalState, BoxFuture, BudgetConsumption, CapabilityId, CellId,
    ContractId, FunctionId, InvocationPrincipal, Metadata, NodeId, PlatformError,
    PlatformErrorCode, PrincipalKind, ReleaseDigest, ResourceBudget, ServiceId, SpanId, TenantId,
    TraceId,
};
use latent_executor::{
    BoundImport, ExecutionBackend, ExecutionCancellation, ExecutionReport, ExecutionRequest,
    GuestOutcome, GuestTrap, PreparationKey, PreparedComponent,
};
use latent_node::{Phase0ActivationRunner, Phase0ActivationRunnerConfig};
use latent_routing::InvocationTarget;
use latent_scheduler::{CellClass, CellLease, CellLeaseLifecycle, CellPool};
use tokio::sync::Barrier;

const BACKEND_ID: &str = "runner-race-test";
const TEST_TIMEOUT: Duration = Duration::from_secs(5);

#[derive(Clone)]
struct Gate {
    entered: Arc<Barrier>,
    proceed: Arc<Barrier>,
}

impl Gate {
    fn new() -> Self {
        Self {
            entered: Arc::new(Barrier::new(2)),
            proceed: Arc::new(Barrier::new(2)),
        }
    }

    async fn block(&self) {
        self.entered.wait().await;
        self.proceed.wait().await;
    }

    async fn entered(&self, label: &str) {
        rendezvous(&self.entered, label).await;
    }

    async fn proceed(&self, label: &str) {
        rendezvous(&self.proceed, label).await;
    }
}

struct Backend {
    report: ExecutionReport,
    gate: Gate,
}

impl Backend {
    fn new(report: ExecutionReport) -> (Arc<Self>, Gate) {
        let gate = Gate::new();
        (
            Arc::new(Self {
                report,
                gate: gate.clone(),
            }),
            gate,
        )
    }
}

impl ExecutionBackend for Backend {
    fn backend_id(&self) -> &str {
        BACKEND_ID
    }

    fn prepare<'a>(
        &'a self,
        _artifact: &'a CapsuleArtifact,
        _key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        Box::pin(async { Err(test_error("test backend does not prepare artifacts")) })
    }

    fn invoke<'a>(
        &'a self,
        _request: ExecutionRequest,
        _cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        Box::pin(async move {
            self.gate.block().await;
            self.report.clone().outcome
        })
    }

    fn invoke_contained<'a>(
        &'a self,
        _request: ExecutionRequest,
        _cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move {
            self.gate.block().await;
            self.report.clone()
        })
    }

    fn release<'a>(
        &'a self,
        _prepared: PreparedComponent,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async { Ok(()) })
    }
}

#[derive(Default)]
struct Lifecycle {
    abandoned: AtomicU64,
}

impl CellLeaseLifecycle for Lifecycle {
    fn on_abandoned(&self) {
        self.abandoned.fetch_add(1, Ordering::AcqRel);
    }
}

#[derive(Clone)]
enum Disposition {
    Immediate,
    Release { gate: Gate, fail: bool },
    Quarantine { gate: Gate, fail: bool },
}

struct Pool {
    lifecycle: Arc<Lifecycle>,
    disposition: Disposition,
    cancel_calls: AtomicU64,
}

impl Pool {
    fn immediate() -> Arc<Self> {
        Arc::new(Self::new(Disposition::Immediate))
    }

    fn release(fail: bool) -> (Arc<Self>, Gate) {
        let gate = Gate::new();
        (
            Arc::new(Self::new(Disposition::Release {
                gate: gate.clone(),
                fail,
            })),
            gate,
        )
    }

    fn quarantine(fail: bool) -> (Arc<Self>, Gate) {
        let gate = Gate::new();
        (
            Arc::new(Self::new(Disposition::Quarantine {
                gate: gate.clone(),
                fail,
            })),
            gate,
        )
    }

    fn new(disposition: Disposition) -> Self {
        Self {
            lifecycle: Arc::new(Lifecycle::default()),
            disposition,
            cancel_calls: AtomicU64::new(0),
        }
    }

    fn disarm(&self, lease: &mut CellLease) {
        let lifecycle: Arc<dyn CellLeaseLifecycle> = self.lifecycle.clone();
        assert!(lease.disarm_lifecycle(&lifecycle));
    }

    fn abandoned(&self) -> u64 {
        self.lifecycle.abandoned.load(Ordering::Acquire)
    }
}

impl CellPool for Pool {
    fn acquire<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        _tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>> {
        let lease = lease(
            activation_id.clone(),
            class,
            budget.clone(),
            self.lifecycle.clone(),
        );
        Box::pin(async move { Ok(lease) })
    }

    fn release<'a>(
        &'a self,
        mut lease: CellLease,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            if let Disposition::Release { gate, fail } = &self.disposition {
                gate.block().await;
                if *fail {
                    return Err(test_error("controlled release failure"));
                }
            }
            self.disarm(&mut lease);
            Ok(())
        })
    }

    fn capacity(&self, _class: CellClass) -> u32 {
        1
    }

    fn available(&self, _class: CellClass) -> u32 {
        1
    }

    fn cancel_waiting<'a>(
        &'a self,
        _activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        self.cancel_calls.fetch_add(1, Ordering::AcqRel);
        Box::pin(async { Ok(()) })
    }

    fn quarantine<'a>(
        &'a self,
        mut lease: CellLease,
        _reason: String,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            if let Disposition::Quarantine { gate, fail } = &self.disposition {
                gate.block().await;
                if *fail {
                    return Err(test_error("controlled quarantine failure"));
                }
            }
            self.disarm(&mut lease);
            Ok(())
        })
    }
}

struct QueuePool {
    lifecycle: Arc<Lifecycle>,
    grant: Gate,
    grant_on_cancel: bool,
    cancel_calls: AtomicU64,
}

impl QueuePool {
    fn new(grant_on_cancel: bool) -> (Arc<Self>, Gate) {
        let grant = Gate::new();
        (
            Arc::new(Self {
                lifecycle: Arc::new(Lifecycle::default()),
                grant: grant.clone(),
                grant_on_cancel,
                cancel_calls: AtomicU64::new(0),
            }),
            grant,
        )
    }
}

impl CellPool for QueuePool {
    fn acquire<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        _tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>> {
        let activation_id = activation_id.clone();
        let budget = budget.clone();
        let lifecycle = self.lifecycle.clone();
        Box::pin(async move {
            self.grant.block().await;
            Ok(lease(activation_id, class, budget, lifecycle))
        })
    }

    fn release<'a>(
        &'a self,
        mut lease: CellLease,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let lifecycle: Arc<dyn CellLeaseLifecycle> = self.lifecycle.clone();
            assert!(lease.disarm_lifecycle(&lifecycle));
            Ok(())
        })
    }

    fn capacity(&self, _class: CellClass) -> u32 {
        1
    }

    fn available(&self, _class: CellClass) -> u32 {
        1
    }

    fn cancel_waiting<'a>(
        &'a self,
        _activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        let call = self.cancel_calls.fetch_add(1, Ordering::AcqRel);
        Box::pin(async move {
            if self.grant_on_cancel && call == 0 {
                self.grant.proceed.wait().await;
            }
            Ok(())
        })
    }

    fn quarantine<'a>(
        &'a self,
        lease: CellLease,
        _reason: String,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        self.release(lease)
    }
}
