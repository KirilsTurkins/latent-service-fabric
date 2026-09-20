use crate::management::{identifier, proto, ManagementLimits, RequestBudget};
use latent_artifacts::{PublicationRef, PublicationSelector};
use latent_core::TenantId;
use tonic::Status;

pub(super) fn publication(
    value: Option<&proto::PublicationRef>,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<PublicationRef, Status> {
    let value =
        value.ok_or_else(|| Status::invalid_argument("exact web publication is required"))?;
    let PublicationSelector::Publication(reference) =
        super::super::selector::request(&String::new(), Some(value), tenant, budget, limits)?
    else {
        return Err(Status::invalid_argument(
            "exact web publication is required",
        ));
    };
    Ok(reference)
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
