//! Retained allocation accounting, shared by queued and directly exported records.
use super::{dimensions::valid_metric_dimension, TelemetryPipelineConfig};
use crate::local::TelemetryRecord;
use latent_activation::TraceContext;
use latent_core::Metadata;

pub(crate) fn retained_bytes(record: &TelemetryRecord, maximum: usize) -> Option<usize> {
    let mut cost = Cost { remaining: maximum };
    cost.charge(size_of::<TelemetryRecord>())?;
    match record {
        TelemetryRecord::Metric(point) => {
            cost.string(&point.name)?;
            cost.string(&point.unit)?;
            cost.metadata(&point.attributes)?;
        }
        TelemetryRecord::Log(record) => {
            cost.string(&record.body)?;
            if let Some(trace) = &record.trace {
                cost.trace(trace)?;
            }
            cost.metadata(&record.attributes)?;
        }
        TelemetryRecord::Span(span) => {
            cost.string(&span.name)?;
            cost.string(&span.status)?;
            if let Some(parent) = &span.parent_span_id {
                cost.string(parent)?;
            }
            cost.trace(&span.trace)?;
            cost.metadata(&span.attributes)?;
        }
    }
    Some(maximum - cost.remaining)
}
struct Cost {
    remaining: usize,
}
impl Cost {
    fn charge(&mut self, bytes: usize) -> Option<()> {
        self.remaining = self.remaining.checked_sub(bytes)?;
        Some(())
    }
    fn string(&mut self, value: &String) -> Option<()> {
        self.charge(value.capacity())
    }
    fn metadata(&mut self, metadata: &Metadata) -> Option<()> {
        // A fixed allowance covers an empty retained root. Per-entry space is
        // conservative for sparse B-tree nodes storing String/String pairs;
        // separately charge both owned string allocations, including spare capacity.
        self.charge(4096_usize.checked_add(metadata.len().checked_mul(1024)?)?)?;
        for (name, value) in metadata {
            self.string(name)?;
            self.string(value)?;
        }
        Some(())
    }
    fn trace(&mut self, trace: &TraceContext) -> Option<()> {
        self.string(&trace.trace_id.0)?;
        self.string(&trace.span_id.0)?;
        self.metadata(&trace.baggage)
    }
}

pub(super) fn valid(record: &TelemetryRecord, config: &TelemetryPipelineConfig) -> bool {
    // This also bounds traversal before inspecting individual map entries.
    if retained_bytes(record, config.maximum_record_bytes).is_none() {
        return false;
    }
    match record {
        TelemetryRecord::Metric(point) => {
            !point.name.is_empty()
                && point.name.len() <= config.maximum_attribute_value_bytes
                && point.unit.len() <= config.maximum_attribute_name_bytes
                && point.value.is_finite()
                && metadata_valid(&point.attributes, config)
                && point
                    .attributes
                    .iter()
                    .all(|(name, value)| valid_metric_dimension(name, value))
        }
        TelemetryRecord::Log(record) => {
            record
                .trace
                .as_ref()
                .is_none_or(|trace| trace_valid(trace, config))
                && metadata_valid(&record.attributes, config)
        }
        TelemetryRecord::Span(span) => {
            !span.name.is_empty()
                && span.name.len() <= config.maximum_attribute_value_bytes
                && span.status.len() <= config.maximum_attribute_value_bytes
                && span
                    .parent_span_id
                    .as_ref()
                    .is_none_or(|id| id.len() <= config.maximum_attribute_value_bytes)
                && trace_valid(&span.trace, config)
                && metadata_valid(&span.attributes, config)
        }
    }
}
fn metadata_valid(metadata: &Metadata, config: &TelemetryPipelineConfig) -> bool {
    metadata.len() <= config.maximum_attributes
        && metadata.iter().all(|(name, value)| {
            !name.is_empty()
                && name.len() <= config.maximum_attribute_name_bytes
                && value.len() <= config.maximum_attribute_value_bytes
        })
}
fn trace_valid(trace: &TraceContext, config: &TelemetryPipelineConfig) -> bool {
    trace.trace_id.0.len() <= config.maximum_attribute_value_bytes
        && trace.span_id.0.len() <= config.maximum_attribute_value_bytes
        && metadata_valid(&trace.baggage, config)
}
