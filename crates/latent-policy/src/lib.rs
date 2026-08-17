//! Policy evaluation and admission decision interfaces.

#![forbid(unsafe_code)]

use latent_core::{BoxFuture, InvocationPrincipal, Metadata, PlatformError, PolicyId};
use latent_manifest::{CapsuleManifest, DeploymentManifest, PolicyManifest};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PolicyDecisionKind {
    Allow,
    Deny,
    Indeterminate,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PolicyReason {
    pub code: String,
    pub message: String,
    pub attributes: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PolicyDecision {
    pub kind: PolicyDecisionKind,
    pub reasons: Vec<PolicyReason>,
    pub obligations: Metadata,
    pub policy_version: String,
}

#[derive(Debug, Clone)]
pub enum PolicyInput<'a> {
    ReleaseAdmission {
        capsule: &'a CapsuleManifest,
        deployment: &'a DeploymentManifest,
    },
    Invocation {
        principal: &'a InvocationPrincipal,
        action: &'a str,
        attributes: &'a Metadata,
    },
    CapabilityGrant {
        principal: &'a InvocationPrincipal,
        capability: &'a str,
        attributes: &'a Metadata,
    },
    Placement {
        attributes: &'a Metadata,
    },
}

pub trait PolicyEngine: Send + Sync {
    fn evaluate<'a>(
        &'a self,
        input: PolicyInput<'a>,
    ) -> BoxFuture<'a, Result<PolicyDecision, PlatformError>>;
}

pub trait PolicyRepository: Send + Sync {
    fn get<'a>(
        &'a self,
        id: &'a PolicyId,
    ) -> BoxFuture<'a, Result<Option<PolicyManifest>, PlatformError>>;

    fn put<'a>(
        &'a self,
        policy: PolicyManifest,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;

    fn delete<'a>(&'a self, id: &'a PolicyId) -> BoxFuture<'a, Result<(), PlatformError>>;
}
