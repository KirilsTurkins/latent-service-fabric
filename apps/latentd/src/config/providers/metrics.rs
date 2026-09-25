use latent_core::PlatformError;
use latent_telemetry::custom::{
    CustomMetricDescriptor, CustomMetricLimits, CustomMetricsConfig, TenantMetricsPolicy,
};
use serde::Deserialize;

use super::{invalid, ProviderIdentity};

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MetricsInstallation {
    pub identity: ProviderIdentity,
    pub descriptors: Vec<CustomMetricDescriptor>,
}

impl MetricsInstallation {
    pub(super) fn validate(&self) -> Result<(), PlatformError> {
        self.identity.validate()?;
        if self.descriptors.is_empty() || self.descriptors.capacity() > 16 {
            return Err(invalid("providers.metrics.descriptors"));
        }
        self.configuration()
            .validate()
            .map_err(|_| invalid("providers.metrics.descriptors"))
    }

    pub(crate) fn configuration(&self) -> CustomMetricsConfig {
        CustomMetricsConfig {
            limits: CustomMetricLimits {
                maximum_series: 32,
                maximum_series_per_tenant: 32,
                observations_per_second: 128,
                observations_per_tenant_per_second: 128,
                maximum_queued_bytes: 65536,
                maximum_queued_bytes_per_tenant: 65536,
                maximum_label_bytes: 1024,
            },
            tenants: vec![TenantMetricsPolicy {
                tenant: self.identity.tenant.clone(),
                metrics: self.descriptors.clone(),
            }],
        }
    }
}
