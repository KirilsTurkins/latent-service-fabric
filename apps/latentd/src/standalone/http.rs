//! One optional bounded HTTP application listener, shared by every deployment.
mod assets;
mod connection;
mod dispatch;
mod head;
mod owner;
mod state;
#[cfg(test)]
mod tests;
pub(crate) mod tls;
mod write;

use crate::config::http::HttpSettings;
use latent_core::{ActivationClock, PlatformError, PlatformErrorCode, ResourceBudget};
use std::{sync::Arc, time::Duration};

pub use assets::AssetSnapshot;
pub(crate) use owner::HttpOwner;
pub(crate) use state::HttpHandle;
pub use state::HttpSnapshot;

pub(crate) struct HttpServices {
    pub manager: latent_node::LocalActivationManager,
    pub deployments: Arc<latent_control_store::DirectoryDeploymentRepository>,
    pub cleanup: latent_wire::invocation::ActivationCleanupHandle,
    pub clock: Arc<dyn ActivationClock>,
    pub budget: ResourceBudget,
}
struct Shared {
    settings: HttpSettings,
    services: HttpServices,
    handle: HttpHandle,
    traces: latent_wire::invocation::SystemInvocationTraceSource,
}
fn failure() -> PlatformError {
    super::error(
        PlatformErrorCode::Unavailable,
        "http-ingress-owner-unavailable",
    )
}
const fn millis(value: u64) -> Duration {
    Duration::from_millis(value)
}
