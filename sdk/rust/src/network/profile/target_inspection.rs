use super::{
    model,
    requests::{Context, RequestProfile},
    responses::ResponseProfile,
    FailureKind, RpcFailure,
};
use latent_rpc::control::v1 as wire;
use std::collections::BTreeSet;

fn id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 512
        && !value.chars().any(|c| c.is_control() || c.is_whitespace())
}
fn hex(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|c| matches!(c,b'0'..=b'9'|b'a'..=b'f'))
}
fn digest(value: &str, prefix: &str) -> bool {
    value.strip_prefix(prefix).is_some_and(hex)
}
fn publication(value: &wire::PublicationRef, tenant: &str) -> bool {
    value.tenant == tenant && value.id.parse::<latent_core::PublicationId>().is_ok()
}

impl RequestProfile for model::InspectHttpTargetRequest {
    const MAXIMUM_REQUEST: usize = 8 * 1024;
    const MAXIMUM_RESPONSE: usize = 64 * 1024;
    fn validate(&self, context: &mut Context, tenant: &str) -> Result<(), RpcFailure> {
        if [&self.service, &self.contract, &self.function]
            .into_iter()
            .any(|v| !id(v))
            || [&self.route, &self.revision_id, &self.routing_key]
                .into_iter()
                .flatten()
                .any(|v| !id(v))
            || self.maximum_wait_millis > 30_000
            || self.publication.as_ref().is_some_and(|v| {
                v.tenant != tenant || v.id.parse::<latent_core::PublicationId>().is_err()
            })
        {
            return Err(RpcFailure::local(FailureKind::InvalidRequest));
        }
        // Capture validated, bounded selectors before the transport awaits a reply.
        context.target_inspection = Some(self.clone());
        Ok(())
    }
}

impl ResponseProfile for wire::InspectHttpTargetResponse {
    fn validate(&self, context: &Context, tenant: &str) -> Result<bool, RpcFailure> {
        let invalid = || RpcFailure::local(FailureKind::InvalidResponse);
        let request = context.target_inspection.as_ref().ok_or_else(invalid)?;
        if self.schema_version != 1
            || self.tenant != tenant
            || self.service != request.service
            || self.contract != request.contract
            || self.function != request.function
            || request.route.as_ref().is_some_and(|v| v != &self.route)
            || !id(&self.route)
            || self.live_grants_checked
            || self.candidates.len() > 32
        {
            return Err(invalid());
        }
        let mut revisions = BTreeSet::new();
        for candidate in &self.candidates {
            if !revisions.insert(&candidate.revision_id) {
                return Err(invalid());
            }
            validate_candidate(candidate, request, tenant, self.state)?;
        }
        if self
            .selected_revision_id
            .as_ref()
            .is_some_and(|v| request.routing_key.is_none() || !revisions.contains(v))
        {
            return Err(invalid());
        }
        // Unknown enum numbers remain descriptive and never establish eligibility.
        Ok(true)
    }
}

fn validate_candidate(
    candidate: &wire::TargetCandidate,
    request: &model::InspectHttpTargetRequest,
    tenant: &str,
    state: i32,
) -> Result<(), RpcFailure> {
    let invalid = || RpcFailure::local(FailureKind::InvalidResponse);
    if !id(&candidate.deployment_id)
        || !id(&candidate.revision_id)
        || !digest(&candidate.component_digest, "sha256:")
        || candidate
            .package_digest
            .as_ref()
            .is_some_and(|v| !digest(v, "sha256:"))
        || request
            .revision_id
            .as_ref()
            .is_some_and(|v| v != &candidate.revision_id)
        || candidate.routing_weight > u32::from(u16::MAX)
        || candidate.reasons.len() > 16
        || candidate.dependencies.len() > 32
        || candidate.http_bindings.len() > 32
        || [
            candidate.publication.as_ref(),
            candidate.requested_publication.as_ref(),
        ]
        .into_iter()
        .flatten()
        .any(|v| !publication(v, tenant))
        || request.publication.as_ref().is_some_and(|v| {
            candidate
                .publication
                .as_ref()
                .is_none_or(|actual| actual.id != v.id || actual.tenant != v.tenant)
        })
    {
        return Err(invalid());
    }
    if candidate.publication_kind.as_ref().is_some_and(|v| {
        !matches!(v.as_str(), "capsule" | "browser-assets" | "ssr-package")
            || candidate.package_digest.is_none()
    }) {
        return Err(invalid());
    }
    for binding in &candidate.http_bindings {
        if !id(&binding.id)
            || binding.generation == 0
            || !matches!(
                binding.state.as_str(),
                "configured-current" | "deployment-changed"
            )
        {
            return Err(invalid());
        }
    }
    for dependency in &candidate.dependencies {
        validate_dependency(dependency)?;
    }
    let preparation = candidate.preparation.as_ref().ok_or_else(invalid)?;
    validate_preparation(preparation, request)?;
    if candidate.eligible
        && (state != 1
            || !candidate.export_compatible
            || candidate.publication.is_none()
            || candidate.package_digest.is_none()
            || candidate.publication_generation.is_none()
            || candidate.routing_weight == 0
            || candidate.reasons != [1]
            || !matches!(preparation.state, 1 | 4)
            || candidate
                .dependencies
                .iter()
                .any(|v| v.state != "configured-current"))
    {
        return Err(invalid());
    }
    Ok(())
}

fn validate_dependency(dependency: &wire::TargetDependency) -> Result<(), RpcFailure> {
    let invalid = || RpcFailure::local(FailureKind::InvalidResponse);
    if !id(&dependency.capability)
        || !id(&dependency.provider_profile)
        || !id(&dependency.configuration_digest)
        || !hex(&dependency.policy_identity_digest)
        || dependency.policies.len() > 32
        || dependency.binding.is_none()
        || !matches!(
            dependency.state.as_str(),
            "configured-current"
                | "policy-changed-or-revoked"
                | "provider-unavailable"
                | "publication-unavailable"
                | "route-changed-or-unavailable"
                | "inspection-indeterminate"
        )
    {
        return Err(invalid());
    }
    for revision in dependency.binding.iter().chain(&dependency.policies) {
        if !id(&revision.id) || !id(&revision.digest) {
            return Err(invalid());
        }
    }
    Ok(())
}

fn validate_preparation(
    preparation: &wire::TargetPreparation,
    request: &model::InspectHttpTargetRequest,
) -> Result<(), RpcFailure> {
    let invalid = || RpcFailure::local(FailureKind::InvalidResponse);
    if (!request.include_preparation && preparation.state != 4)
        || (request.include_preparation && preparation.state == 4)
        || preparation
            .imports
            .len()
            .saturating_add(preparation.type_imports.len())
            > 64
        || preparation.exports.len() > 128
        || [
            &preparation.engine_version,
            &preparation.target_triple,
            &preparation.cpu_feature_set,
        ]
        .into_iter()
        .flatten()
        .any(|v| !id(v))
        || preparation
            .engine_configuration_digest
            .as_ref()
            .is_some_and(|v| !digest(v, "blake3:"))
        || preparation
            .sealed_metadata_fingerprint
            .as_ref()
            .is_some_and(|v| !hex(v))
        || preparation
            .imports
            .iter()
            .chain(&preparation.type_imports)
            .any(|v| !id(v))
        || preparation
            .exports
            .iter()
            .any(|v| !id(&v.contract) || !id(&v.function))
        || preparation.diagnostic.as_ref().is_some_and(|v| {
            v.schema_version != 1 || v.profile_digest.as_ref().is_some_and(|d| !hex(d))
        })
    {
        return Err(invalid());
    }
    if preparation.state == 1
        && (preparation.profile.is_none()
            || preparation.engine_version.is_none()
            || preparation.engine_configuration_digest.is_none()
            || preparation.target_triple.is_none()
            || preparation.cpu_feature_set.is_none()
            || preparation.declared_budget.is_none()
            || preparation.import_count
                != Some((preparation.imports.len() + preparation.type_imports.len()) as u64)
            || preparation.function_count != Some(preparation.exports.len() as u64)
            || preparation.hostcall_fuel.is_none()
            || preparation.maximum_lifted_bytes.is_none()
            || preparation.maximum_type_nodes.is_none())
    {
        return Err(invalid());
    }
    Ok(())
}
