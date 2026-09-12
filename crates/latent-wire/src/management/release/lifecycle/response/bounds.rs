use super::{ManagementLimits, RequestBudget};
use latent_artifacts::{
    LifecycleScope, ReleaseActor, ReleaseLifecycleRecord, ReleaseOperationReceipt,
    ReleasePolicyIdentity,
};
use latent_core::{ReleaseDigest, TenantId};
use tonic::Status;

fn invalid() -> Status {
    Status::internal("invalid release lifecycle receipt")
}

fn scope(
    value: &LifecycleScope,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    let LifecycleScope::Tenant(value) = value else {
        return Err(invalid());
    };
    if value != tenant {
        return Err(invalid());
    }
    id(&value.0, 512.min(limits.max_id_bytes), budget)
}

fn id(value: &String, maximum: usize, budget: &mut RequestBudget) -> Result<(), Status> {
    budget.string(value, maximum)?;
    super::super::super::super::identifier(value, maximum).map_err(|_| invalid())
}

fn actor(
    value: &ReleaseActor,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    budget.allocation::<ReleaseActor>(1)?;
    id(&value.subject, 512.min(limits.max_id_bytes), budget)
}

fn digest(
    value: &ReleaseDigest,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    super::super::super::validation::digest(&value.0, budget, limits).map_err(|error| {
        if error.code() == tonic::Code::ResourceExhausted {
            error
        } else {
            invalid()
        }
    })
}

fn policy(
    value: Option<&ReleasePolicyIdentity>,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    if let Some(value) = value {
        budget.allocation::<ReleasePolicyIdentity>(1)?;
        id(&value.scope, 128.min(limits.max_id_bytes), budget)?;
        budget.allocation::<u8>(value.digest.as_str().len())?;
        if value.generation == 0 {
            return Err(invalid());
        }
    }
    Ok(())
}

pub(super) fn record(
    value: &ReleaseLifecycleRecord,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    budget.allocation::<ReleaseLifecycleRecord>(1)?;
    scope(&value.scope, tenant, budget, limits)?;
    digest(&value.release, budget, limits)?;
    actor(&value.actor, budget, limits)?;
    id(&value.operation_id, 128.min(limits.max_id_bytes), budget)?;
    policy(value.policy.as_ref(), budget, limits)?;
    if value.generation == 0 {
        return Err(invalid());
    }
    if let Some(package) = &value.package {
        budget.allocation::<u8>(package.as_str().len())?;
    }
    if let Some(evidence) = &value.evidence_revision_digest {
        budget.allocation::<u8>(evidence.as_str().len())?;
    }
    Ok(())
}

pub(super) fn receipt(
    value: &ReleaseOperationReceipt,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    budget.allocation::<ReleaseOperationReceipt>(1)?;
    scope(&value.scope, tenant, budget, limits)?;
    actor(&value.actor, budget, limits)?;
    id(&value.operation_id, 128.min(limits.max_id_bytes), budget)?;
    budget.allocation::<u8>(value.request_digest.as_str().len())?;
    policy(value.policy.as_ref(), budget, limits)?;
    if let Some(release) = &value.component_digest {
        digest(release, budget, limits)?;
    }
    if let Some(package) = &value.package_manifest_digest {
        budget.allocation::<u8>(package.as_str().len())?;
    }
    if let Some(record) = &value.record {
        self::record(record, tenant, budget, limits)?;
        if value.component_digest.as_ref() != Some(&record.release) {
            return Err(invalid());
        }
    }
    if value.disposition == latent_artifacts::ReleaseOperationDisposition::Committed
        && value.record.is_none()
    {
        return Err(invalid());
    }
    Ok(())
}
