use std::sync::Arc;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use latent_activation::{ActivationEnvelope, ActivationManager, ActivationOutcome};
use latent_core::{
    ActivationId, BoxFuture, Metadata, PlatformError, PlatformErrorCode, ResourceBudget, TenantId,
};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionCleanup, ExecutionReport, ExecutionRequest,
    GuestInterruptionKind, GuestOutcome, PreparationKey, PreparedComponent,
};
use latent_scheduler::{CellClass, CellLease, CellPool, CellPoolSnapshot};
use latent_telemetry::{
    ActivationLifecycleEvent, ActivationLifecycleStage, ActivationObserver, MetricKind,
    MetricPoint, TelemetryHandle,
};

pub struct ObservedActivationManager<M> {
    inner: Arc<M>,
    observer: Arc<dyn ActivationObserver>,
}

impl<M> std::fmt::Debug for ObservedActivationManager<M> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ObservedActivationManager")
            .finish_non_exhaustive()
    }
}

impl<M> ObservedActivationManager<M> {
    #[must_use]
    pub fn new(inner: Arc<M>, observer: Arc<dyn ActivationObserver>) -> Self {
        Self { inner, observer }
    }

    #[must_use]
    pub fn inner(&self) -> &Arc<M> {
        &self.inner
    }
}

impl<M> ActivationManager for ObservedActivationManager<M>
where
    M: ActivationManager + 'static,
{
    fn invoke<'a>(&'a self, envelope: ActivationEnvelope) -> BoxFuture<'a, ActivationOutcome> {
        Box::pin(async move {
            self.observer.on_received(&envelope);
            let activation_id = envelope.activation_id.clone();
            let outcome = self.inner.invoke(envelope).await;
            self.observer.on_finalized(&activation_id, &outcome);
            outcome
        })
    }

    fn cancel<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        reason: &'a str,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            self.observer.on_cancel_requested(activation_id);
            self.inner.cancel(activation_id, reason).await
        })
    }
}

pub struct ObservedCellPool<P> {
    inner: Arc<P>,
    observer: Arc<dyn ActivationObserver>,
    telemetry: TelemetryHandle,
}

impl<P> std::fmt::Debug for ObservedCellPool<P> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ObservedCellPool")
            .field("telemetry", &self.telemetry.snapshot())
            .finish_non_exhaustive()
    }
}

impl<P> ObservedCellPool<P> {
    #[must_use]
    pub fn new(
        inner: Arc<P>,
        observer: Arc<dyn ActivationObserver>,
        telemetry: TelemetryHandle,
    ) -> Self {
        Self {
            inner,
            observer,
            telemetry,
        }
    }

    #[must_use]
    pub fn inner(&self) -> &Arc<P> {
        &self.inner
    }

    fn emit_pool_snapshot(&self, class: CellClass, observed_at: u64) {
        let snapshot = self.inner_snapshot(class);
        let attributes =
            Metadata::from([("cell_class".to_owned(), cell_class_name(class).to_owned())]);
        for (name, value) in [
            ("latent.cell.capacity", snapshot.capacity),
            ("latent.cell.available", snapshot.available),
            ("latent.cell.active", snapshot.active_leases),
            ("latent.cell.quarantined", snapshot.quarantined),
            ("latent.scheduler.queue.depth", snapshot.queue_depth),
        ] {
            emit_metric(
                &self.telemetry,
                name,
                MetricKind::Gauge,
                f64::from(value),
                "1",
                attributes.clone(),
                observed_at,
            );
        }
    }
}

impl<P> ObservedCellPool<P>
where
    P: CellPool,
{
    fn inner_snapshot(&self, class: CellClass) -> CellPoolSnapshot {
        self.inner.observations(class)
    }
}

impl<P> CellPool for ObservedCellPool<P>
where
    P: CellPool + 'static,
{
    fn acquire<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>> {
        Box::pin(async move {
            let started = Instant::now();
            let observed_at = now_unix_millis();
            self.observer.on_lifecycle(&ActivationLifecycleEvent {
                activation_id: activation_id.clone(),
                stage: ActivationLifecycleStage::Queueing,
                occurred_at_unix_millis: observed_at,
                duration_micros: None,
                attributes: Metadata::from([(
                    "cell_class".to_owned(),
                    cell_class_name(class).to_owned(),
                )]),
            });
            self.emit_pool_snapshot(class, observed_at);
            let result = self
                .inner
                .acquire(activation_id, tenant, class, budget)
                .await;
            let completed_at = now_unix_millis();
            let duration = elapsed_micros(started);
            let result_name = if result.is_ok() {
                "granted"
            } else {
                "rejected"
            };
            self.observer.on_lifecycle(&ActivationLifecycleEvent {
                activation_id: activation_id.clone(),
                stage: ActivationLifecycleStage::Queueing,
                occurred_at_unix_millis: completed_at,
                duration_micros: Some(duration),
                attributes: Metadata::from([
                    ("cell_class".to_owned(), cell_class_name(class).to_owned()),
                    ("result".to_owned(), result_name.to_owned()),
                ]),
            });
            emit_metric(
                &self.telemetry,
                "latent.scheduler.queue.wait",
                MetricKind::Histogram,
                duration as f64,
                "us",
                Metadata::from([
                    ("cell_class".to_owned(), cell_class_name(class).to_owned()),
                    ("result".to_owned(), result_name.to_owned()),
                ]),
                completed_at,
            );
            if let Ok(lease) = &result {
                emit_budget_grant(&self.telemetry, &lease.granted_budget, completed_at);
            }
            self.emit_pool_snapshot(class, completed_at);
            result
        })
    }

    fn release<'a>(&'a self, lease: CellLease) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let activation_id = lease.activation_id.clone();
            let class = lease.class;
            let started = Instant::now();
            let result = self.inner.release(lease).await;
            let observed_at = now_unix_millis();
            self.observer.on_lifecycle(&ActivationLifecycleEvent {
                activation_id,
                stage: ActivationLifecycleStage::Cleanup,
                occurred_at_unix_millis: observed_at,
                duration_micros: Some(elapsed_micros(started)),
                attributes: Metadata::from([
                    ("cleanup".to_owned(), "release".to_owned()),
                    (
                        "result".to_owned(),
                        if result.is_ok() { "ok" } else { "failed" }.to_owned(),
                    ),
                ]),
            });
            emit_metric(
                &self.telemetry,
                "latent.cell.releases",
                MetricKind::Counter,
                1.0,
                "1",
                Metadata::from([(
                    "result".to_owned(),
                    if result.is_ok() { "ok" } else { "failed" }.to_owned(),
                )]),
                observed_at,
            );
            self.emit_pool_snapshot(class, observed_at);
            result
        })
    }

    fn capacity(&self, class: CellClass) -> u32 {
        self.inner.capacity(class)
    }

    fn available(&self, class: CellClass) -> u32 {
        self.inner.available(class)
    }

    fn cancel_waiting<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let result = self.inner.cancel_waiting(activation_id).await;
            emit_metric(
                &self.telemetry,
                "latent.scheduler.queue.cancellations",
                MetricKind::Counter,
                1.0,
                "1",
                Metadata::from([(
                    "result".to_owned(),
                    if result.is_ok() { "ok" } else { "failed" }.to_owned(),
                )]),
                now_unix_millis(),
            );
            result
        })
    }

    fn quarantine<'a>(
        &'a self,
        lease: CellLease,
        reason: String,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let activation_id = lease.activation_id.clone();
            let class = lease.class;
            let started = Instant::now();
            let result = self.inner.quarantine(lease, reason).await;
            let observed_at = now_unix_millis();
            self.observer.on_lifecycle(&ActivationLifecycleEvent {
                activation_id,
                stage: ActivationLifecycleStage::Cleanup,
                occurred_at_unix_millis: observed_at,
                duration_micros: Some(elapsed_micros(started)),
                attributes: Metadata::from([
                    ("cleanup".to_owned(), "quarantine".to_owned()),
                    (
                        "result".to_owned(),
                        if result.is_ok() { "ok" } else { "failed" }.to_owned(),
                    ),
                ]),
            });
            emit_metric(
                &self.telemetry,
                "latent.cell.quarantines",
                MetricKind::Counter,
                1.0,
                "1",
                Metadata::from([(
                    "result".to_owned(),
                    if result.is_ok() { "ok" } else { "failed" }.to_owned(),
                )]),
                observed_at,
            );
            self.emit_pool_snapshot(class, observed_at);
            result
        })
    }

    fn observations(&self, class: CellClass) -> CellPoolSnapshot {
        self.inner.observations(class)
    }
}

pub struct ObservedExecutionBackend<B> {
    inner: Arc<B>,
    observer: Arc<dyn ActivationObserver>,
    telemetry: TelemetryHandle,
}

impl<B> std::fmt::Debug for ObservedExecutionBackend<B> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ObservedExecutionBackend")
            .field("telemetry", &self.telemetry.snapshot())
            .finish_non_exhaustive()
    }
}

impl<B> ObservedExecutionBackend<B> {
    #[must_use]
    pub fn new(
        inner: Arc<B>,
        observer: Arc<dyn ActivationObserver>,
        telemetry: TelemetryHandle,
    ) -> Self {
        Self {
            inner,
            observer,
            telemetry,
        }
    }

    #[must_use]
    pub fn inner(&self) -> &Arc<B> {
        &self.inner
    }

    fn observe_execution(
        &self,
        activation_id: &ActivationId,
        started: Instant,
        outcome: &Result<GuestOutcome, PlatformError>,
    ) {
        let observed_at = now_unix_millis();
        let result = execution_result_name(outcome);
        self.observer.on_lifecycle(&ActivationLifecycleEvent {
            activation_id: activation_id.clone(),
            stage: ActivationLifecycleStage::Execution,
            occurred_at_unix_millis: observed_at,
            duration_micros: Some(elapsed_micros(started)),
            attributes: Metadata::from([("result".to_owned(), result.to_owned())]),
        });
        emit_metric(
            &self.telemetry,
            "latent.execution.outcomes",
            MetricKind::Counter,
            1.0,
            "1",
            Metadata::from([("result".to_owned(), result.to_owned())]),
            observed_at,
        );
        match outcome {
            Ok(GuestOutcome::Trapped { .. }) => emit_metric(
                &self.telemetry,
                "latent.execution.traps",
                MetricKind::Counter,
                1.0,
                "1",
                Metadata::new(),
                observed_at,
            ),
            Ok(GuestOutcome::Interrupted { kind, .. }) => emit_metric(
                &self.telemetry,
                "latent.execution.interruptions",
                MetricKind::Counter,
                1.0,
                "1",
                Metadata::from([("kind".to_owned(), interruption_name(*kind).to_owned())]),
                observed_at,
            ),
            Err(error) => emit_metric(
                &self.telemetry,
                "latent.platform.errors",
                MetricKind::Counter,
                1.0,
                "1",
                Metadata::from([(
                    "error_code".to_owned(),
                    platform_error_name(error.code).to_owned(),
                )]),
                observed_at,
            ),
            Ok(GuestOutcome::Returned { .. }) => {}
        }
    }
}

impl<B> ExecutionBackend for ObservedExecutionBackend<B>
where
    B: ExecutionBackend + 'static,
{
    fn backend_id(&self) -> &str {
        self.inner.backend_id()
    }

    fn prepare<'a>(
        &'a self,
        artifact: &'a latent_artifacts::CapsuleArtifact,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        Box::pin(async move {
            let result = self.inner.prepare(artifact, key).await;
            emit_metric(
                &self.telemetry,
                "latent.cache.operations",
                MetricKind::Counter,
                1.0,
                "1",
                Metadata::from([
                    ("operation".to_owned(), "prepare".to_owned()),
                    (
                        "result".to_owned(),
                        if result.is_ok() { "ok" } else { "failed" }.to_owned(),
                    ),
                ]),
                now_unix_millis(),
            );
            result
        })
    }

    fn invoke<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        Box::pin(async move {
            let activation_id = request.activation.activation_id.clone();
            let started = Instant::now();
            let result = self.inner.invoke(request, cancellation).await;
            self.observe_execution(&activation_id, started, &result);
            result
        })
    }

    fn invoke_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move {
            let activation_id = request.activation.activation_id.clone();
            let started = Instant::now();
            let report = self.inner.invoke_contained(request, cancellation).await;
            self.observe_execution(&activation_id, started, &report.outcome);
            let observed_at = now_unix_millis();
            let disposition = match &report.cleanup {
                ExecutionCleanup::Reusable => "reusable",
                ExecutionCleanup::Quarantine { .. } => "quarantine",
            };
            self.observer.on_lifecycle(&ActivationLifecycleEvent {
                activation_id,
                stage: ActivationLifecycleStage::Cleanup,
                occurred_at_unix_millis: observed_at,
                duration_micros: None,
                attributes: Metadata::from([("cleanup".to_owned(), disposition.to_owned())]),
            });
            emit_metric(
                &self.telemetry,
                "latent.execution.cleanup",
                MetricKind::Counter,
                1.0,
                "1",
                Metadata::from([("disposition".to_owned(), disposition.to_owned())]),
                observed_at,
            );
            report
        })
    }

    fn release<'a>(
        &'a self,
        prepared: PreparedComponent,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let result = self.inner.release(prepared).await;
            emit_metric(
                &self.telemetry,
                "latent.cache.operations",
                MetricKind::Counter,
                1.0,
                "1",
                Metadata::from([
                    ("operation".to_owned(), "release".to_owned()),
                    (
                        "result".to_owned(),
                        if result.is_ok() { "ok" } else { "failed" }.to_owned(),
                    ),
                ]),
                now_unix_millis(),
            );
            result
        })
    }
}

fn emit_metric(
    telemetry: &TelemetryHandle,
    name: &str,
    kind: MetricKind,
    value: f64,
    unit: &str,
    attributes: Metadata,
    observed_at_unix_millis: u64,
) {
    let _ = telemetry.try_emit_metric(MetricPoint {
        name: name.to_owned(),
        kind,
        value,
        unit: unit.to_owned(),
        attributes,
        observed_at_unix_millis,
    });
}

fn emit_budget_grant(telemetry: &TelemetryHandle, budget: &ResourceBudget, observed_at: u64) {
    for (resource, value) in [
        ("cpu_fuel", budget.cpu_fuel as f64),
        ("memory_bytes", budget.memory_bytes as f64),
        ("log_bytes", budget.log_bytes as f64),
    ] {
        emit_metric(
            telemetry,
            "latent.activation.budget.granted",
            MetricKind::Histogram,
            value,
            "1",
            Metadata::from([("resource".to_owned(), resource.to_owned())]),
            observed_at,
        );
    }
}

fn execution_result_name(result: &Result<GuestOutcome, PlatformError>) -> &'static str {
    match result {
        Ok(GuestOutcome::Returned { .. }) => "returned",
        Ok(GuestOutcome::Trapped { .. }) => "trapped",
        Ok(GuestOutcome::Interrupted { kind, .. }) => interruption_name(*kind),
        Err(_) => "platform_error",
    }
}

fn interruption_name(kind: GuestInterruptionKind) -> &'static str {
    match kind {
        GuestInterruptionKind::Cancelled => "cancelled",
        GuestInterruptionKind::DeadlineExceeded => "deadline_exceeded",
        GuestInterruptionKind::FuelExhausted => "fuel_exhausted",
        GuestInterruptionKind::MemoryExhausted => "memory_exhausted",
    }
}

fn platform_error_name(code: PlatformErrorCode) -> &'static str {
    match code {
        PlatformErrorCode::Unavailable => "unavailable",
        PlatformErrorCode::DeadlineExceeded => "deadline_exceeded",
        PlatformErrorCode::Cancelled => "cancelled",
        PlatformErrorCode::ResourceExhausted => "resource_exhausted",
        PlatformErrorCode::PermissionDenied => "permission_denied",
        PlatformErrorCode::Unauthenticated => "unauthenticated",
        PlatformErrorCode::InvalidArgument => "invalid_argument",
        PlatformErrorCode::NotFound => "not_found",
        PlatformErrorCode::AlreadyExists => "already_exists",
        PlatformErrorCode::IncompatibleContract => "incompatible_contract",
        PlatformErrorCode::StateConflict => "state_conflict",
        PlatformErrorCode::DependencyFailed => "dependency_failed",
        PlatformErrorCode::GuestTrap => "guest_trap",
        PlatformErrorCode::CorruptArtifact => "corrupt_artifact",
        PlatformErrorCode::RouteUnavailable => "route_unavailable",
        PlatformErrorCode::AdmissionRejected => "admission_rejected",
        PlatformErrorCode::Internal => "internal",
        _ => "unknown",
    }
}

fn cell_class_name(class: CellClass) -> &'static str {
    match class {
        CellClass::Tiny => "tiny",
        CellClass::Small => "small",
        CellClass::Standard => "standard",
        CellClass::Large => "large",
        CellClass::ExtraLarge => "extra-large",
    }
}

fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

fn now_unix_millis() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    u64::try_from(millis).unwrap_or(u64::MAX)
}
