use latent_core::Metadata;
use latent_telemetry::{LogRecord, LogSeverity};
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
    }
}

impl StandaloneNode {
    /// Stops admission, gives accepted activations a bounded drain interval, then
    /// cancels outstanding owners and verifies cleanup before joining helpers.
    pub async fn shutdown(mut self) -> Result<ShutdownReport, PlatformError> {
        self.load.stop_accepting();
        let handle = self.transport.as_ref().expect("live transport").handle();
        handle.stop_accepting();
        let drain_deadline = tokio::time::Instant::now() + self.shutdown_grace;
        while self.manager.journal().snapshot().active != 0 {
            if tokio::time::Instant::now() >= drain_deadline {
                break;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        self.scheduler.shutdown();
        let mut failure = self
            .transport
            .take()
            .expect("owned transport")
            .shutdown()
            .await
            .err();
        if let Err(error) = self
            .sampler
            .take()
            .expect("owned sampler")
            .shutdown(self.shutdown_grace)
            .await
        {
            failure.get_or_insert(error);
        }
        let mut report = self.shutdown_observations(handle.snapshot());
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
        let factory = self.factory.take().expect("owned engine factory");
        // Inventory, manager, and backend are the remaining runtime owners. Their
        // destruction precedes the factory's unique-owner shutdown barrier.
        drop(self);
        if let Err(error) = factory.shutdown() {
            failure.get_or_insert(error);
        } else if let Ok(report) = &mut report {
            report.epoch_helper_joined = true;
        }
        if let Some(error) = failure {
            return Err(error);
        }
        let mut report = report?;
        report.clean = report.reclaimed() && report.telemetry_flushed && report.epoch_helper_joined;
        Ok(report)
    }

    fn shutdown_observations(
        &self,
        transport: transport::TransportSnapshot,
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
        })
    }
}
