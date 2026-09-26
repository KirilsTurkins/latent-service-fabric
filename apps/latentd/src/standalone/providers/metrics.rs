//! Bounded public observations after the shared telemetry exporter has joined.
use latent_capabilities::broker::metrics::MetricProvider;
use latent_core::{PlatformError, PlatformErrorCode};
use latent_telemetry::{StructuredLocalSink, TelemetryRecord};
use serde::Serialize;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MetricObservation {
    pub schema_version: &'static str,
    pub attempted: u64,
    pub accepted: u64,
    pub invalid: u64,
    pub exhausted: u64,
    pub unavailable: u64,
    pub queued_bytes: usize,
    pub retired: bool,
    pub captured_records: usize,
    pub truncated: bool,
    pub sink_evicted_entries: u64,
    pub sink_dropped_oversized: u64,
    pub records: Vec<MetricRecord>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MetricRecord {
    name: String,
    unit: String,
    value_bits: String,
}

pub(super) fn observe(
    provider: &MetricProvider,
    sink: &StructuredLocalSink,
) -> Result<MetricObservation, PlatformError> {
    let registry = provider
        .registry()
        .snapshot()
        .map_err(PlatformError::from)?;
    if !registry.retired || registry.queued_bytes != 0 {
        return Err(PlatformError {
            code: PlatformErrorCode::Unavailable,
            message: "metric-export-cleanup-unconfirmed".into(),
            retryable: false,
            details: Vec::new(),
        });
    }
    let provider = provider.snapshot();
    let mut count = 0;
    let mut records = Vec::with_capacity(16);
    for record in sink.records() {
        if let TelemetryRecord::CustomMetric(metric) = record {
            count += 1;
            if records.len() == 16 {
                records.remove(0);
            }
            let point = metric.point();
            records.push(MetricRecord {
                name: point.name.clone(),
                unit: point.unit.clone(),
                value_bits: format!("{:016x}", point.value.to_bits()),
            });
        }
    }
    let retained = sink.snapshot();
    Ok(MetricObservation {
        schema_version: "latent.standalone.metrics.v1",
        attempted: provider.attempted,
        accepted: provider.accepted,
        invalid: provider.invalid,
        exhausted: provider.exhausted,
        unavailable: provider.unavailable,
        queued_bytes: registry.queued_bytes,
        retired: registry.retired,
        captured_records: count,
        truncated: count > records.len(),
        sink_evicted_entries: retained.evicted_entries,
        sink_dropped_oversized: retained.dropped_oversized,
        records,
    })
}
