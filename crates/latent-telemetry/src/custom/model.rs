use crate::{MetricKind, MetricPoint};
use latent_core::{PlatformError, PlatformErrorCode};
use std::sync::Arc;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CustomMetricError {
    InvalidName,
    BudgetExhausted,
    Unavailable,
}
impl From<PlatformError> for CustomMetricError {
    fn from(error: PlatformError) -> Self {
        match error.code {
            PlatformErrorCode::ResourceExhausted => Self::BudgetExhausted,
            PlatformErrorCode::InvalidArgument => Self::InvalidName,
            _ => Self::Unavailable,
        }
    }
}
impl From<CustomMetricError> for PlatformError {
    fn from(error: CustomMetricError) -> Self {
        Self {
            code: match error {
                CustomMetricError::InvalidName => PlatformErrorCode::InvalidArgument,
                CustomMetricError::BudgetExhausted => PlatformErrorCode::ResourceExhausted,
                CustomMetricError::Unavailable => PlatformErrorCode::Unavailable,
            },
            message: "custom-metric-rejected".into(),
            retryable: false,
            details: Vec::new(),
        }
    }
}
/// The trusted adapter supplies source identity from the pinned activation plan.
#[derive(Clone, Copy)]
pub struct CustomMetricSource<'a> {
    pub tenant: &'a str,
    pub service: &'a str,
    pub revision: &'a str,
}
#[derive(Clone, Copy)]
pub struct CustomMetricInput<'a> {
    pub name: &'a str,
    pub kind: MetricKind,
    pub value: f64,
    pub unit: &'a str,
    pub attributes: &'a [(String, String)],
}
/// Aggregation covers accepted observations, including later exporter failures.
/// Counter/up-down values in `MetricPoint` are deltas; gauge values are samples.
#[derive(Debug, Clone, PartialEq)]
pub enum CustomAggregation {
    Sum {
        total: f64,
        count: u64,
    },
    Gauge,
    Histogram {
        /// Strictly increasing finite inclusive upper bounds.
        upper_bounds: Box<[f64]>,
        /// Disjoint bucket counts, with a final +infinity bucket.
        bucket_counts: Box<[u64]>,
        count: u64,
        sum: f64,
    },
}
#[derive(Debug, PartialEq)]
pub(super) struct Sample {
    pub point: MetricPoint,
    pub sequence: u64,
    pub aggregation: CustomAggregation,
}
/// Only the configured registry can construct a custom record. Clones share
/// immutable allocation; a copy grants neither series admission nor authority.
#[derive(Debug, Clone, PartialEq)]
pub struct CustomMetricPoint(pub(super) Arc<Sample>);
impl CustomMetricPoint {
    #[must_use]
    pub fn point(&self) -> &MetricPoint {
        &self.0.point
    }
    #[must_use]
    pub fn sequence(&self) -> u64 {
        self.0.sequence
    }
    #[must_use]
    pub fn aggregation(&self) -> &CustomAggregation {
        &self.0.aggregation
    }
    pub(crate) fn retained_bytes(&self) -> usize {
        let p = &self.0.point;
        let extra = match &self.0.aggregation {
            CustomAggregation::Histogram {
                upper_bounds,
                bucket_counts,
                ..
            } => (upper_bounds.len() + bucket_counts.len()) * 8,
            _ => 0,
        };
        // B-tree bookkeeping follows the shared pipeline's conservative charge.
        size_of::<Sample>()
            + 64
            + extra
            + p.name.capacity()
            + p.unit.capacity()
            + 4096
            + p.attributes.len() * 1024
            + p.attributes
                .iter()
                .map(|(k, v)| k.capacity() + v.capacity())
                .sum::<usize>()
    }
}
