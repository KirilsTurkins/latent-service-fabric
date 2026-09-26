use super::{domain, enums, proto};

fn revision(value: domain::AuditCapabilityRevision) -> proto::AuditCapabilityRevision {
    proto::AuditCapabilityRevision {
        id: value.id,
        revision: value.revision,
        digest: value.digest.into_string(),
    }
}
pub(super) fn context(value: domain::AuditCapabilityContext) -> proto::AuditCapabilityContext {
    proto::AuditCapabilityContext {
        activation: value.activation,
        parent_activation: value.parent_activation,
        root_activation: value.root_activation,
        service: value.service,
        binding_definition_digest: value.binding_definition_digest.into_string(),
        binding: Some(revision(value.binding)),
        policies: value.policies.into_iter().map(revision).collect(),
        provider_profile: value.provider_profile,
        provider_configuration_digest: value.provider_configuration_digest.into_string(),
        provider_configuration_epoch: value.provider_configuration_epoch,
        capability: value.capability,
        operation: value.operation,
        resource_class: enums::capability_resource(value.resource_class),
        request: value
            .request
            .map(|value| proto::AuditCapabilityRequestDigest {
                scope: enums::capability_digest_scope(value.scope),
                digest: value.digest.into_string(),
            }),
        required: value.required,
        provider_outcome: value.provider_outcome.map(enums::provider_outcome),
    }
}
