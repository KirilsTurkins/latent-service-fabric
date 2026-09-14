//! Exact data-only bindings published by the existing deployment transaction.
mod compile;
pub(in crate::deployments) mod model;
mod source;
pub(in crate::deployments) use source::Generations;
mod update;
pub use model::{BindingDefinition, BindingLimits, ConfiguredBindingProvider};
pub use update::PreparedBindingUpdate;

use super::{compiler::CompiledCatalog, PublishedCatalog};
use latent_capabilities::broker::{ActivationCapabilityBroker, CompiledCapabilityPlan};
use latent_core::{PlatformError, PlatformErrorCode};
use model::StoredBinding;
use std::sync::{Arc, RwLock, Weak};

pub(super) struct CompilerOwner {
    broker: Arc<ActivationCapabilityBroker>,
    providers: Box<[ConfiguredBindingProvider]>,
    current: Weak<RwLock<PublishedCatalog>>,
    limits: BindingLimits,
}
impl CompilerOwner {
    fn retained_bytes(&self) -> usize {
        256 + self
            .providers
            .iter()
            .map(|provider| {
                256 + provider.tenant.0.capacity()
                    + provider.service.0.capacity()
                    + provider
                        .local_deployment
                        .as_ref()
                        .map_or(0, |id| id.0.capacity())
            })
            .sum::<usize>()
    }
}
/// Source facts survive unavailable providers and restart; parser/package input
/// is temporary and no connection, guest instance or cell is retained here.
pub(super) struct BindingCatalog {
    pub data: Arc<[StoredBinding]>,
    owner: Option<Arc<CompilerOwner>>,
    plans: Box<[Arc<CompiledCapabilityPlan>]>,
    unavailable: usize,
}
impl Default for BindingCatalog {
    fn default() -> Self {
        Self {
            data: Arc::from([]),
            owner: None,
            plans: Box::new([]),
            unavailable: 0,
        }
    }
}
impl BindingCatalog {
    pub fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if let Some(owner) = &self.owner {
            owner.broker.with_current_plans(&self.plans, action)
        } else {
            action()
        }
    }
    pub fn retained_bytes(&self) -> usize {
        if self.data.is_empty() && self.owner.is_none() {
            return 0;
        }
        256 + self
            .owner
            .as_ref()
            .map_or(0, |owner| owner.retained_bytes())
            + self
                .data
                .iter()
                .map(StoredBinding::retained_bytes)
                .sum::<usize>()
            + self.plans.len() * std::mem::size_of::<Arc<CompiledCapabilityPlan>>()
    }
}
pub(super) async fn inherit(
    catalog: &CompiledCatalog,
    previous: Option<&CompiledCatalog>,
    artifacts: &dyn latent_artifacts::ArtifactRepository,
) -> Result<BindingCatalog, PlatformError> {
    let Some(previous) = previous else {
        return Ok(BindingCatalog::default());
    };
    if previous.bindings.owner.is_none() && previous.bindings.data.is_empty() {
        return Ok(BindingCatalog::default());
    }
    compile::compile(
        catalog,
        Arc::clone(&previous.bindings.data),
        previous.bindings.owner.clone(),
        artifacts,
        false,
    )
    .await
}
pub(super) async fn restore(
    catalog: &CompiledCatalog,
    data: Vec<StoredBinding>,
    artifacts: &dyn latent_artifacts::ArtifactRepository,
) -> Result<BindingCatalog, PlatformError> {
    compile::compile(catalog, data.into(), None, artifacts, false).await
}
fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    super::error(code, message)
}
fn invalid() -> PlatformError {
    error(PlatformErrorCode::InvalidArgument, "binding-invalid")
}
fn denied() -> PlatformError {
    error(PlatformErrorCode::PermissionDenied, "binding-denied")
}
fn capacity() -> PlatformError {
    error(PlatformErrorCode::ResourceExhausted, "binding-capacity")
}
