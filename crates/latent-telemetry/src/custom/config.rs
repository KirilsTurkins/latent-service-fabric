use super::model::CustomMetricError;
use crate::MetricKind;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CustomMetricLabel {
    pub key: String,
    pub values: Vec<String>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CustomMetricDescriptor {
    pub name: String,
    pub kind: MetricKind,
    pub unit: String,
    pub labels: Vec<CustomMetricLabel>,
    pub histogram_upper_bounds: Vec<f64>,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TenantMetricsPolicy {
    pub tenant: String,
    pub metrics: Vec<CustomMetricDescriptor>,
}
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CustomMetricLimits {
    pub maximum_series: usize,
    pub maximum_series_per_tenant: usize,
    pub observations_per_second: usize,
    pub observations_per_tenant_per_second: usize,
    pub maximum_queued_bytes: usize,
    pub maximum_queued_bytes_per_tenant: usize,
    pub maximum_label_bytes: usize,
}
impl Default for CustomMetricLimits {
    fn default() -> Self {
        Self {
            maximum_series: 512,
            maximum_series_per_tenant: 64,
            observations_per_second: 4096,
            observations_per_tenant_per_second: 1024,
            maximum_queued_bytes: 4 * 1024 * 1024,
            maximum_queued_bytes_per_tenant: 512 * 1024,
            maximum_label_bytes: 1024,
        }
    }
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CustomMetricsConfig {
    pub limits: CustomMetricLimits,
    pub tenants: Vec<TenantMetricsPolicy>,
}
pub(super) fn token(value: &str, maximum: usize) -> bool {
    !value.is_empty()
        && value.len() <= maximum
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_.-/".contains(&b))
}
pub(super) fn name(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value.as_bytes()[0].is_ascii_alphabetic()
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_.".contains(&b))
        && !["latent", "otel", "host"].iter().any(|prefix| {
            value
                .get(..prefix.len())
                .is_some_and(|s| s.eq_ignore_ascii_case(prefix))
        })
}
fn fail() -> CustomMetricError {
    CustomMetricError::InvalidName
}
impl CustomMetricsConfig {
    pub(super) fn validate(&self) -> Result<(), CustomMetricError> {
        let l = self.limits;
        if !(1..=1024).contains(&l.maximum_series)
            || !(1..=l.maximum_series).contains(&l.maximum_series_per_tenant)
            || !(1..=16_384).contains(&l.observations_per_second)
            || !(1..=l.observations_per_second).contains(&l.observations_per_tenant_per_second)
            || !(super::registry::RECORD_BYTES..=32 * 1024 * 1024).contains(&l.maximum_queued_bytes)
            || !(super::registry::RECORD_BYTES..=l.maximum_queued_bytes)
                .contains(&l.maximum_queued_bytes_per_tenant)
            || !(1..=4096).contains(&l.maximum_label_bytes)
            || self.tenants.is_empty()
            || self.tenants.len() > 8
            || self.tenants.capacity() > 8
        {
            return Err(fail());
        }
        let mut metadata = self.tenants.capacity() * size_of::<TenantMetricsPolicy>();
        let mut descriptors = 0;
        for (i, tenant) in self.tenants.iter().enumerate() {
            if !token(&tenant.tenant, 128)
                || tenant.tenant.capacity() > 128
                || tenant.metrics.is_empty()
                || tenant.metrics.len() > 32
                || tenant.metrics.capacity() > 32
                || self.tenants[..i]
                    .iter()
                    .any(|old| old.tenant == tenant.tenant)
            {
                return Err(fail());
            }
            descriptors += tenant.metrics.len();
            metadata += tenant.tenant.capacity()
                + tenant.metrics.capacity() * size_of::<CustomMetricDescriptor>();
            for (j, metric) in tenant.metrics.iter().enumerate() {
                metric.validate(&mut metadata)?;
                if tenant.metrics[..j]
                    .iter()
                    .any(|old| old.name == metric.name)
                {
                    return Err(fail());
                }
                for old in self.tenants[..i]
                    .iter()
                    .flat_map(|t| &t.metrics)
                    .filter(|old| old.name == metric.name)
                {
                    if old.kind != metric.kind
                        || old.unit != metric.unit
                        || old.histogram_upper_bounds != metric.histogram_upper_bounds
                    {
                        return Err(fail());
                    }
                }
            }
        }
        if descriptors > 128 || metadata > 256 * 1024 {
            return Err(fail());
        }
        Ok(())
    }
}
impl CustomMetricDescriptor {
    fn validate(&self, metadata: &mut usize) -> Result<(), CustomMetricError> {
        if !name(&self.name)
            || self.name.capacity() > 64
            || !token(&self.unit, 16)
            || self.unit.capacity() > 16
            || self.labels.len() > 8
            || self.labels.capacity() > 8
            || self.histogram_upper_bounds.len() > 16
            || self.histogram_upper_bounds.capacity() > 16
            || (self.kind != MetricKind::Histogram && !self.histogram_upper_bounds.is_empty())
            || self.histogram_upper_bounds.iter().any(|v| !v.is_finite())
            || self
                .histogram_upper_bounds
                .windows(2)
                .any(|pair| pair[0] >= pair[1])
        {
            return Err(fail());
        }
        *metadata += self.name.capacity()
            + self.unit.capacity()
            + self.labels.capacity() * size_of::<CustomMetricLabel>()
            + self.histogram_upper_bounds.capacity() * size_of::<f64>();
        for (index, label) in self.labels.iter().enumerate() {
            if !name(&label.key)
                || label.key.len() > 32
                || label.key.capacity() > 32
                || label.values.is_empty()
                || label.values.len() > 16
                || label.values.capacity() > 16
                || self.labels[..index].iter().any(|old| old.key == label.key)
            {
                return Err(fail());
            }
            *metadata += label.key.capacity() + label.values.capacity() * size_of::<String>();
            for (i, value) in label.values.iter().enumerate() {
                if value.is_empty()
                    || value.len() > 64
                    || value.capacity() > 64
                    || !value.bytes().all(|b| b.is_ascii_graphic())
                    || label.values[..i].contains(value)
                {
                    return Err(fail());
                }
                *metadata += value.capacity();
            }
        }
        Ok(())
    }
}
