#[derive(Debug, Default)]
struct MutableActivationPhaseTiming {
    acquisition_queued: bool,
    acquire_or_queue_wait_micros: Option<u64>,
    contained_execution_micros: Option<u64>,
    backend_total_micros: Option<u64>,
    backend_resource_cleanup_micros: Option<u64>,
    cell_disposition_micros: Option<u64>,
}

#[derive(Clone, Debug, Default)]
struct PhaseTimingRecorder {
    state: Arc<Mutex<HashMap<String, MutableActivationPhaseTiming>>>,
}

impl PhaseTimingRecorder {
    fn record_acquire(
        &self,
        activation_id: &ActivationId,
        elapsed_micros: u64,
        queued: bool,
    ) {
        let mut state = self.lock();
        let timing = state.entry(activation_id.0.clone()).or_default();
        timing.acquire_or_queue_wait_micros = Some(elapsed_micros);
        timing.acquisition_queued = queued;
    }

    fn record_backend(
        &self,
        activation_id: &ActivationId,
        backend_total_micros: u64,
        contained_execution_micros: u64,
    ) {
        let mut state = self.lock();
        let timing = state.entry(activation_id.0.clone()).or_default();
        timing.backend_total_micros = Some(backend_total_micros);
        timing.contained_execution_micros = Some(contained_execution_micros);
        timing.backend_resource_cleanup_micros = Some(
            backend_total_micros.saturating_sub(contained_execution_micros),
        );
    }

    fn record_disposition(&self, activation_id: &ActivationId, elapsed_micros: u64) {
        let mut state = self.lock();
        state
            .entry(activation_id.0.clone())
            .or_default()
            .cell_disposition_micros = Some(elapsed_micros);
    }

    fn take_report(
        &self,
        activation_id: &ActivationId,
        total_invocation_micros: u64,
    ) -> Result<ActivationPhaseTimingReport, BenchError> {
        let timing = self
            .lock()
            .remove(&activation_id.0)
            .ok_or_else(|| {
                BenchError::new(format!(
                    "phase timing recorder has no entry for {}",
                    activation_id.0
                ))
            })?;
        let acquire = timing.acquire_or_queue_wait_micros.ok_or_else(|| {
            BenchError::new(format!(
                "phase timing recorder has no acquire result for {}",
                activation_id.0
            ))
        })?;
        let contained = timing.contained_execution_micros.ok_or_else(|| {
            BenchError::new(format!(
                "phase timing recorder has no contained-execution result for {}",
                activation_id.0
            ))
        })?;
        let backend_total = timing.backend_total_micros.ok_or_else(|| {
            BenchError::new(format!(
                "phase timing recorder has no backend result for {}",
                activation_id.0
            ))
        })?;
        let backend_cleanup = timing.backend_resource_cleanup_micros.ok_or_else(|| {
            BenchError::new(format!(
                "phase timing recorder has no backend-cleanup result for {}",
                activation_id.0
            ))
        })?;
        let disposition = timing.cell_disposition_micros.ok_or_else(|| {
            BenchError::new(format!(
                "phase timing recorder has no cell-disposition result for {}",
                activation_id.0
            ))
        })?;
        Ok(ActivationPhaseTimingReport {
            acquisition_queued: timing.acquisition_queued,
            acquire_or_queue_wait_micros: acquire,
            contained_execution_micros: contained,
            backend_total_micros: backend_total,
            backend_resource_cleanup_micros: backend_cleanup,
            cell_disposition_micros: disposition,
            post_invocation_cleanup_micros: backend_cleanup.saturating_add(disposition),
            total_invocation_micros,
        })
    }

    fn lock(&self) -> MutexGuard<'_, HashMap<String, MutableActivationPhaseTiming>> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

#[derive(Clone)]
struct TimingCellPool {
    inner: Arc<FixedCellPool>,
    timings: PhaseTimingRecorder,
}

impl TimingCellPool {
    fn new(inner: Arc<FixedCellPool>, timings: PhaseTimingRecorder) -> Self {
        Self { inner, timings }
    }
}

impl CellPool for TimingCellPool {
    fn acquire<'a>(
        &'a self,
        activation_id: &'a ActivationId,
        tenant: &'a TenantId,
        class: CellClass,
        budget: &'a ResourceBudget,
    ) -> BoxFuture<'a, Result<CellLease, PlatformError>> {
        let activation_id = activation_id.clone();
        let tenant = tenant.clone();
        let budget = budget.clone();
        let inner = Arc::clone(&self.inner);
        let timings = self.timings.clone();
        Box::pin(async move {
            let queued = inner.observations().available == 0;
            let started = Instant::now();
            let result = inner
                .acquire(&activation_id, &tenant, class, &budget)
                .await;
            timings.record_acquire(
                &activation_id,
                duration_micros(started.elapsed()),
                queued,
            );
            result
        })
    }

    fn release<'a>(&'a self, lease: CellLease) -> BoxFuture<'a, Result<(), PlatformError>> {
        let activation_id = lease.activation_id.clone();
        let inner = Arc::clone(&self.inner);
        let timings = self.timings.clone();
        Box::pin(async move {
            let started = Instant::now();
            let result = inner.release(lease).await;
            timings.record_disposition(&activation_id, duration_micros(started.elapsed()));
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
        self.inner.cancel_waiting(activation_id)
    }

    fn quarantine<'a>(
        &'a self,
        lease: CellLease,
        reason: String,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        let activation_id = lease.activation_id.clone();
        let inner = Arc::clone(&self.inner);
        let timings = self.timings.clone();
        Box::pin(async move {
            let started = Instant::now();
            let result = inner.quarantine(lease, reason).await;
            timings.record_disposition(&activation_id, duration_micros(started.elapsed()));
            result
        })
    }

    fn observations(&self, class: CellClass) -> CellPoolSnapshot {
        CellPool::observations(self.inner.as_ref(), class)
    }
}

struct TimingExecutionBackend {
    inner: Arc<Phase0WasmtimeBackend>,
    timings: PhaseTimingRecorder,
}

impl TimingExecutionBackend {
    fn new(inner: Arc<Phase0WasmtimeBackend>, timings: PhaseTimingRecorder) -> Self {
        Self { inner, timings }
    }
}

impl ExecutionBackend for TimingExecutionBackend {
    fn backend_id(&self) -> &str {
        self.inner.backend_id()
    }

    fn prepare<'a>(
        &'a self,
        artifact: &'a CapsuleArtifact,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>> {
        self.inner.prepare(artifact, key)
    }

    fn invoke<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>> {
        self.inner.invoke(request, cancellation)
    }

    fn invoke_contained<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, ExecutionReport> {
        let activation_id = request.activation.activation_id.clone();
        Box::pin(async move {
            let started = Instant::now();
            let report = self.inner.invoke_contained(request, cancellation).await;
            let backend_total_micros = duration_micros(started.elapsed());
            let contained_execution_micros = execution_wall_time_micros(&report.outcome);
            self.timings.record_backend(
                &activation_id,
                backend_total_micros,
                contained_execution_micros,
            );
            report
        })
    }

    fn release<'a>(
        &'a self,
        prepared: PreparedComponent,
    ) -> BoxFuture<'a, Result<(), PlatformError>> {
        self.inner.release(prepared)
    }
}

fn execution_wall_time_micros(outcome: &Result<GuestOutcome, PlatformError>) -> u64 {
    match outcome {
        Ok(GuestOutcome::Returned { consumption, .. })
        | Ok(GuestOutcome::Trapped { consumption, .. })
        | Ok(GuestOutcome::Interrupted { consumption, .. }) => consumption.wall_time_micros,
        Err(_) => 0,
    }
}
