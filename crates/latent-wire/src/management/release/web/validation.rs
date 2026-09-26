use crate::management::{identifier, proto, ManagementLimits, RequestBudget};
use latent_artifacts::PublicationRef;
use latent_core::TenantId;
use tonic::Status;

pub(super) fn publication(
    value: Option<&proto::PublicationRef>,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<PublicationRef, Status> {
    super::super::selector::request(value, tenant, budget, limits)
}

pub(super) fn operation(
    value: Option<&proto::ReleaseOperationPrecondition>,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
    publish: bool,
) -> Result<(), Status> {
    if value.is_none() {
        return Err(Status::invalid_argument("web operation is required"));
    }
    super::super::lifecycle::operation(value, budget, limits, publish)
}

pub(super) fn operation_id(
    value: &String,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    budget.string(value, 128.min(limits.max_id_bytes))?;
    identifier(value, 128.min(limits.max_id_bytes))
}
