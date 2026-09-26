use super::super::{lifecycle::conversion as lifecycle, selector};
use crate::management::{control_audit, proto, ManagementLimits, RequestBudget};
use latent_artifacts::{
    web::{WebOperationReceipt, WebPublicationStatus},
    ReleaseActor,
};
use latent_core::TenantId;
use tonic::Status;

pub(super) fn receipt(
    value: &WebOperationReceipt,
    replayed: bool,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<proto::WebOperationReceipt, Status> {
    value
        .validate()
        .map_err(|_| Status::internal("invalid web operation receipt"))?;
    if value.publication.scope.tenant() != Some(tenant) {
        return Err(Status::internal("web operation scope mismatch"));
    }
    budget.allocation::<proto::WebOperationReceipt>(1)?;
    selector::charge(Some(&value.publication.id), tenant, budget, limits)?;
    budget.string(&value.operation_id, 128.min(limits.max_id_bytes))?;
    budget.allocation::<u8>(71)?;
    let actor = actor(&value.actor, budget, limits)?;
    Ok(proto::WebOperationReceipt {
        format_version: value.format_version,
        publication: Some(selector::owned(&value.publication.id, tenant)),
        operation_id: value.operation_id.clone(),
        action: lifecycle::release_lifecycle_action(value.action),
        actor: Some(actor),
        expected_generation: value.expected_generation,
        resulting_generation: value.resulting_generation,
        disposition: lifecycle::release_operation_disposition(value.disposition),
        reason: lifecycle::release_lifecycle_reason(value.reason),
        request_digest: value.request_digest.to_string(),
        replayed,
    })
}

pub(super) fn mutation(
    value: &latent_artifacts::web::WebMutationResult,
    tenant: &TenantId,
    limits: &ManagementLimits,
    audited: bool,
) -> Result<proto::WebMutationResponse, Status> {
    let mut budget = RequestBudget::for_response::<proto::WebMutationResponse>(limits)?;
    budget.allocation::<u8>(4096)?;
    if audited {
        control_audit::charge(&mut budget)?;
    }
    Ok(proto::WebMutationResponse {
        operation: Some(receipt(
            &value.receipt,
            value.replay,
            tenant,
            &mut budget,
            limits,
        )?),
        audit_ack: audited.then(control_audit::maximum),
    })
}

pub(super) fn status(
    value: &WebPublicationStatus,
    tenant: &TenantId,
    limits: &ManagementLimits,
) -> Result<proto::GetWebPublicationResponse, Status> {
    let record = &value.record;
    if record.publication.scope.tenant() != Some(tenant) {
        return Err(Status::internal("web publication scope mismatch"));
    }
    let mut budget = RequestBudget::for_response::<proto::GetWebPublicationResponse>(limits)?;
    budget.allocation::<proto::WebLifecycleRecord>(1)?;
    selector::charge(Some(&record.publication.id), tenant, &mut budget, limits)?;
    budget.allocation::<u8>(71 * (3 + usize::from(record.evidence_revision.is_some())))?;
    budget.string(&record.operation_id, 128.min(limits.max_id_bytes))?;
    let actor = actor(&record.actor, &mut budget, limits)?;
    let renderer = value
        .renderer
        .as_ref()
        .map(|renderer| {
            budget.allocation::<proto::WebRendererDescriptor>(1)?;
            budget.string(&renderer.digest, 128)?;
            budget.string(&renderer.profile_digest, 128)?;
            Ok::<_, Status>(proto::WebRendererDescriptor {
                component_digest: renderer.digest.clone(),
                profile: match renderer.profile {
                    latent_manifest::RendererProfile::WasmWebBufferedV1 => {
                        proto::WebRendererProfile::WasmWebBufferedV1
                    }
                    latent_manifest::RendererProfile::AngularSsrComponentV1 => {
                        proto::WebRendererProfile::AngularSsrComponentV1
                    }
                } as i32,
                profile_digest: renderer.profile_digest.clone(),
                component_bytes: renderer.size,
            })
        })
        .transpose()?;
    Ok(proto::GetWebPublicationResponse {
        record: Some(proto::WebLifecycleRecord {
            publication: Some(selector::owned(&record.publication.id, tenant)),
            package_digest: record.package.to_string(),
            web_manifest_digest: record.manifest.to_string(),
            assets_digest: record.assets.to_string(),
            state: lifecycle::release_lifecycle_state(record.state),
            generation: record.generation,
            actor: Some(actor),
            reason: lifecycle::release_lifecycle_reason(record.reason),
            operation_id: record.operation_id.clone(),
            evidence_revision_digest: record.evidence_revision.as_ref().map(ToString::to_string),
        }),
        eligibility: lifecycle::release_live_eligibility(value.eligibility),
        eligibility_reason: lifecycle::release_eligibility_reason(value.eligibility_reason),
        renderer,
    })
}

fn actor(
    value: &ReleaseActor,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<proto::ReleaseActor, Status> {
    budget.allocation::<proto::ReleaseActor>(1)?;
    budget.string(&value.subject, limits.max_id_bytes.min(256))?;
    Ok(proto::ReleaseActor {
        subject: value.subject.clone(),
        kind: lifecycle::release_actor_kind(value.kind),
    })
}
