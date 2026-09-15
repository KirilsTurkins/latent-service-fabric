use super::{CustomAggregation, CustomMetricDescriptor, MetricKind, E};

pub(super) struct Series {
    pub key: [u8; 32],
    pub values: Values,
}
#[derive(Clone, Copy, Default)]
pub(super) struct Values {
    count: u64,
    sum: f64,
    buckets: [u64; 17],
}
impl Values {
    pub(super) fn updated(
        mut self,
        descriptor: &CustomMetricDescriptor,
        value: f64,
    ) -> Result<Self, E> {
        self.count = self.count.checked_add(1).ok_or(E::BudgetExhausted)?;
        self.sum = if descriptor.kind == MetricKind::Gauge {
            value
        } else {
            self.sum + value
        };
        if !self.sum.is_finite() {
            return Err(E::BudgetExhausted);
        }
        if descriptor.kind == MetricKind::Histogram {
            let bucket = descriptor
                .histogram_upper_bounds
                .iter()
                .position(|bound| value <= *bound)
                .unwrap_or(descriptor.histogram_upper_bounds.len());
            self.buckets[bucket] = self.buckets[bucket]
                .checked_add(1)
                .ok_or(E::BudgetExhausted)?;
        }
        Ok(self)
    }
    pub(super) fn export(self, descriptor: &CustomMetricDescriptor) -> CustomAggregation {
        match descriptor.kind {
            MetricKind::Counter | MetricKind::UpDownCounter => CustomAggregation::Sum {
                total: self.sum,
                count: self.count,
            },
            MetricKind::Gauge => CustomAggregation::Gauge,
            MetricKind::Histogram => CustomAggregation::Histogram {
                upper_bounds: descriptor.histogram_upper_bounds.clone().into_boxed_slice(),
                bucket_counts: self.buckets[..=descriptor.histogram_upper_bounds.len()].into(),
                count: self.count,
                sum: self.sum,
            },
        }
    }
}
