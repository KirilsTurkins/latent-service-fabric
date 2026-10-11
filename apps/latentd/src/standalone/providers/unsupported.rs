use std::{sync::Arc, time::Instant};

use latent_artifacts::DirectoryArtifactRepository;
use latent_capabilities::broker::ActivationCapabilityRuntime;
use latent_control_store::DirectoryDeploymentRepository;
use latent_core::{PlatformError, PlatformErrorCode};
use latent_policy::capability::PolicyStore;

use super::{ProviderDescriptor, ProviderServices, ProviderShutdownReport};
use crate::config::NodeSettings;

pub(in crate::standalone) struct ProviderRuntime {
    pub runtime: Arc<ActivationCapabilityRuntime>,
}

impl ProviderRuntime {
    pub async fn open(
        _settings: &NodeSettings,
        _artifacts: &Arc<DirectoryArtifactRepository>,
        _deployments: &Arc<DirectoryDeploymentRepository>,
        _policies: Arc<PolicyStore>,
        _services: ProviderServices,
    ) -> Result<Self, PlatformError> {
        Err(unsupported())
    }

    pub fn descriptors(&self) -> &[ProviderDescriptor] {
        &[]
    }

    pub fn metric_observation(
        &self,
        _sink: &latent_telemetry::StructuredLocalSink,
    ) -> Result<Option<super::MetricObservation>, PlatformError> {
        Err(unsupported())
    }

    pub fn retire(&self) {
        self.runtime.retire();
    }

    pub async fn shutdown(
        &self,
        _deadline: Instant,
    ) -> Result<ProviderShutdownReport, PlatformError> {
        Err(unsupported())
    }
}

fn unsupported() -> PlatformError {
    crate::standalone::error(
        PlatformErrorCode::IncompatibleContract,
        "configured-provider-platform-unsupported",
    )
}
