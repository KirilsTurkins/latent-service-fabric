//! Recover exact historical associations without changing receipt canonical bytes.
use super::{validate, TableData};
use crate::{
    deployment_operations::{budget::Budget, capacity, codec, corrupt, Result},
    deployments::CompiledCatalog,
};
use latent_artifacts::ArtifactRepository;
use std::sync::Arc;

pub(in crate::deployments) fn recover_publications(
    data: &mut TableData,
    artifacts: &dyn ArtifactRepository,
    catalog: &CompiledCatalog,
    budget: &Arc<Budget>,
) -> Result<bool> {
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
    let legacy = data.format_version == 1;
    for row in &mut data.receipts {
        let receipt = &mut row.receipt;
        if legacy {
            // A still-retained exact object revision proves its original pin.
            // Otherwise require a unique current scoped catalog match.
            let retained = catalog
                .record_by_id(&receipt.deployment_id)
                .filter(|record| {
                    record.deployment.metadata.tenant.as_ref() == Some(&receipt.tenant)
                        && catalog.versions.get(&receipt.deployment_id)
                            == Some(&receipt.object_generation)
                        && record.deployment.release == receipt.component
                        && record
                            .attributes
                            .get("lsf.deployment")
                            .is_some_and(|manifest| {
                                codec::hash(manifest.as_bytes()) == receipt.manifest_digest
                            })
                });
            row.publication = if let Some(record) = retained {
                record.publication_reference(artifacts)?
            } else {
                artifacts.recover_execution_publication(&receipt.tenant, &receipt.component)?
            };
        } else {
            let selected = match &row.publication {
                Some(reference) => artifacts.select_execution_publication(
                    &receipt.tenant,
                    &receipt.component,
                    Some(&reference.id),
                )?,
                None => {
                    artifacts.recover_execution_publication(&receipt.tenant, &receipt.component)?
                }
            };
            if selected != row.publication {
                return Err(corrupt());
            }
        }
        receipt.publication.clone_from(&row.publication);
    }
    data.format_version = 2;
    Ok(legacy)
}
