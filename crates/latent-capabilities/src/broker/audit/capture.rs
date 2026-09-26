use super::{
    denied, AuditIdentities, AuditOperationAttempt, CapabilityRequestDigest, Digest, PlatformError,
    SessionCore, Sha256,
};
use latent_audit::{
    AuditActorIdentity, AuditActorKind, AuditCapabilityContext, AuditCapabilityDigestScope,
    AuditCapabilityRequestDigest, AuditCapabilityResourceClass, AuditCapabilityRevision,
    AuditControlAction, AuditScope,
};
use latent_core::{ArtifactBlobDigest, PrincipalKind};
use latent_policy::capability::ResourceTarget;

pub(super) fn attempt(
    core: &SessionCore,
    index: usize,
    operation: &str,
    resource: ResourceTarget<'_>,
    digest: ArtifactBlobDigest,
    required: bool,
    id: u64,
) -> Result<AuditOperationAttempt, PlatformError> {
    let plan = &core.plan;
    let target = &plan.target;
    let binding = &plan.bindings[index];
    let provider = &binding.provider;
    let revision = |value: latent_policy::capability::CapabilityPolicyRevision<'_>| -> Result<_, PlatformError> {
        Ok(AuditCapabilityRevision {
            id: value.id.into(), revision: value.revision, digest: value.digest.parse().map_err(|_| denied())?,
        })
    };
    let context = AuditCapabilityContext {
        activation: core.activation_id.0.clone(),
        parent_activation: core.parent_activation_id.as_ref().map(|id| id.0.clone()),
        root_activation: core.root_activation_id.0.clone(),
        service: target.service.0.clone(),
        binding_definition_digest: binding.definition_digest.clone().ok_or_else(denied)?,
        binding: revision(binding.policies.binding_revision())?,
        policies: binding
            .policies
            .policy_revisions()
            .map(revision)
            .collect::<Result<_, _>>()?,
        provider_profile: provider.profile.clone(),
        provider_configuration_digest: provider.digest.parse().map_err(|_| denied())?,
        provider_configuration_epoch: provider.epoch,
        capability: provider.capability.clone(),
        operation: operation.into(),
        resource_class: class(resource),
        request: Some(AuditCapabilityRequestDigest {
            scope: AuditCapabilityDigestScope::ProviderRequest,
            digest: digest.clone(),
        }),
        required,
        provider_outcome: None,
    };
    Ok(AuditOperationAttempt {
        expected_state_version: None,
        expected_rollback_target_generation: None,
        scope: AuditScope::Tenant(target.tenant.clone()),
        actor: AuditActorIdentity {
            kind: match core.principal.kind {
                PrincipalKind::User => AuditActorKind::User,
                PrincipalKind::Service => AuditActorKind::Service,
                PrincipalKind::Node => AuditActorKind::Node,
                PrincipalKind::Trigger => AuditActorKind::Trigger,
                PrincipalKind::Administrator => AuditActorKind::Administrator,
                _ => return Err(denied()),
            },
            subject: core.principal.subject.clone(),
        },
        operation_id: format!("capability-{id:016x}"),
        request_digest: digest,
        preview_receipt_digest: None,
        action: AuditControlAction::CapabilityCall,
        identities: AuditIdentities {
            publication: Some(target.publication.clone()),
            component: Some(target.release.clone()),
            package: plan.publication.package().cloned(),
            deployment: target.deployment.clone(),
            revision: Some(target.revision.clone()),
            route_generation: Some(target.generation),
            lifecycle_generation: Some(plan.publication.generation()),
            capability: Some(context),
            ..Default::default()
        },
        replay: false,
        expected_generation: None,
        expected_deployment_generation: None,
        expected_rollout_revision: None,
        occurred_at_unix_millis: core.owner.clock.sample().unix_millis(),
    })
}
pub(super) fn class(value: ResourceTarget<'_>) -> AuditCapabilityResourceClass {
    match value {
        ResourceTarget::Context => AuditCapabilityResourceClass::Context,
        ResourceTarget::Clock => AuditCapabilityResourceClass::Clock,
        ResourceTarget::Random => AuditCapabilityResourceClass::Random,
        ResourceTarget::Log { .. } => AuditCapabilityResourceClass::Log,
        ResourceTarget::Http { .. } => AuditCapabilityResourceClass::Http,
        ResourceTarget::Blob { .. } => AuditCapabilityResourceClass::Blob,
        ResourceTarget::Secrets { .. } => AuditCapabilityResourceClass::Secrets,
        ResourceTarget::Events { .. } => AuditCapabilityResourceClass::Events,
        ResourceTarget::Telemetry { .. } => AuditCapabilityResourceClass::Telemetry,
        ResourceTarget::Service { .. } => AuditCapabilityResourceClass::Service,
    }
}
pub(super) fn bounded_resource(value: ResourceTarget<'_>) -> bool {
    match value {
        ResourceTarget::Context | ResourceTarget::Clock | ResourceTarget::Random => true,
        ResourceTarget::Log { level } => level.len() <= 16,
        ResourceTarget::Http {
            origin,
            method,
            path,
        } => {
            origin.scheme.len() <= 8
                && origin.host.len() <= 253
                && method.len() <= 16
                && path.len() <= 2048
        }
        ResourceTarget::Blob { namespace } => namespace.len() <= 128,
        ResourceTarget::Secrets { reference } => reference.len() <= 128,
        ResourceTarget::Events { subject } => subject.len() <= 128,
        ResourceTarget::Telemetry { name } => name.len() <= 128,
        ResourceTarget::Service {
            service,
            publication,
        } => service.len() <= 128 && publication.len() <= 128,
    }
}

pub(in crate::broker) fn request_digest(
    operation: &str,
    resource: ResourceTarget<'_>,
    input: &[u8],
    typed: Option<CapabilityRequestDigest>,
) -> ArtifactBlobDigest {
    let mut digest = Sha256::new();
    let mut part = |value: &[u8]| {
        digest.update((value.len() as u64).to_le_bytes());
        digest.update(value);
    };
    part(b"lsf-capability-provider-request-v1");
    part(operation.as_bytes());
    match resource {
        ResourceTarget::Context => part(b"context"),
        ResourceTarget::Clock => part(b"clock"),
        ResourceTarget::Random => part(b"random"),
        ResourceTarget::Log { level } => {
            part(b"log");
            part(level.as_bytes());
        }
        ResourceTarget::Http {
            origin,
            method,
            path,
        } => {
            part(b"http");
            part(origin.scheme.as_bytes());
            part(origin.host.as_bytes());
            part(&origin.port.to_le_bytes());
            part(method.as_bytes());
            part(path.as_bytes());
        }
        ResourceTarget::Blob { namespace } => {
            part(b"blob");
            part(namespace.as_bytes());
        }
        ResourceTarget::Secrets { reference } => {
            part(b"secrets");
            part(reference.as_bytes());
        }
        ResourceTarget::Events { subject } => {
            part(b"events");
            part(subject.as_bytes());
        }
        ResourceTarget::Telemetry { name } => {
            part(b"telemetry");
            part(name.as_bytes());
        }
        ResourceTarget::Service {
            service,
            publication,
        } => {
            part(b"service");
            part(service.as_bytes());
            part(publication.as_bytes());
        }
    }
    part(input);
    if let Some(typed) = typed {
        part(b"typed");
        part(&typed.0);
    }
    let hash = digest.finalize();
    format!("sha256:{hash:x}").parse().expect("SHA-256 digest")
}
