use latent_core::Metadata;
use latent_telemetry::{LogRecord, LogSeverity};
use latent_wasmtime::PreparationCompilerSnapshot;
use latent_wire::invocation::ActivationCleanupSnapshot;
use serde::Serialize;

use super::{error, transport, Duration, PlatformError, PlatformErrorCode, StandaloneNode};

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ShutdownReport {
    pub clean: bool,
    pub active_connections: usize,
    pub active_rpcs: usize,
    pub active_control_jobs: usize,
    pub active_activations: usize,
    pub cancellation_registrations: u64,
    pub observer_correlations: usize,
    pub quota_reservations: u32,
    pub queued_reservations: u32,
    pub reserved_cpu_fuel: u64,
    pub reserved_memory_bytes: u64,
    pub active_leases: u64,
    pub queued_activations: u64,
    pub quarantined_cells: u64,
    pub active_backend_invocations: u64,
    pub instance_reservations: usize,
    pub preparing_components: usize,
    pub preparing_source_bytes: usize,
    pub preparing_metadata_bytes: usize,
    pub live_stores: u64,
    pub live_host_states: u64,
    pub live_instances: u64,
    pub live_temporary_buffers: u64,
    pub live_cancellation_probes: u64,
    pub telemetry_retained_entries: usize,
    pub telemetry_flushed: bool,
    pub epoch_helper_joined: bool,
    /// Separate compiler ownership population; thread joins are observed after
    /// consuming factory shutdown, never inferred from quiescent user code.
    pub compiler: PreparationCompilerSnapshot,
    pub cleanup: ActivationCleanupSnapshot,
}

impl ShutdownReport {
    fn reclaimed(&self) -> bool {
        self.active_connections == 0
            && self.active_rpcs == 0
            && self.active_control_jobs == 0
            && self.active_activations == 0
            && self.cancellation_registrations == 0
            && self.observer_correlations == 0
            && self.quota_reservations == 0
            && self.queued_reservations == 0
            && self.reserved_cpu_fuel == 0
            && self.reserved_memory_bytes == 0
            && self.active_leases == 0
            && self.queued_activations == 0
            && self.active_backend_invocations == 0
            && self.instance_reservations == 0
            && self.preparing_components == 0
            && self.preparing_source_bytes == 0
            && self.preparing_metadata_bytes == 0
            && self.live_stores == 0
            && self.live_host_states == 0
            && self.live_instances == 0
            && self.live_temporary_buffers == 0
            && self.live_cancellation_probes == 0
            && compiler_reclaimed(&self.compiler)
            && cleanup_reclaimed(&self.cleanup)
    }
}

impl StandaloneNode {
    /// Stops admission, gives accepted activations a bounded drain interval, then
    /// cancels outstanding owners and verifies cleanup before joining helpers.
    #[expect(
        clippy::too_many_lines,
        reason = "one ordered teardown keeps forced cleanup, resource observations and native joins together"
    )]
    pub async fn shutdown(mut self) -> Result<ShutdownReport, PlatformError> {
        self.supply_chain.retire();
        self.load.stop_accepting();
        let handle = self
            .transport
            .as_ref()
            .map(super::transport::Transport::handle);
        if let Some(handle) = &handle {
            handle.stop_accepting();
        }
        let cleanup = self.cleanup.take().expect("owned cleanup driver");
        let cleanup_handle = cleanup.handle();
        cleanup.stop_accepting();
        let drain_deadline = tokio::time::Instant::now() + self.shutdown_grace;
        while self.manager.journal().snapshot().active != 0 {
            if tokio::time::Instant::now() >= drain_deadline {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        // This phase begins after natural drain. One cutoff covers all forced
        // handoffs and driver scheduling; no invocation deadline is renewed.
        let forced_deadline =
            forced_cleanup_deadline(tokio::time::Instant::now(), self.cleanup_grace)?;
        // Seal compiler admission at the drain cutoff, before transport or
        // sampler cleanup can hide a native job that finishes after its grace.
        let factory = self.factory.take().expect("owned engine factory");
        let compiler_observer = factory.compiler_observer();
        let compiler_quiescence = factory.quiesce_compiler();
        self.scheduler.shutdown();
        let transport = self.transport.take();
        let (transport_result, cleanup_result) = tokio::join!(
            Box::pin(async {
                if let Some(transport) = transport {
                    transport.shutdown().await.map(|_| ())
                } else {
                    Ok(())
                }
            }),
            Box::pin(cleanup.shutdown(forced_deadline))
        );
        let mut failure = transport_result.err();
        if let Err(error) = cleanup_result {
            failure.get_or_insert(error);
        }
        if let Some(sampler) = self.sampler.take() {
            if let Err(error) = sampler.shutdown(self.shutdown_grace).await {
                failure.get_or_insert(error);
            }
        }
        // Native jobs cannot be preempted. Their owned completion must precede
        // observations and final joins, even when it makes shutdown unsuccessful.
        // Idle thread wake/exit scheduling is not additional invocation work.
        if let Err(error) = compiler_quiescence.await {
            failure.get_or_insert(error);
        }
        if compiler_observer
            .last_work_completed_at()
            .is_some_and(|completed| completed > drain_deadline.into_std())
        {
            failure.get_or_insert_with(|| {
                error(
                    PlatformErrorCode::DeadlineExceeded,
                    "compiler work exceeded shutdown grace",
                )
            });
        }
        let mut report = self.shutdown_observations(
            handle.as_ref().map_or_else(
                transport::TransportSnapshot::default,
                transport::TransportHandle::snapshot,
            ),
            cleanup_handle.snapshot(),
        );
        if report.as_ref().is_ok_and(|report| !report.reclaimed()) {
            failure.get_or_insert_with(|| {
                error(
                    PlatformErrorCode::Internal,
                    "node resources were not reclaimed",
                )
            });
        }
        // This diagnostic contains no caller identifiers, payload, or private error.
        let _ = self.telemetry.try_emit_log(LogRecord {
            severity: if failure.is_none() && report.is_ok() {
                LogSeverity::Info
            } else {
                LogSeverity::Error
            },
            body: "standalone shutdown resource check".to_owned(),
            trace: None,
            attributes: Metadata::new(),
            observed_at_unix_millis: self.clock.sample().unix_millis(),
        });
        if let Err(error) = self
            .telemetry_runtime
            .take()
            .expect("owned telemetry")
            .shutdown()
            .await
        {
            failure.get_or_insert(error);
        } else if let Ok(report) = &mut report {
            report.telemetry_flushed = true;
            report.telemetry_retained_entries = self.sink.snapshot().entries;
        }
        // Inventory, manager, and backend are the remaining runtime owners. Their
        // destruction precedes the factory's unique-owner shutdown barrier.
        drop(self);
        if let Err(error) = factory.shutdown() {
            failure.get_or_insert(error);
        } else if let Ok(report) = &mut report {
            report.epoch_helper_joined = true;
        }
        if let Ok(report) = &mut report {
            report.compiler = compiler_observer.snapshot();
        }
        if let Some(error) = failure {
            return Err(error);
        }
        let mut report = report?;
        report.clean = report.reclaimed()
            && report.telemetry_flushed
            && report.epoch_helper_joined
            && report.compiler.workers_joined == report.compiler.maximum_workers as u64;
        Ok(report)
    }

    fn shutdown_observations(
        &self,
        transport: transport::TransportSnapshot,
        cleanup: ActivationCleanupSnapshot,
    ) -> Result<ShutdownReport, PlatformError> {
        let quota = self.quotas.usage()?;
        let mut active_leases = 0_u64;
        let mut queued_activations = 0_u64;
        let mut quarantined_cells = 0_u64;
        for class in &self.classes {
            let snapshot = self.scheduler.observations(*class);
            active_leases += u64::from(snapshot.active_leases);
            queued_activations += u64::from(snapshot.queue_depth);
            quarantined_cells += u64::from(snapshot.quarantined);
        }
        let backend = self.backend.resource_snapshot();
        let cache = self.backend.cache_snapshot();
        Ok(ShutdownReport {
            clean: false,
            active_connections: transport.active_connections,
            active_rpcs: transport.active_rpcs,
            active_control_jobs: transport.active_control_jobs,
            active_activations: self.manager.journal().snapshot().active,
            cancellation_registrations: self.manager.cancellation_snapshot().active_registrations,
            observer_correlations: self.observer.snapshot().active_correlations,
            quota_reservations: quota.active_activations,
            queued_reservations: quota.queued_activations,
            reserved_cpu_fuel: quota.reserved_cpu_fuel,
            reserved_memory_bytes: quota.reserved_memory_bytes,
            active_leases,
            queued_activations,
            quarantined_cells,
            active_backend_invocations: backend.active_invocations,
            instance_reservations: self.backend.active_instance_reservations(),
            preparing_components: cache.preparing,
            preparing_source_bytes: cache.preparing_source_bytes,
            preparing_metadata_bytes: cache.preparing_metadata_bytes,
            live_stores: backend.live_stores,
            live_host_states: backend.live_host_states,
            live_instances: backend.live_component_instances,
            live_temporary_buffers: backend.live_temporary_buffers,
            live_cancellation_probes: backend.live_cancellation_probes,
            telemetry_retained_entries: 0,
            telemetry_flushed: false,
            epoch_helper_joined: false,
            compiler: self.backend.compiler_snapshot(),
            cleanup,
        })
    }
}

fn forced_cleanup_deadline(
    now: tokio::time::Instant,
    grace: Duration,
) -> Result<tokio::time::Instant, PlatformError> {
    grace
        .checked_mul(2)
        .and_then(|duration| now.checked_add(duration))
        .ok_or_else(|| {
            error(
                PlatformErrorCode::InvalidArgument,
                "cleanup deadline exceeds its bound",
            )
        })
}

fn cleanup_reclaimed(cleanup: &ActivationCleanupSnapshot) -> bool {
    !cleanup.accepting
        && !cleanup.driver_alive
        && cleanup.driver_joined
        && cleanup.reserved == 0
        && cleanup.queued == 0
        && cleanup.running == 0
        && cleanup.timed_out == 0
        && cleanup.panicked == 0
        && cleanup.fallbacks == 0
        && cleanup.handoffs == cleanup.completed
        && !cleanup.failed
}

#[cfg(test)]
mod tests;

fn compiler_reclaimed(compiler: &PreparationCompilerSnapshot) -> bool {
    !compiler.accepting
        && !compiler.failed
        && compiler.assigned_jobs == 0
        && compiler.running_jobs == 0
        && compiler.queued_jobs == 0
        && compiler.waiting_callers == 0
        && compiler.ready_preparations == 0
        && compiler.ready_metadata_bytes == 0
        && compiler.ready_compiled_image_bytes == 0
        && compiler.reserved_document_bytes == 0
        && compiler.workers_live == 0
        && compiler.workers_quiescent == compiler.maximum_workers as u64
}
