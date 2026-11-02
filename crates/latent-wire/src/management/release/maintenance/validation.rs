use super::*;
use crate::management::{identifier, ManagementLimits};
use latent_artifacts::{
    LifecycleScope, PublicationDeletionRequest, PublicationReclamationLimits,
    PublicationReclamationRequest, PublicationRef, PublicationRetentionAction,
    PublicationRetentionFence, PublicationRetentionRequest, PublicationRetentionTarget,
    ReleaseActor, ReleaseActorKind,
};
use latent_core::TenantId;

fn invalid() -> Status {
    Status::invalid_argument("publication-maintenance-invalid-selection")
}
pub(super) fn kind(value: i32) -> Result<proto::PublicationMaintenanceKind, Status> {
    proto::PublicationMaintenanceKind::try_from(value)
        .ok()
        .filter(|v| *v != proto::PublicationMaintenanceKind::Unspecified)
        .ok_or_else(invalid)
}
pub(super) fn operation(
    id: &String,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    budget.string(id, 128.min(limits.max_id_bytes))?;
    identifier(id, 128.min(limits.max_id_bytes))
}
fn fence(value: &Vec<u8>, budget: &mut RequestBudget) -> Result<PublicationRetentionFence, Status> {
    budget.bytes(value, 32)?;
    Ok(PublicationRetentionFence::from_bytes(
        value.as_slice().try_into().map_err(|_| invalid())?,
    ))
}
pub(super) fn publications(
    values: &Vec<proto::PublicationRef>,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<Vec<PublicationRef>, Status> {
    if values.is_empty() {
        return Err(invalid());
    }
    budget.sequence(values, 32)?;
    budget.allocation::<PublicationRef>(values.len())?;
    let mut result = Vec::with_capacity(values.len());
    for value in values {
        let publication = super::super::selector::request(Some(value), tenant, budget, limits)?;
        if result
            .last()
            .is_some_and(|previous: &PublicationRef| previous.id >= publication.id)
        {
            return Err(invalid());
        }
        result.push(publication);
    }
    Ok(result)
}
pub(super) fn selection(
    value: Option<&proto::PublicationMaintenanceSelection>,
    principal: &InvocationPrincipal,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<PublicationDeletionRequest, Status> {
    let v = value.ok_or_else(invalid)?;
    let tenant = principal.tenant.as_ref().expect("authenticated tenant");
    budget.allocation::<proto::PublicationMaintenanceSelection>(1)?;
    operation(&v.operation_id, budget, limits)?;
    let catalog_fence = fence(&v.catalog_fence, budget)?;
    if v.targets.is_empty() {
        return Err(invalid());
    }
    budget.sequence(&v.targets, 32)?;
    budget.allocation::<PublicationRetentionTarget>(v.targets.len())?;
    let mut targets = Vec::with_capacity(v.targets.len());
    for target in &v.targets {
        if target.expected_generation == 0 {
            return Err(invalid());
        }
        let publication =
            super::super::selector::request(target.publication.as_ref(), tenant, budget, limits)?;
        if targets
            .last()
            .is_some_and(|previous: &PublicationRetentionTarget| {
                previous.publication.id >= publication.id
            })
        {
            return Err(invalid());
        }
        targets.push(PublicationRetentionTarget {
            publication,
            expected_generation: target.expected_generation,
        });
    }
    Ok(PublicationDeletionRequest {
        scope: LifecycleScope::Tenant(tenant.clone()),
        actor: ReleaseActor {
            subject: principal.subject.clone(),
            kind: ReleaseActorKind::try_from(principal.kind)
                .map_err(|_| Status::permission_denied("unsupported publication actor"))?,
        },
        operation_id: v.operation_id.clone(),
        expected_catalog_fence: catalog_fence,
        targets,
    })
}
pub(super) fn work(files: u32, bytes: u64) -> Result<PublicationReclamationLimits, Status> {
    if !(1..=1024).contains(&files) || !(1..=1024 * 1024 * 1024).contains(&bytes) {
        return Err(invalid());
    }
    Ok(PublicationReclamationLimits {
        maximum_files: files as usize,
        maximum_bytes_hashed: bytes,
    })
}
pub(super) fn command(
    value: Option<&proto::PublicationMaintenanceCommand>,
    principal: &InvocationPrincipal,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<Command, Status> {
    let v = value.ok_or_else(invalid)?;
    let action = kind(v.kind)?;
    budget.allocation::<proto::PublicationMaintenanceCommand>(1)?;
    let selected = selection(v.selection.as_ref(), principal, budget, limits)?;
    if action == proto::PublicationMaintenanceKind::Reclaim {
        return Ok(Command::Reclamation(PublicationReclamationRequest {
            deletion: selected,
            expected_catalog_fence: fence(&v.reclamation_catalog_fence, budget)?,
            limits: work(v.maximum_files, v.maximum_bytes_hashed)?,
        }));
    }
    budget.bytes(&v.reclamation_catalog_fence, 0)?;
    if v.maximum_files != 0 || v.maximum_bytes_hashed != 0 {
        return Err(invalid());
    }
    Ok(if action == proto::PublicationMaintenanceKind::Delete {
        Command::Deletion(selected)
    } else {
        Command::Retention(PublicationRetentionRequest {
            scope: selected.scope,
            actor: selected.actor,
            operation_id: selected.operation_id,
            expected_catalog_fence: selected.expected_catalog_fence,
            targets: selected.targets,
            action: if action == proto::PublicationMaintenanceKind::Pin {
                PublicationRetentionAction::Pin
            } else {
                PublicationRetentionAction::Unpin
            },
        })
    })
}
