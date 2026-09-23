//! Recover exact historical associations without changing receipt canonical bytes.
use super::{validate, TableData};
use crate::deployment_operations::{budget::Budget, capacity, corrupt, Result};
use latent_artifacts::ArtifactRepository;
use std::sync::Arc;

pub(in crate::deployments) fn validate_publications(
    data: &mut TableData,
    artifacts: &dyn ArtifactRepository,
    budget: &Arc<Budget>,
) -> Result<()> {
    if data.receipts.len() > budget.limits.maximum_receipts {
        return Err(capacity());
    }
    let _scratch = budget.reserve(
        data.receipts
            .len()
            .saturating_mul(2 * (latent_core::PublicationId::TEXT_BYTES + 1024)),
    )?;
    for row in &mut data.receipts {
        row.receipt.publication = row.publication.clone();
    }
    validate(data, true, budget.limits)?;
    for row in &mut data.receipts {
        let receipt = &mut row.receipt;
        let selected = match &row.publication {
            Some(reference) => artifacts.select_execution_publication(
                &receipt.tenant,
                &receipt.component,
                Some(&reference.id),
            )?,
            None => artifacts.recover_execution_publication(&receipt.tenant, &receipt.component)?,
        };
        if selected != row.publication {
            return Err(corrupt());
        }
        receipt.publication.clone_from(&row.publication);
    }
    Ok(())
}
