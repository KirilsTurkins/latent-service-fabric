use latent_artifacts::{LifecycleScope, PublicationRef, PublicationSelector};
use latent_core::{PublicationId, ReleaseDigest, TenantId};
use tonic::Status;

use super::super::{identifier, proto, ManagementLimits, RequestBudget};

pub(super) fn request(
    digest: &String,
    publication: Option<&proto::PublicationRef>,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<PublicationSelector, Status> {
    if let Some(reference) = publication {
        if !digest.is_empty() {
            return Err(Status::invalid_argument(
                "exactly one publication selector is required",
            ));
        }
        budget.allocation::<proto::PublicationRef>(1)?;
        budget.string(&reference.id, PublicationId::TEXT_BYTES)?;
        budget.string(&reference.tenant, limits.max_id_bytes.min(512))?;
        identifier(&reference.tenant, limits.max_id_bytes.min(512))?;
        if reference.tenant != tenant.0 {
            return Err(Status::invalid_argument(
                "publication selector tenant mismatch",
            ));
        }
        let id = reference
            .id
            .parse()
            .map_err(|_| Status::invalid_argument("invalid publication identity"))?;
        Ok(PublicationSelector::Publication(PublicationRef {
            id,
            scope: LifecycleScope::Tenant(tenant.clone()),
        }))
    } else {
        super::validation::digest(digest, budget, limits)?;
        Ok(PublicationSelector::LegacyComponent(ReleaseDigest(
            digest.clone(),
        )))
    }
}

pub(super) fn matches(
    selector: &PublicationSelector,
    component: &ReleaseDigest,
    publication: Option<&PublicationId>,
) -> bool {
    match selector {
        PublicationSelector::LegacyComponent(expected) => expected == component,
        PublicationSelector::Publication(expected) => Some(&expected.id) == publication,
    }
}

pub(in super::super) fn owned(id: &PublicationId, tenant: &TenantId) -> proto::PublicationRef {
    proto::PublicationRef {
        id: id.as_str().to_owned(),
        tenant: tenant.0.clone(),
    }
}

pub(super) fn charge(
    id: Option<&PublicationId>,
    tenant: &TenantId,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    if let Some(id) = id {
        budget.allocation::<proto::PublicationRef>(1)?;
        budget.allocation::<u8>(id.as_str().len())?;
        budget.string(&tenant.0, limits.max_id_bytes.min(512))?;
    }
    Ok(())
}
