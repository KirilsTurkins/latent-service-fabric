use super::*;
use crate::management::ManagementLimits;
use latent_artifacts::{
    PublicationDeletionRequest, PublicationReclamationContent, PublicationRetentionSnapshot,
    PublicationRetentionTarget, ReleaseActor,
};
use latent_core::TenantId;

fn target(value: &PublicationRetentionTarget) -> proto::PublicationMaintenanceTarget {
    proto::PublicationMaintenanceTarget {
        publication: Some(proto::PublicationRef {
            id: value.publication.id.as_str().to_owned(),
            tenant: value
                .publication
                .scope
                .tenant()
                .expect("validated tenant")
                .0
                .clone(),
        }),
        expected_generation: value.expected_generation,
    }
}
fn actor(value: &ReleaseActor) -> proto::ReleaseActor {
    proto::ReleaseActor {
        subject: value.subject.clone(),
        kind: super::super::lifecycle::conversion::release_actor_kind(value.kind),
    }
}
fn targets_budget(
    values: &[PublicationRetentionTarget],
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    if values.is_empty() || values.len() > 32 {
        return Err(Status::internal("invalid retained publication batch"));
    }
    budget.allocation::<proto::PublicationMaintenanceTarget>(values.len())?;
    for v in values {
        if v.publication.scope.tenant() != Some(tenant) || v.expected_generation == 0 {
            return Err(Status::internal(
                "retained publication scope or generation mismatch",
            ));
        }
        super::super::selector::charge(Some(&v.publication.id), tenant, budget, limits)?;
    }
    if values
        .windows(2)
        .any(|p| p[0].publication.id >= p[1].publication.id)
    {
        return Err(Status::internal("unordered retained publication batch"));
    }
    Ok(())
}
pub(super) fn selection_budget(
    value: &PublicationDeletionRequest,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    if value.scope.tenant() != Some(tenant) {
        return Err(Status::internal("retained publication tenant mismatch"));
    }
    budget.allocation::<proto::PublicationMaintenanceSelection>(1)?;
    budget.allocation::<u8>(32)?;
    budget.string(&value.operation_id, 128.min(limits.max_id_bytes))?;
    budget.string(&tenant.0, limits.max_id_bytes)?;
    targets_budget(&value.targets, tenant, budget, limits)
}
pub(super) fn selection(
    value: &PublicationDeletionRequest,
) -> proto::PublicationMaintenanceSelection {
    proto::PublicationMaintenanceSelection {
        operation_id: value.operation_id.clone(),
        catalog_fence: value.expected_catalog_fence.as_bytes().to_vec(),
        targets: value.targets.iter().map(target).collect(),
    }
}
pub(super) fn content(
    v: PublicationReclamationContent,
) -> Result<proto::PublicationReclamationAccounting, Status> {
    let count =
        |n: usize| u32::try_from(n).map_err(|_| Status::internal("invalid reclamation count"));
    Ok(proto::PublicationReclamationAccounting {
        publications: count(v.publications)?,
        publication_files: count(v.publication_files)?,
        publication_file_bytes: v.publication_file_bytes,
        selected_blobs: count(v.selected_blobs)?,
        last_reference_blobs: count(v.last_reference_blobs)?,
        last_reference_blob_bytes: v.last_reference_blob_bytes,
        shared_blobs_retained: count(v.shared_blobs_retained)?,
        shared_blob_bytes_retained: v.shared_blob_bytes_retained,
        bytes_hashed: v.bytes_hashed,
    })
}
pub(super) fn receipt(
    value: &Receipt,
    tenant: &TenantId,
    limits: &ManagementLimits,
) -> Result<proto::PublicationMaintenanceOperationReceipt, Status> {
    use proto::PublicationMaintenanceKind as K;
    let mut budget =
        RequestBudget::for_response::<proto::PublicationMaintenanceOperationReceipt>(limits)?;
    // At most one original request and output graph coexist. Charge its owned
    // strings/targets before cloning it into a shared typed conversion shape.
    let (scope, who, id, fence, targets) = match value {
        Receipt::Retention(v) => (
            &v.request.scope,
            &v.request.actor,
            &v.request.operation_id,
            v.request.expected_catalog_fence,
            &v.request.targets,
        ),
        Receipt::Deletion(v) => (
            &v.request.scope,
            &v.request.actor,
            &v.request.operation_id,
            v.request.expected_catalog_fence,
            &v.request.targets,
        ),
        Receipt::Reclamation(v) => (
            &v.request.deletion.scope,
            &v.request.deletion.actor,
            &v.request.deletion.operation_id,
            v.request.deletion.expected_catalog_fence,
            &v.request.deletion.targets,
        ),
    };
    if scope.tenant() != Some(tenant) {
        return Err(Status::internal("retained maintenance scope mismatch"));
    }
    budget.string(&tenant.0, limits.max_id_bytes)?;
    budget.string(&who.subject, 512.min(limits.max_string_bytes))?;
    budget.string(id, 128.min(limits.max_id_bytes))?;
    budget.allocation::<proto::ReleaseActor>(1)?;
    budget.allocation::<proto::PublicationMaintenanceCommand>(1)?;
    budget.allocation::<proto::PublicationMaintenanceSelection>(1)?;
    budget.allocation::<u8>(64)?;
    budget.allocation::<proto::PublicationReclamationAccounting>(1)?;
    targets_budget(targets, tenant, &mut budget, limits)?;
    let (
        kind,
        revision,
        reference_revision,
        reclaimed,
        current,
        maximum_files,
        maximum_bytes_hashed,
    ) = match value {
        Receipt::Retention(v) => (
            if v.request.action == latent_artifacts::PublicationRetentionAction::Pin {
                K::Pin
            } else {
                K::Unpin
            },
            v.revision,
            0,
            None,
            Vec::new(),
            0,
            0,
        ),
        Receipt::Deletion(v) => (
            K::Delete,
            v.revision,
            v.reference_revision,
            None,
            Vec::new(),
            0,
            0,
        ),
        Receipt::Reclamation(v) => (
            K::Reclaim,
            0,
            v.reference_revision,
            Some(content(v.content)?),
            v.request.expected_catalog_fence.as_bytes().to_vec(),
            u32::try_from(v.request.limits.maximum_files).map_err(|_| bounds::exhausted())?,
            v.request.limits.maximum_bytes_hashed,
        ),
    };
    Ok(proto::PublicationMaintenanceOperationReceipt {
        tenant: tenant.0.clone(),
        actor: Some(actor(who)),
        revision,
        reference_revision,
        reclaimed,
        command: Some(proto::PublicationMaintenanceCommand {
            kind: kind as i32,
            selection: Some(proto::PublicationMaintenanceSelection {
                operation_id: id.clone(),
                catalog_fence: fence.as_bytes().to_vec(),
                targets: targets.iter().map(target).collect(),
            }),
            reclamation_catalog_fence: current,
            maximum_files,
            maximum_bytes_hashed,
        }),
    })
}
pub(super) fn snapshot(
    value: &PublicationRetentionSnapshot,
    tenant: &TenantId,
    limits: &ManagementLimits,
) -> Result<proto::GetPublicationRetentionResponse, Status> {
    let mut budget = RequestBudget::for_response::<proto::GetPublicationRetentionResponse>(limits)?;
    budget.string(&tenant.0, limits.max_id_bytes)?;
    budget.allocation::<u8>(32)?;
    budget.sequence(&value.selections, 32)?;
    budget.allocation::<proto::PublicationRetentionEntry>(value.selections.len())?;
    // Validate/charge every source before constructing the output graph.
    for v in &value.selections {
        targets_budget(std::slice::from_ref(&v.target), tenant, &mut budget, limits)?;
        if let Some(pin) = &v.pin {
            if pin.publication != v.target.publication
                || pin.pinned_generation == 0
                || pin.pinned_generation > v.target.expected_generation
            {
                return Err(Status::internal("invalid retained publication pin"));
            }
            budget.allocation::<proto::PublicationRetentionPinRecord>(1)?;
            budget.allocation::<proto::ReleaseActor>(1)?;
            budget.string(&pin.actor.subject, 512.min(limits.max_string_bytes))?;
            budget.string(&pin.operation_id, 128.min(limits.max_id_bytes))?;
        }
    }
    Ok(proto::GetPublicationRetentionResponse {
        tenant: tenant.0.clone(),
        catalog_fence: value.catalog_fence.as_bytes().to_vec(),
        entries: value
            .selections
            .iter()
            .map(|v| proto::PublicationRetentionEntry {
                target: Some(target(&v.target)),
                pin: v
                    .pin
                    .as_ref()
                    .map(|p| proto::PublicationRetentionPinRecord {
                        pinned_generation: p.pinned_generation,
                        actor: Some(actor(&p.actor)),
                        operation_id: p.operation_id.clone(),
                    }),
            })
            .collect(),
    })
}
