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

// The original audit schema bounds every copied source before allocation.
// This checks borrowed authority data; names never construct a budget owner.
pub(super) fn preflight(
    core: &SessionCore,
    index: usize,
    operation: &str,
) -> Result<(), PlatformError> {
    let binding = core.plan.bindings.get(index).ok_or_else(denied)?;
    let target = &core.plan.target;
    let token = |text: &str, maximum: usize| -> Result<(), PlatformError> {
        if text.is_empty()
            || text.len() > maximum
            || text.chars().any(char::is_control)
            || text.trim() != text
        {
            Err(denied())
        } else {
            Ok(())
        }
    };
    token(&target.tenant.0, 512)?;
    token(&core.principal.subject, 512)?;
    for text in [
        &core.activation_id.0,
        &core.root_activation_id.0,
        &target.service.0,
        &binding.provider.profile,
    ] {
        token(text, 128)?;
    }
    if let Some(parent) = &core.parent_activation_id {
        token(&parent.0, 128)?;
    }
    token(&target.revision.0, 256)?;
    if let Some(deployment) = &target.deployment {
        token(&deployment.0, 256)?;
    }
    token(operation, 64)?;
    token(&binding.provider.capability, 128)?;
    if target.release.0.len() != 71 || binding.provider.digest.len() != 71 {
        return Err(denied());
    }
    if !matches!(
        core.principal.kind,
        PrincipalKind::User
            | PrincipalKind::Service
            | PrincipalKind::Node
            | PrincipalKind::Trigger
            | PrincipalKind::Administrator
    ) {
        return Err(denied());
    }
    let revision = binding.policies.binding_revision();
    token(revision.id, 128)?;
    if revision.digest.len() != 71 || revision.revision == 0 {
        return Err(denied());
    }
    let mut count = 0;
    for revision in binding.policies.policy_revisions() {
        count += 1;
        if count > 8 {
            return Err(denied());
        }
        token(revision.id, 128)?;
        if revision.digest.len() != 71 || revision.revision == 0 {
            return Err(denied());
        }
    }
    if count == 0 {
        return Err(denied());
    }
    Ok(())
}
fn operation_id(id: u64) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut text = *b"capability-0000000000000000";
    for index in 0..16 {
        text[11 + index] = HEX[((id >> (4 * (15 - index))) & 15) as usize];
    }
    std::str::from_utf8(&text)
        .expect("ASCII operation identity")
        .to_owned()
}

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
    preflight(core, index, operation)?;
    let count = binding.policies.policy_revisions().count();
    let mut policies = Vec::with_capacity(count);
    for source in binding.policies.policy_revisions() {
        policies.push(revision(source)?);
    }
    let context = AuditCapabilityContext {
        activation: core.activation_id.0.clone(),
        parent_activation: core.parent_activation_id.as_ref().map(|id| id.0.clone()),
        root_activation: core.root_activation_id.0.clone(),
        service: target.service.0.clone(),
        binding_definition_digest: binding.definition_digest.clone().ok_or_else(denied)?,
        binding: revision(binding.policies.binding_revision())?,
        policies,
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
        operation_id: operation_id(id),
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
        ResourceTarget::Stream { .. } => AuditCapabilityResourceClass::Stream,
        ResourceTarget::Blob { .. } => AuditCapabilityResourceClass::Blob,
        ResourceTarget::Secrets { .. } => AuditCapabilityResourceClass::Secrets,
        ResourceTarget::Events { .. } => AuditCapabilityResourceClass::Events,
        ResourceTarget::Telemetry { .. } => AuditCapabilityResourceClass::Telemetry,
        ResourceTarget::Service { .. } => AuditCapabilityResourceClass::Service,
        ResourceTarget::State { .. } => AuditCapabilityResourceClass::State,
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
        ResourceTarget::Stream { endpoint } => endpoint.validate().is_ok(),
        ResourceTarget::Secrets { reference } => reference.len() <= 128,
        ResourceTarget::Events { subject } => subject.len() <= 128,
        ResourceTarget::Telemetry { name } => name.len() <= 128,
        ResourceTarget::Service {
            service,
            publication,
        } => service.len() <= 128 && publication.len() <= 128,
        ResourceTarget::State {
            namespace,
            incarnation,
            entity,
            recovery_scope,
            result_policy,
            ..
        } => {
            namespace.len() <= 256
                && incarnation != 0
                && entity.is_none_or(|value| value.len() <= 256)
                && recovery_scope.len() <= 256
                && result_policy.len() <= 256
        }
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
        ResourceTarget::Stream { endpoint } => {
            part(b"stream");
            part(endpoint.host.as_bytes());
            part(&endpoint.port.to_le_bytes());
            part(match endpoint.transport {
                latent_policy::capability::StreamTransport::Tcp => b"tcp",
                latent_policy::capability::StreamTransport::HostTls => b"host-tls",
            });
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
        ResourceTarget::State {
            namespace,
            incarnation,
            entity,
            recovery_kind,
            recovery_scope,
            result_policy,
        } => {
            part(b"state");
            part(namespace.as_bytes());
            part(&incarnation.to_le_bytes());
            part(&[u8::from(entity.is_some())]);
            part(entity.unwrap_or_default().as_bytes());
            part(&[match recovery_kind {
                latent_policy::capability::RecoveryScopeKind::OriginalCaller => 1,
                latent_policy::capability::RecoveryScopeKind::ServiceIntegration => 2,
                latent_policy::capability::RecoveryScopeKind::Delegated => 3,
                latent_policy::capability::RecoveryScopeKind::Shared => 4,
            }]);
            part(recovery_scope.as_bytes());
            part(result_policy.as_bytes());
        }
    }
    part(input);
    if let Some(typed) = typed {
        part(b"typed");
        part(&typed.0);
    }
    let hash = digest.finalize();
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut text = [b'0'; 71];
    text[..7].copy_from_slice(b"sha256:");
    for (index, byte) in hash.iter().enumerate() {
        text[7 + index * 2] = HEX[usize::from(byte >> 4)];
        text[8 + index * 2] = HEX[usize::from(byte & 15)];
    }
    std::str::from_utf8(&text)
        .expect("ASCII digest")
        .parse()
        .expect("SHA-256 digest")
}
