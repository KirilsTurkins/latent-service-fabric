use latent_core::{BoxFuture, PlatformError, PlatformErrorCode};
use latent_node::{InventoryReporter, NodeInventory};
use latent_telemetry::{MetricPoint, StructuredLocalSink, TelemetryRecord};

use crate::{IdleScalingObservation, InvariantProbe};

/// Supplies an actual measurement, including measured route lookup latency.
/// Implementations should read bounded, already collected evidence; this port
/// does not authorize a scale, calibration, or load workload.
pub trait IdleScalingMeasurement: Send + Sync {
    fn observation(
        &self,
        registered_releases: u64,
    ) -> BoxFuture<'_, Result<IdleScalingObservation, PlatformError>>;
}

/// Delegates inventory to its real reporter and reads a bounded local telemetry
/// capture. Reporter failures and missing measurements remain explicit errors.
pub struct ObservedInvariantProbe<'a> {
    inventory: &'a dyn InventoryReporter,
    telemetry: &'a StructuredLocalSink,
    idle: Option<&'a dyn IdleScalingMeasurement>,
}

impl<'a> ObservedInvariantProbe<'a> {
    pub fn new(
        inventory: &'a dyn InventoryReporter,
        telemetry: &'a StructuredLocalSink,
        idle: Option<&'a dyn IdleScalingMeasurement>,
    ) -> Result<Self, PlatformError> {
        // Check immutable configured maxima, not a racy current entry count,
        // before records() can clone any source-owned strings or collections.
        let bounds = telemetry.snapshot();
        if bounds.maximum_entries > 4096 || bounds.maximum_bytes > 8 * 1024 * 1024 {
            return Err(super::error(
                PlatformErrorCode::ResourceExhausted,
                "harness-telemetry-source-too-large",
            ));
        }
        Ok(Self {
            inventory,
            telemetry,
            idle,
        })
    }
}

impl InvariantProbe for ObservedInvariantProbe<'_> {
    fn node_inventory(&self) -> BoxFuture<'_, Result<NodeInventory, PlatformError>> {
        self.inventory.snapshot()
    }

    fn idle_scaling(
        &self,
        registered_releases: u64,
    ) -> BoxFuture<'_, Result<IdleScalingObservation, PlatformError>> {
        Box::pin(async move {
            let source = self.idle.ok_or_else(|| {
                super::error(
                    PlatformErrorCode::IncompatibleContract,
                    "idle-scaling-requires-measured-route-latency-evidence",
                )
            })?;
            let observation = source.observation(registered_releases).await?;
            if observation.registered_releases != registered_releases
                || observation.process_count == 0
                || observation.thread_count == 0
                || observation.resident_memory_bytes == 0
            {
                return Err(super::error(
                    PlatformErrorCode::InvalidArgument,
                    "invalid-idle-scaling-measurement",
                ));
            }
            Ok(observation)
        })
    }

    fn telemetry(&self) -> BoxFuture<'_, Result<Vec<MetricPoint>, PlatformError>> {
        Box::pin(async move {
            Ok(self
                .telemetry
                .records()
                .into_iter()
                .filter_map(|record| match record {
                    TelemetryRecord::Metric(point) => Some(point),
                    TelemetryRecord::Log(_) | TelemetryRecord::Span(_) => None,
                })
                .collect())
        })
    }
}
