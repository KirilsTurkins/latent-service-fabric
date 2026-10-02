//! Owned capture for fixed-worker activation contexts. It retains original row
//! stamps and a real bounded read lease, never reusable authentication tokens.
use super::{
    denied, CapabilityCeiling, EvaluationInput, PolicySnapshot, PolicyStore, ReleaseUseEligibility,
    ResourceTarget, SealedPolicyDecision,
};
use crate::capability::ResourceRequest;
use latent_core::{InvocationPrincipal, Metadata, PlatformError};
use std::sync::Arc;

struct Input {
    principal: InvocationPrincipal,
    service: String,
    publication: String,
    capability: String,
    operation: String,
    resource: ResourceRequest,
}
impl Input {
    fn borrowed(&self) -> EvaluationInput<'_> {
        EvaluationInput {
            principal: &self.principal,
            service: &self.service,
            publication: &self.publication,
            capability: &self.capability,
            operation: &self.operation,
            resource: self.resource.target(),
        }
    }
}

/// Only a configured policy owner can capture this from a still-current sealed
/// decision. Metadata clones do not renew the original revisions/publication.
pub struct OwnedPolicyDecision {
    snapshot: PolicySnapshot,
    publication: ReleaseUseEligibility,
    input: Input,
    ceiling: CapabilityCeiling,
    require_audit: bool,
}
impl OwnedPolicyDecision {
    #[must_use]
    pub const fn requires_audit(&self) -> bool {
        self.require_audit
    }

    fn borrowed(&self) -> SealedPolicyDecision<'_> {
        SealedPolicyDecision {
            snapshot: &self.snapshot,
            publication: &self.publication,
            input: self.input.borrowed(),
            ceiling: self.ceiling,
            require_audit: self.require_audit,
        }
    }
}
impl PolicyStore {
    pub fn retain_decision(
        &self,
        decision: &SealedPolicyDecision<'_>,
    ) -> Result<OwnedPolicyDecision, PlatformError> {
        let mut captured = None;
        self.with_current(decision, &mut |actual, ceiling| {
            let original = decision.snapshot;
            let lease = original.owner.lease()?;
            let resource = own_resource(actual.resource);
            captured = Some(OwnedPolicyDecision {
                snapshot: PolicySnapshot {
                    owner: Arc::clone(&original.owner),
                    tenant: original.tenant.clone(),
                    policies: original.policies.clone(),
                    binding: original.binding.clone(),
                    lease,
                },
                publication: decision.publication.clone(),
                input: Input {
                    principal: InvocationPrincipal {
                        subject: actual.principal.subject.clone(),
                        kind: actual.principal.kind,
                        tenant: actual.principal.tenant.clone(),
                        service: actual.principal.service.clone(),
                        claims: Metadata::new(),
                    },
                    service: actual.service.into(),
                    publication: actual.publication.into(),
                    capability: actual.capability.into(),
                    operation: actual.operation.into(),
                    resource,
                },
                ceiling,
                require_audit: decision.require_audit,
            });
            Ok(())
        })?;
        captured.ok_or_else(denied)
    }

    pub fn with_captured(
        &self,
        captured: &OwnedPolicyDecision,
        operation: &SealedPolicyDecision<'_>,
        action: &mut dyn FnMut(&[&EvaluationInput<'_>]) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.with_current_decisions(&[&captured.borrowed(), operation], action)
    }

    /// Recheck the original retained owner, row stamps and publication under the
    /// existing short currentness fence. This does not acquire a replacement
    /// grant or expose a reusable borrowed authorization object. The callback
    /// must not wait, perform I/O, call guests or recursively enter this fence.
    pub fn with_retained_decision(
        &self,
        captured: &OwnedPolicyDecision,
        action: &mut dyn FnMut(
            &EvaluationInput<'_>,
            CapabilityCeiling,
        ) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.with_current(&captured.borrowed(), action)
    }

    /// Recheck several original retained decisions under one policy/publication
    /// fence. This preserves the same lock order as `with_current_decisions`;
    /// callbacks must be short and must not perform I/O or enter another fence.
    pub fn with_retained_decisions(
        &self,
        captured: &[&OwnedPolicyDecision],
        action: &mut dyn FnMut(&[&EvaluationInput<'_>]) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if captured.is_empty() || captured.len() > 8 {
            return Err(denied());
        }
        let borrowed: Vec<_> = captured
            .iter()
            .map(|decision| decision.borrowed())
            .collect();
        let references: Vec<_> = borrowed.iter().collect();
        self.with_current_decisions(&references, action)
    }
}

fn own_resource(resource: ResourceTarget<'_>) -> ResourceRequest {
    match resource {
        ResourceTarget::Context => ResourceRequest::Context,
        ResourceTarget::Clock => ResourceRequest::Clock,
        ResourceTarget::Random => ResourceRequest::Random,
        ResourceTarget::Log { level } => ResourceRequest::Log {
            level: level.into(),
        },
        ResourceTarget::Http {
            origin,
            method,
            path,
        } => ResourceRequest::Http {
            origin: origin.clone(),
            method: method.into(),
            path: path.into(),
        },
        ResourceTarget::Blob { namespace } => ResourceRequest::Blob {
            namespace: namespace.into(),
        },
        ResourceTarget::Secrets { reference } => ResourceRequest::Secrets {
            reference: reference.into(),
        },
        ResourceTarget::Events { subject } => ResourceRequest::Events {
            subject: subject.into(),
        },
        ResourceTarget::Telemetry { name } => ResourceRequest::Telemetry { name: name.into() },
        ResourceTarget::Service {
            service,
            publication,
        } => ResourceRequest::Service {
            service: service.into(),
            publication: publication.into(),
        },
        ResourceTarget::State {
            namespace,
            incarnation,
            entity,
            recovery_kind,
            recovery_scope,
            result_policy,
        } => ResourceRequest::State {
            namespace: namespace.into(),
            incarnation,
            entity: entity.map(str::to_owned),
            recovery_kind,
            recovery_scope: recovery_scope.into(),
            result_policy: result_policy.into(),
        },
    }
}
