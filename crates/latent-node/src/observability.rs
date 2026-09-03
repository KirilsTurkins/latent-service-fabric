#![allow(clippy::cast_precision_loss, clippy::too_many_lines)]

use std::sync::Arc;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use latent_activation::{ActivationEnvelope, ActivationManager, ActivationOutcome};
use latent_core::{
    ActivationId, ActivationTerminalState, BoxFuture, BudgetConsumption, CancelDisposition,
    Metadata, PlatformError, PlatformErrorCode, ResourceBudget, TenantId,
};
use latent_executor::{
    ExecutionBackend, ExecutionCancellation, ExecutionCleanup, ExecutionReport, ExecutionRequest,
    GuestInterruptionKind, GuestOutcome, PreparationKey, PreparedComponent,
};
use latent_scheduler::{CellClass, CellLease, CellPool, CellPoolSnapshot};
use latent_telemetry::{
    ActivationLifecycleEvent, ActivationLifecycleStage, ActivationObserver, GuestLogObserver,
    GuestLogRecord, MetricKind, MetricPoint, TelemetryHandle,
};

/// Bounded source used to bridge a runtime-owned guest log buffer into the
/// node-shared observer before terminal correlation is removed.
pub trait GuestLogSource: Send + Sync {
    fn snapshot_for(&self, activation_id: &ActivationId) -> Vec<GuestLogRecord>;
}

pub struct ObservedActivationManager<M> {
    inner: Arc<M>,
    observer: Arc<dyn ActivationObserver>,
    guest_log_observer: Option<Arc<dyn GuestLogObserver>>,
    guest_logs: Option<Arc<dyn GuestLogSource>>,
}

impl<M> std::fmt::Debug for ObservedActivationManager<M> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("ObservedActivationManager")
            .field("guest_log_forwarding", &self.guest_logs.is_some())
            .finish_non_exhaustive()
    }
}

impl<M> ObservedActivationManager<M> {
    #[must_use]
    pub fn new(inner: Arc<M>, observer: Arc<dyn ActivationObserver>) -> Self {
        Self {
            inner,
            observer,
            guest_log_observer: None,
            guest_logs: None,
        }
    }

    #[must_use]
    pub fn with_guest_logs(
        inner: Arc<M>,
        observer: Arc<dyn ActivationObserver>,
        guest_log_observer: Arc<dyn GuestLogObserver>,
        guest_logs: Arc<dyn GuestLogSource>,
    ) -> Self {
        Self {
            inner,
            observer,
            guest_log_observer: Some(guest_log_observer),
            guest_logs: Some(guest_logs),
        }
    }

    #[must_use]
    pub fn inner(&self) -> &Arc<M> {
        &self.inner
    }

    fn pre_invoke_observation(&self, envelope: &ActivationEnvelope) -> Result<(), PlatformError> {
        self.observer.on_received(envelope)?;
        let observed_at = now_unix_millis();
        self.observer.on_lifecycle(&ActivationLifecycleEvent {
            activation_id: envelope.activation_id.clone(),
            stage: ActivationLifecycleStage::Resolution,
            occurred_at_unix_millis: observed_at,
            duration_micros: None,
            attributes: Metadata::from([(
                "resolution".to_owned(),
                if envelope.resolved_revision.is_some() {
                    "resolved_revision"
                } else {
                    "phase0_prebound"
                }
                .to_owned(),
            )]),
        })?;
        self.observer.on_lifecycle(&ActivationLifecycleEvent {
            activation_id: envelope.activation_id.clone(),
            stage: ActivationLifecycleStage::Admission,
            occurred_at_unix_millis: observed_at,
            duration_micros: None,
            attributes: Metadata::from([("result".to_owned(), "ok".to_owned())]),
        })
    }

    fn forward_guest_logs(&self, activation_id: &ActivationId) -> Result<(), PlatformError> {
        let (Some(source), Some(observer)) = (&self.guest_logs, &self.guest_log_observer) else {
            return Ok(());
        };
        let mut first_error = None;
        for record in source.snapshot_for(activation_id) {
            collect_error(&mut first_error, observer.on_guest_log(record));
        }
        first_error.map_or(Ok(()), Err)
    }
}

impl<M> ActivationManager for ObservedActivationManager<M>
where
    M: ActivationManager + 'static,
{
    fn invoke<'a>(&'a self, envelope: ActivationEnvelope) -> BoxFuture<'a, ActivationOutcome> {
        Box::pin(async move {
            let activation_id = envelope.activation_id.clone();
            if let Err(error) = self.pre_invoke_observation(&envelope) {
                let mut outcome = observer_failure(error, BudgetConsumption::default());
                if let Err(finalization_error) =
                    self.observer.on_finalized(&activation_id, &outcome)
                {
                    outcome = observer_failure(finalization_error, BudgetConsumption::default());
                }
                return outcome;
            }

            let mut outcome = self.inner.invoke(envelope).await;
            if let Err(error) = self.forward_guest_logs(&activation_id) {
                outcome = observer_failure(error, outcome_consumption(&outcome).clone());
            }
            if let Err(error) = self.observer.on_finalized(&activation_id, &outcome) {
                outcome = observer_failure(error, outcome_consumption(&outcome).clone());
            }
            outcome
        })
    }

    fn cancel<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        reason: &'a str,
    ) -> BoxFuture<'a, Result<CancelDisposition, PlatformError>> {
        Box::pin(async move {
            let observer_result = self.observer.on_cancel_requested(activation_id);
            let cancellation = self.inner.cancel(activation_id, reason).await;
            observer_result.and(cancellation)
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
}

impl<P> ObservedCellPool<P>
where
    P: CellPool,
{
    fn emit_pool_snapshot(&self, class: CellClass, observed_at: u64) -> Result<(), PlatformError> {
        let snapshot = self.inner.observations(class);
        let attributes =
            Metadata::from([("cell_class".to_owned(), cell_class_name(class).to_owned())]);
        let mut first_error = None;
        for (name, value) in [
            ("latent.cell.capacity", snapshot.capacity),
            ("latent.cell.available", snapshot.available),
            ("latent.cell.active", snapshot.active_leases),
            ("latent.cell.quarantined", snapshot.quarantined),
            ("latent.scheduler.queue.depth", snapshot.queue_depth),
        ] {
            collect_error(
                &mut first_error,
                emit_metric(
                    &self.telemetry,
                    name,
                    MetricKind::Gauge,
                    f64::from(value),
                    "1",
                    attributes.clone(),
                    observed_at,
                ),
            );
        }
        first_error.map_or(Ok(()), Err)
    }

    async fn acquire_observed(
        &self,
        activation_id: &ActivationId,
        tenant: &TenantId,
        class: CellClass,
        budget: &ResourceBudget,
        deadline_unix_millis: Option<u64>,
    ) -> Result<CellLease, PlatformError> {
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
        })?;
        self.emit_pool_snapshot(class, observed_at)?;

        let result = self
            .inner
            .acquire_with_deadline(activation_id, tenant, class, budget, deadline_unix_millis)
            .await;
        let completed_at = now_unix_millis();
        let duration = elapsed_micros(started);
        let result_name = if result.is_ok() {
            "acquired"
        } else {
            "rejected"
        };
        let mut observer_error = None;
        collect_error(
            &mut observer_error,
            self.observer.on_lifecycle(&ActivationLifecycleEvent {
                activation_id: activation_id.clone(),
                stage: ActivationLifecycleStage::Queueing,
                occurred_at_unix_millis: completed_at,
                duration_micros: Some(duration),
                attributes: Metadata::from([
                    ("cell_class".to_owned(), cell_class_name(class).to_owned()),
                    ("result".to_owned(), result_name.to_owned()),
                ]),
            }),
        );
        collect_error(
            &mut observer_error,
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
            ),
        );
        if let Ok(lease) = &result {
            collect_error(
                &mut observer_error,
                emit_budget_grant(&self.telemetry, &lease.granted_budget, completed_at),
            );
        }
        collect_error(
            &mut observer_error,
            self.emit_pool_snapshot(class, completed_at),
        );

        if let Some(error) = observer_error {
            if let Ok(lease) = result {
                let _ = self.inner.release(lease).await;
            }
            Err(error)
        } else {
            result
        }
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
            self.acquire_observed(activation_id, tenant, class, budget, None)
                .await
        })
    }

    fn acquire_with_deadline<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
        deadline_unix_millis: Option<u64>,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>> {
        Box::pin(async move {
            self.acquire_observed(activation_id, tenant, class, budget, deadline_unix_millis)
                .await
        })
    }

    fn release<'a>(&'a self, lease: CellLease) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let activation_id = lease.activation_id.clone();
            let class = lease.class;
            let started = Instant::now();
            let result = self.inner.release(lease).await;
            let observed_at = now_unix_millis();
            let result_name = if result.is_ok() { "ok" } else { "failed" };
            let mut observer_error = None;
            collect_error(
                &mut observer_error,
                self.observer.on_lifecycle(&ActivationLifecycleEvent {
                    activation_id,
                    stage: ActivationLifecycleStage::Cleanup,
                    occurred_at_unix_millis: observed_at,
                    duration_micros: Some(elapsed_micros(started)),
                    attributes: Metadata::from([
                        ("cleanup".to_owned(), "release".to_owned()),
                        ("result".to_owned(), result_name.to_owned()),
                    ]),
                }),
            );
            collect_error(
                &mut observer_error,
                emit_metric(
                    &self.telemetry,
                    "latent.cell.releases",
                    MetricKind::Counter,
                    1.0,
                    "1",
                    Metadata::from([("result".to_owned(), result_name.to_owned())]),
                    observed_at,
                ),
            );
            collect_error(
                &mut observer_error,
                self.emit_pool_snapshot(class, observed_at),
            );
            observer_error.map_or(result, Err)
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
            let telemetry = emit_metric(
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
            telemetry.and(result)
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
            let result_name = if result.is_ok() { "ok" } else { "failed" };
            let mut observer_error = None;
            collect_error(
                &mut observer_error,
                self.observer.on_lifecycle(&ActivationLifecycleEvent {
                    activation_id,
                    stage: ActivationLifecycleStage::Cleanup,
                    occurred_at_unix_millis: observed_at,
                    duration_micros: Some(elapsed_micros(started)),
                    attributes: Metadata::from([
                        ("cleanup".to_owned(), "quarantine".to_owned()),
                        ("result".to_owned(), result_name.to_owned()),
                    ]),
                }),
            );
            collect_error(
                &mut observer_error,
                emit_metric(
                    &self.telemetry,
                    "latent.cell.quarantines",
                    MetricKind::Counter,
                    1.0,
                    "1",
                    Metadata::from([("result".to_owned(), result_name.to_owned())]),
                    observed_at,
                ),
            );
            collect_error(
                &mut observer_error,
                self.emit_pool_snapshot(class, observed_at),
            );
            observer_error.map_or(result, Err)
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
            let started = Instant::now();
            let result = self.inner.prepare(artifact, key).await;
            let observed_at = now_unix_millis();
            let telemetry = emit_cache_operation(
                &self.telemetry,
                "prepare",
                result.is_ok(),
                elapsed_micros(started),
                observed_at,
            );
            if let Err(error) = telemetry {
                if let Ok(prepared) = result {
                    let _ = self.inner.release(prepared).await;
                }
                Err(error)
            } else {
                result
            }
        })
    }

    fn invoke<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        Box::pin(async move {
            let activation_id = request.activation.activation_id.clone();
            self.observer.on_lifecycle(&ActivationLifecycleEvent {
                activation_id: activation_id.clone(),
                stage: ActivationLifecycleStage::Materialization,
                occurred_at_unix_millis: now_unix_millis(),
                duration_micros: None,
                attributes: Metadata::new(),
            })?;
            let started = Instant::now();
            let result = self.inner.invoke(request, cancellation).await;
            let observed_at = now_unix_millis();
            let mut observer_error = None;
            collect_error(
                &mut observer_error,
                self.observer.on_lifecycle(&ActivationLifecycleEvent {
                    activation_id,
                    stage: ActivationLifecycleStage::Execution,
                    occurred_at_unix_millis: observed_at,
                    duration_micros: Some(elapsed_micros(started)),
                    attributes: Metadata::from([(
                        "result".to_owned(),
                        execution_result_name(&result).to_owned(),
                    )]),
                }),
            );
            collect_error(
                &mut observer_error,
                emit_execution_metrics(
                    &self.telemetry,
                    &result,
                    elapsed_micros(started),
                    observed_at,
                ),
            );
            observer_error.map_or(result, Err)
        })
    }

    fn invoke_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        Box::pin(async move {
            let activation_id = request.activation.activation_id.clone();
            if let Err(error) = self.observer.on_lifecycle(&ActivationLifecycleEvent {
                activation_id: activation_id.clone(),
                stage: ActivationLifecycleStage::Materialization,
                occurred_at_unix_millis: now_unix_millis(),
                duration_micros: None,
                attributes: Metadata::new(),
            }) {
                return ExecutionReport::quarantine(
                    Err(error),
                    "strict telemetry failure before materialization",
                );
            }

            let started = Instant::now();
            let mut report = self.inner.invoke_contained(request, cancellation).await;
            let observed_at = now_unix_millis();
            let mut observer_error = None;
            collect_error(
                &mut observer_error,
                self.observer.on_lifecycle(&ActivationLifecycleEvent {
                    activation_id: activation_id.clone(),
                    stage: ActivationLifecycleStage::Execution,
                    occurred_at_unix_millis: observed_at,
                    duration_micros: Some(elapsed_micros(started)),
                    attributes: Metadata::from([(
                        "result".to_owned(),
                        execution_result_name(&report.outcome).to_owned(),
                    )]),
                }),
            );
            collect_error(
                &mut observer_error,
                emit_execution_metrics(
                    &self.telemetry,
                    &report.outcome,
                    elapsed_micros(started),
                    observed_at,
                ),
            );
            let (disposition, cleanup_reason) = match &report.cleanup {
                ExecutionCleanup::Reusable => ("reusable", "reusable"),
                ExecutionCleanup::Quarantine { .. } => ("quarantine", "quarantine"),
            };
            collect_error(
                &mut observer_error,
                self.observer.on_lifecycle(&ActivationLifecycleEvent {
                    activation_id,
                    stage: ActivationLifecycleStage::Cleanup,
                    occurred_at_unix_millis: observed_at,
                    duration_micros: None,
                    attributes: Metadata::from([
                        ("cleanup".to_owned(), cleanup_reason.to_owned()),
                        ("result".to_owned(), "ok".to_owned()),
                    ]),
                }),
            );
            collect_error(
                &mut observer_error,
                emit_metric(
                    &self.telemetry,
                    "latent.execution.cleanup",
                    MetricKind::Counter,
                    1.0,
                    "1",
                    Metadata::from([("disposition".to_owned(), disposition.to_owned())]),
                    observed_at,
                ),
            );
            if let Some(error) = observer_error {
                report.outcome = Err(error);
            }
            report
        })
    }

    fn release<'a>(
        &'a self,
        prepared: PreparedComponent,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        Box::pin(async move {
            let started = Instant::now();
            let result = self.inner.release(prepared).await;
            let telemetry = emit_cache_operation(
                &self.telemetry,
                "release",
                result.is_ok(),
                elapsed_micros(started),
                now_unix_millis(),
            );
            telemetry.and(result)
        })
    }
}

fn observer_failure(error: PlatformError, consumption: BudgetConsumption) -> ActivationOutcome {
    ActivationOutcome::Failed {
        terminal_state: ActivationTerminalState::PlatformFailed,
        error,
        consumption,
    }
}

fn outcome_consumption(outcome: &ActivationOutcome) -> &BudgetConsumption {
    match outcome {
        ActivationOutcome::Succeeded(success) => &success.consumption,
        ActivationOutcome::DeclaredError { consumption, .. }
        | ActivationOutcome::Failed { consumption, .. } => consumption,
    }
}

fn emit_execution_metrics(
    telemetry: &TelemetryHandle,
    result: &Result<GuestOutcome, PlatformError>,
    duration_micros: u64,
    observed_at: u64,
) -> Result<(), PlatformError> {
    let result_name = execution_result_name(result);
    let attributes = Metadata::from([("result".to_owned(), result_name.to_owned())]);
    let mut first_error = None;
    collect_error(
        &mut first_error,
        emit_metric(
            telemetry,
            "latent.execution.duration",
            MetricKind::Histogram,
            duration_micros as f64,
            "us",
            attributes.clone(),
            observed_at,
        ),
    );
    collect_error(
        &mut first_error,
        emit_metric(
            telemetry,
            "latent.execution.outcomes",
            MetricKind::Counter,
            1.0,
            "1",
            attributes,
            observed_at,
        ),
    );
    match result {
        Ok(GuestOutcome::Trapped { .. }) => collect_error(
            &mut first_error,
            emit_metric(
                telemetry,
                "latent.execution.traps",
                MetricKind::Counter,
                1.0,
                "1",
                Metadata::new(),
                observed_at,
            ),
        ),
        Ok(GuestOutcome::Interrupted { kind, .. }) => collect_error(
            &mut first_error,
            emit_metric(
                telemetry,
                "latent.execution.interruptions",
                MetricKind::Counter,
                1.0,
                "1",
                Metadata::from([("kind".to_owned(), interruption_name(*kind).to_owned())]),
                observed_at,
            ),
        ),
        Err(error) => collect_error(
            &mut first_error,
            emit_metric(
                telemetry,
                "latent.execution.platform_errors",
                MetricKind::Counter,
                1.0,
                "1",
                Metadata::from([(
                    "error_code".to_owned(),
                    platform_error_name(error.code).to_owned(),
                )]),
                observed_at,
            ),
        ),
        Ok(GuestOutcome::Returned { .. } | GuestOutcome::DeclaredError { .. }) => {}
    }
    first_error.map_or(Ok(()), Err)
}

fn emit_cache_operation(
    telemetry: &TelemetryHandle,
    operation: &str,
    succeeded: bool,
    duration_micros: u64,
    observed_at: u64,
) -> Result<(), PlatformError> {
    let attributes = Metadata::from([
        ("operation".to_owned(), operation.to_owned()),
        (
            "result".to_owned(),
            if succeeded { "ok" } else { "failed" }.to_owned(),
        ),
    ]);
    let mut first_error = None;
    collect_error(
        &mut first_error,
        emit_metric(
            telemetry,
            "latent.cache.operations",
            MetricKind::Counter,
            1.0,
            "1",
            attributes.clone(),
            observed_at,
        ),
    );
    collect_error(
        &mut first_error,
        emit_metric(
            telemetry,
            "latent.cache.operation.duration",
            MetricKind::Histogram,
            duration_micros as f64,
            "us",
            attributes,
            observed_at,
        ),
    );
    first_error.map_or(Ok(()), Err)
}

fn emit_metric(
    telemetry: &TelemetryHandle,
    name: &str,
    kind: MetricKind,
    value: f64,
    unit: &str,
    attributes: Metadata,
    observed_at_unix_millis: u64,
) -> Result<(), PlatformError> {
    telemetry
        .try_emit_metric(MetricPoint {
            name: name.to_owned(),
            kind,
            value,
            unit: unit.to_owned(),
            attributes,
            observed_at_unix_millis,
        })
        .map(|_| ())
}

fn emit_budget_grant(
    telemetry: &TelemetryHandle,
    budget: &ResourceBudget,
    observed_at: u64,
) -> Result<(), PlatformError> {
    let mut grants = vec![
        ("cpu_fuel", budget.cpu_fuel as f64),
        ("memory_bytes", budget.memory_bytes as f64),
        ("child_calls", f64::from(budget.child_calls)),
        ("outbound_requests", f64::from(budget.outbound_requests)),
        ("state_read_bytes", budget.state_read_bytes as f64),
        ("state_write_bytes", budget.state_write_bytes as f64),
        ("blob_read_bytes", budget.blob_read_bytes as f64),
        ("blob_write_bytes", budget.blob_write_bytes as f64),
        ("log_bytes", budget.log_bytes as f64),
        ("effect_count", f64::from(budget.effect_count)),
    ];
    if let Some(wall_time_limit_millis) = budget.wall_time_limit_millis {
        grants.push((
            "wall_time_micros",
            wall_time_limit_millis.saturating_mul(1_000) as f64,
        ));
    }
    let mut first_error = None;
    for (resource, value) in grants {
        collect_error(
            &mut first_error,
            emit_metric(
                telemetry,
                "latent.activation.budget.granted",
                MetricKind::Histogram,
                value,
                "1",
                Metadata::from([("resource".to_owned(), resource.to_owned())]),
                observed_at,
            ),
        );
    }
    first_error.map_or(Ok(()), Err)
}

fn execution_result_name(result: &Result<GuestOutcome, PlatformError>) -> &'static str {
    match result {
        Ok(GuestOutcome::Returned { .. }) => "returned",
        Ok(GuestOutcome::DeclaredError { .. }) => "declared_error",
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

fn collect_error(first_error: &mut Option<PlatformError>, result: Result<(), PlatformError>) {
    if first_error.is_none() {
        *first_error = result.err();
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

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicBool, Ordering};

    use latent_activation::{ActivationSuccess, TraceContext};
    use latent_core::{
        ContractId, FunctionId, InvocationPrincipal, PrincipalKind, ServiceId, SpanId, TraceId,
    };
    use latent_routing::InvocationTarget;

    use super::*;

    #[derive(Default)]
    struct SuccessfulManager {
        invoked: AtomicBool,
        cancelled: AtomicBool,
    }

    impl ActivationManager for SuccessfulManager {
        fn invoke<'a>(&'a self, _envelope: ActivationEnvelope) -> BoxFuture<'a, ActivationOutcome> {
            self.invoked.store(true, Ordering::Release);
            Box::pin(async {
                ActivationOutcome::Succeeded(ActivationSuccess {
                    output: Vec::new(),
                    output_media_type: "application/octet-stream".to_owned(),
                    consumption: BudgetConsumption::default(),
                    committed_state_version: None,
                    effect_ids: Vec::new(),
                    metadata: Metadata::new(),
                })
            })
        }

        fn cancel<'a>(
            &'a self,
            _activation_id: &'a ActivationId,
            _reason: &'a str,
        ) -> BoxFuture<'a, Result<CancelDisposition, PlatformError>> {
            self.cancelled.store(true, Ordering::Release);
            Box::pin(async { Ok(CancelDisposition::Accepted) })
        }
    }

    struct StrictFinalizationObserver;

    impl ActivationObserver for StrictFinalizationObserver {
        fn on_finalized(
            &self,
            _activation_id: &ActivationId,
            _outcome: &ActivationOutcome,
        ) -> Result<(), PlatformError> {
            Err(test_error("strict finalization drop"))
        }

        fn on_cancel_requested(&self, _activation_id: &ActivationId) -> Result<(), PlatformError> {
            Err(test_error("strict cancellation drop"))
        }
    }

    #[tokio::test]
    async fn strict_observer_failures_reach_manager_call_sites() {
        let inner = Arc::new(SuccessfulManager::default());
        let observer: Arc<dyn ActivationObserver> = Arc::new(StrictFinalizationObserver);
        let manager = ObservedActivationManager::new(inner.clone(), observer);
        let envelope = test_envelope("strict-manager");
        let activation_id = envelope.activation_id.clone();

        let outcome = manager.invoke(envelope).await;
        assert!(inner.invoked.load(Ordering::Acquire));
        assert!(matches!(
            outcome,
            ActivationOutcome::Failed {
                error: PlatformError {
                    code: PlatformErrorCode::ResourceExhausted,
                    ..
                },
                ..
            }
        ));

        let error = manager
            .cancel(&activation_id, "test")
            .await
            .expect_err("strict cancellation observation must reach the caller");
        assert!(inner.cancelled.load(Ordering::Acquire));
        assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
    }

    fn test_envelope(id: &str) -> ActivationEnvelope {
        let activation_id = ActivationId(id.to_owned());
        ActivationEnvelope {
            activation_id: activation_id.clone(),
            parent_activation_id: None,
            root_activation_id: activation_id,
            principal: InvocationPrincipal {
                subject: "subject".to_owned(),
                kind: PrincipalKind::User,
                tenant: Some(TenantId("tenant".to_owned())),
                service: None,
                claims: Metadata::new(),
            },
            target: InvocationTarget {
                tenant: TenantId("tenant".to_owned()),
                service: ServiceId("service".to_owned()),
                contract: ContractId("example:contract".to_owned()),
                function: FunctionId("invoke".to_owned()),
                route: None,
            },
            resolved_revision: None,
            deadline_unix_millis: None,
            priority: 0,
            trace: TraceContext {
                trace_id: TraceId(format!("trace-{id}")),
                span_id: SpanId(format!("span-{id}")),
                trace_flags: 1,
                baggage: Metadata::new(),
            },
            idempotency_key: None,
            retry_attempt: 0,
            budget: ResourceBudget {
                cpu_fuel: 10,
                memory_bytes: 1_024,
                wall_time_limit_millis: Some(100),
                child_calls: 0,
                outbound_requests: 0,
                state_read_bytes: 0,
                state_write_bytes: 0,
                blob_read_bytes: 0,
                blob_write_bytes: 0,
                log_bytes: 1_024,
                effect_count: 0,
            },
            metadata: Metadata::new(),
            input: Vec::new(),
            input_media_type: "application/octet-stream".to_owned(),
        }
    }

    fn test_error(message: &str) -> PlatformError {
        PlatformError {
            code: PlatformErrorCode::ResourceExhausted,
            message: message.to_owned(),
            retryable: false,
            details: Vec::new(),
        }
    }
}
