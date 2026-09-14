//! Bounded capability policy language and tenant-scoped authorization ownership.
//!
//! Descriptive manifests and explanations are not execution permission. The
//! configured policy owner must issue and recheck a sealed admission decision.

mod binding;
mod control;
mod language;
mod narrowing;
mod resource_request;
mod resources;
mod store;
#[cfg(test)]
mod tests;

pub use binding::ProviderBinding;
pub use control::{PolicyControlHandle, PolicyWorkPermit};
pub use language::{CapabilityPolicy, PrincipalClass};
pub use narrowing::GrantRestriction;
pub use resource_request::ResourceRequest;
pub use resources::{CapabilityCeiling, HttpOrigin, ResourceConstraint, ResourceTarget};
pub use store::{
    CallRestrictions, CapabilityPolicyRevision, EvaluationInput, Explanation, PolicySnapshot,
    PolicySnapshotState, SealedPolicyDecision,
};
pub use store::{
    MutationRequest, OperationReceipt, PolicyPage, PolicyPageRequest, PolicyRead, PolicyReadLease,
    PolicyStore, PolicyStoreLimits, RecordKind, RecordView,
};

use latent_core::{PlatformError, PlatformErrorCode};

pub const LANGUAGE: &str = "lsf-capability-policy-v1";
pub const PROVIDER_BINDING_LANGUAGE: &str = "lsf-provider-binding-v1";
pub const MAX_DOCUMENT_BYTES: usize = 64 * 1024;
pub const MAX_RULES: usize = 64;
pub const MAX_SET_ENTRIES: usize = 16;

fn invalid() -> PlatformError {
    error(
        PlatformErrorCode::InvalidArgument,
        "capability-policy-invalid",
    )
}
fn error(code: PlatformErrorCode, message: &'static str) -> PlatformError {
    PlatformError {
        code,
        message: message.into(),
        retryable: false,
        details: Vec::new(),
    }
}
fn capacity() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "capability-policy-capacity",
    )
}
fn unavailable() -> PlatformError {
    error(
        PlatformErrorCode::Unavailable,
        "capability-policy-unavailable",
    )
}
fn denied() -> PlatformError {
    error(
        PlatformErrorCode::PermissionDenied,
        "capability-policy-denied",
    )
}

fn preflight(bytes: &[u8]) -> Result<(), PlatformError> {
    crate::supply_chain::json::preflight(bytes, MAX_DOCUMENT_BYTES).map_err(|_| invalid())
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"-_.:/@".contains(&byte))
}

fn unique<T: Ord>(values: &[T], validate: impl Fn(&T) -> bool) -> bool {
    values.len() <= MAX_SET_ENTRIES
        && values.iter().all(validate)
        && values
            .iter()
            .collect::<std::collections::BTreeSet<_>>()
            .len()
            == values.len()
}

fn publication(value: &str) -> bool {
    value.len() == latent_core::PublicationId::TEXT_BYTES
        && value.parse::<latent_core::PublicationId>().is_ok()
}

fn operation(contract: &str, name: &str) -> bool {
    let operations: &[&str] = match contract {
        "latent:context/context@0.1.0" => &[
            "activation-id",
            "root-activation-id",
            "parent-activation-id",
            "principal",
            "trace",
            "deadline-unix-millis",
            "remaining-budget",
            "metadata",
        ],
        "latent:log/log@0.1.0" => &["write"],
        "latent:clock/monotonic@0.1.0" => &["now-nanos"],
        "latent:clock/wall@0.1.0" => &["now-unix-millis"],
        "latent:random/random@0.1.0" => &["bytes", "u64-value"],
        "latent:blob/blob@0.1.0" => &["create", "open", "write", "read", "seal", "close"],
        "latent:secrets/reader@0.1.0" => &["read"],
        "latent:events/publisher@0.2.0" => &["publish"],
        "latent:http/client@0.2.0" => &["send"],
        "latent:telemetry/custom@0.1.0" => &["emit-metric"],
        "latent:service/invoke@0.1.0" => &["call"],
        _ => return false,
    };
    operations.contains(&name)
}
