mod admission;
mod fingerprint;
mod index;
mod packing;
mod records;
mod reuse;
mod search;
#[cfg(test)]
mod tests;

use std::borrow::Cow;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use latent_artifacts::{ArtifactRepository, ReleaseEligibility, VerifiedArtifactMetadata};
use latent_core::{Metadata, PlatformError, PlatformErrorCode, ReleaseDigest, RouteGeneration};
use latent_manifest::{
    __serde_json as json, JsonManifestCodec, ManifestCodec, ManifestValidator,
    Phase1ManifestValidator,
};

use super::observation::{count, Work};
use super::pagination::DeploymentIndex;
use super::{
    deployment_revision_id_observed, error, manifest_error, DirectoryDeploymentRepositoryConfig,
};
use fingerprint::contract_fingerprint;
pub(super) use index::RouteView;
use index::{EndpointRow, RouteRow, WeightedCandidate};
pub(super) use records::{DesiredDeployments, ObjectVersions, RecordIndex, RevisionRecord};

pub(super) struct CompiledCatalog {
    pub deployments: DesiredDeployments,
    pub versions: ObjectVersions,
    pub generation: RouteGeneration,
    pub generated_at_unix_millis: u64,
    pub records: Box<[Arc<RevisionRecord>]>,
    pub paging_index: DeploymentIndex,
    pub eligibility: Box<[ReleaseEligibility]>,
    pub local_releases: usize,
    routes: Box<[RouteRow]>,
    route_revisions: Box<[RecordIndex]>,
    endpoints: Box<[EndpointRow]>,
    candidates: Box<[WeightedCandidate]>,
    reuse: Option<Box<reuse::ReuseState>>,
}

#[cfg(test)]
pub(super) async fn compile(
    deployments: BTreeMap<latent_core::DeploymentId, latent_manifest::DeploymentManifest>,
    generation: RouteGeneration,
    generated_at_unix_millis: u64,
    artifacts: &dyn ArtifactRepository,
    config: DirectoryDeploymentRepositoryConfig,
) -> Result<CompiledCatalog, PlatformError> {
    let versions = deployments
        .keys()
        .map(|id| (id.clone(), generation.0))
        .collect();
    compile_versioned(
        deployments
            .into_iter()
            .map(|(id, manifest)| (id, Arc::new(manifest)))
            .collect(),
        versions,
        generation,
        generated_at_unix_millis,
        artifacts,
        config,
        None,
        &mut Work::default(),
    )
    .await
    .map(super::persistence::EncodedCatalog::into_catalog)
}

#[expect(
    clippy::too_many_arguments,
    reason = "the local observer adds no policy or compilation input"
)]
pub(super) async fn compile_versioned(
    deployments: DesiredDeployments,
    versions: ObjectVersions,
    generation: RouteGeneration,
    generated_at_unix_millis: u64,
    artifacts: &dyn ArtifactRepository,
    config: DirectoryDeploymentRepositoryConfig,
    previous: Option<&CompiledCatalog>,
    work: &mut Work,
) -> Result<super::persistence::EncodedCatalog, PlatformError> {
    compile_versioned_inner(
        deployments,
        versions,
        generation,
        generated_at_unix_millis,
        artifacts,
        config,
        previous,
        work,
        false,
    )
    .await
}

#[expect(
    clippy::too_many_arguments,
    reason = "startup adds bounded per-read retries without restarting compilation"
)]
pub(super) async fn compile_versioned_inner(
    mut deployments: DesiredDeployments,
    versions: ObjectVersions,
    generation: RouteGeneration,
    generated_at_unix_millis: u64,
    artifacts: &dyn ArtifactRepository,
    config: DirectoryDeploymentRepositoryConfig,
    previous: Option<&CompiledCatalog>,
    work: &mut Work,
    recovery: bool,
) -> Result<super::persistence::EncodedCatalog, PlatformError> {
    count!(work, compiler_calls, 1);
    work.generation(generation.0);
    let result = async {
        if deployments.len() > config.max_deployments {
            return Err(error(
                PlatformErrorCode::ResourceExhausted,
                "deployment-count-limit",
            ));
        }
        if versions.len() != deployments.len()
            || versions.iter().any(|(id, stamp)| {
                *stamp == 0 || *stamp > generation.0 || !deployments.contains_key(id)
            })
        {
            return Err(error(
                PlatformErrorCode::CorruptArtifact,
                "invalid-persisted-catalog",
            ));
        }
        let codec = JsonManifestCodec::default();
        // Group references, not cloned artifacts. At most one release's verified
        // metadata is alive; repository verification owns any component bytes.
        let mut ordered = deployments
            .values()
            .enumerate()
            .map(|(index, manifest)| (RecordIndex(index), manifest))
            .collect::<Vec<_>>();
        ordered.sort_unstable_by(|(_, left), (_, right)| {
            left.release
                .cmp(&right.release)
                .then_with(|| left.id.cmp(&right.id))
        });
        let mut release: Option<(ReleaseDigest, VerifiedArtifactMetadata)> = None;
        let compatible = reuse::compatible(previous, config);
        let mut memo = reuse::MemoBuilder::new(deployments.len(), config);
        let mut release_surface = None;
        let mut fingerprints = BTreeMap::new();
        let mut scopes = BTreeMap::new();
        let mut contracts = BTreeMap::new();
        let mut indexes = index::IndexBudget::default();
        let mut revision_ids = BTreeSet::new();
        let mut metadata_budget = config.max_state_bytes;
        let mut eligibility = Vec::new();
        let mut local_releases = 0;
        for id in versions.keys() {
            charge(&mut metadata_budget, 128)?;
            charge(&mut metadata_budget, id.0.len())?;
        }

        // The existing per-version allowance also covers bounded record/order slots.
        let mut records = vec![None; deployments.len()];
        for (position, deployment) in ordered {
            Phase1ManifestValidator
                .validate_deployment(deployment)
                .map_err(manifest_error)?;
            let equal_prior = compatible
                .and_then(|catalog| catalog.record_by_id(&deployment.id))
                .filter(|record| record.deployment.as_ref() == deployment.as_ref());
            let encoded = if let Some(record) = equal_prior {
                Cow::Borrowed(
                    record
                        .attributes
                        .get("lsf.deployment")
                        .expect("compiler-owned deployment")
                        .as_bytes(),
                )
            } else {
                count!(work, compiler_deployment_encodes, 1);
                Cow::Owned(
                    codec
                        .encode_deployment(deployment)
                        .map_err(manifest_error)?,
                )
            };
            charge(&mut metadata_budget, encoded.len())?;
            if deployment.id.0 == "default" {
                return Err(error(
                    PlatformErrorCode::AlreadyExists,
                    "reserved-default-route",
                ));
            }
            let tenant = deployment
                .metadata
                .tenant
                .as_ref()
                .ok_or_else(|| error(PlatformErrorCode::InvalidArgument, "missing-tenant"))?;
            for id in [&tenant.0, &deployment.service.0, &deployment.id.0] {
                if !valid_identifier(id, config.max_identifier_bytes) {
                    return Err(error(
                        PlatformErrorCode::InvalidArgument,
                        "invalid-route-identifier",
                    ));
                }
            }
            let scope_key = (tenant.clone(), deployment.service.clone());
            if let Some(namespace) =
                scopes.insert(scope_key.clone(), deployment.metadata.namespace.clone())
            {
                if namespace != deployment.metadata.namespace {
                    return Err(error(
                        PlatformErrorCode::PermissionDenied,
                        "namespace-route-conflict",
                    ));
                }
            }
            if release
                .as_ref()
                .is_none_or(|(digest, _)| digest != &deployment.release)
            {
                // Drop before awaiting the next fetch, not after its result is allocated.
                drop(release.take());
                drop(release_surface.take());
                fingerprints.clear();
                let artifact =
                    super::recovery_admission::metadata(artifacts, &deployment.release, recovery)
                        .await?;
                if let Some(grant) =
                    super::recovery_admission::eligibility(artifacts, &deployment.release, recovery)
                        .await?
                {
                    if grant.release() != &deployment.release {
                        return Err(error(
                            PlatformErrorCode::PermissionDenied,
                            "route-admission-release-mismatch",
                        ));
                    }
                    charge(&mut metadata_budget, grant.retained_bytes())?;
                    eligibility.try_reserve_exact(1).map_err(|_| {
                        error(
                            PlatformErrorCode::ResourceExhausted,
                            "route-admission-allocation",
                        )
                    })?;
                    eligibility.push(grant);
                } else {
                    local_releases += 1;
                }
                let digest_matches = artifact.verified_digest() == &deployment.release
                    && artifact
                        .descriptor()
                        .release_digest
                        .0
                        .eq_ignore_ascii_case(&deployment.release.0)
                    && artifact
                        .manifest()
                        .component_digest
                        .0
                        .eq_ignore_ascii_case(&deployment.release.0);
                if !digest_matches {
                    return Err(error(
                        PlatformErrorCode::CorruptArtifact,
                        "release-digest-mismatch",
                    ));
                }
                let stamp = reuse::metadata_stamp(&artifact);
                memo.push(position, stamp);
                release_surface = reuse::prior_release(compatible, &deployment.release, stamp)
                    .map(reuse::Surface::new)
                    .transpose()?;
                release = Some((deployment.release.clone(), artifact));
            }
            let artifact = &release.as_ref().expect("current release was fetched").1;
            if let Some(grant) = eligibility
                .last()
                .filter(|grant| grant.release() == &deployment.release)
            {
                if grant.tenant() != tenant {
                    return Err(error(
                        PlatformErrorCode::PermissionDenied,
                        "route-admission-tenant-mismatch",
                    ));
                }
            }
            Phase1ManifestValidator
                .validate_deployment_against_capsule(deployment, artifact.manifest())
                .map_err(manifest_error)?;
            let mut descriptors = BTreeMap::new();
            if release_surface.is_none() {
                for descriptor in artifact.contracts() {
                    if descriptors.insert(&descriptor.id, descriptor).is_some() {
                        return Err(error(
                            PlatformErrorCode::AlreadyExists,
                            "duplicate-contract-id",
                        ));
                    }
                }
            }
            let mut callable = BTreeSet::new();
            let mut exported = BTreeMap::new();
            for export in &artifact.manifest().exports {
                if !valid_identifier(&export.contract.0, config.max_identifier_bytes) {
                    return Err(error(
                        PlatformErrorCode::IncompatibleContract,
                        "invalid-contract-id",
                    ));
                }
                let reused = release_surface
                    .as_ref()
                    .map(|surface| {
                        surface
                            .exports
                            .get(&export.contract.0)
                            .ok_or_else(reuse::invariant)
                    })
                    .transpose()?;
                let descriptor = if reused.is_some() {
                    None
                } else {
                    Some(*descriptors.get(&export.contract).ok_or_else(|| {
                        error(
                            PlatformErrorCode::IncompatibleContract,
                            "missing-export-contract-metadata",
                        )
                    })?)
                };
                // Canonical trees and their encoded bytes are temporary for one contract.
                // Both caches retain only computed SHA-256 fingerprints, never documentation
                // or type trees. The canonical bytes (and persisted schema IDs) are unchanged.
                let schema = match fingerprints.get(&export.contract) {
                    Some(schema) => String::clone(schema),
                    None => {
                        let schema = if let Some(reused) = reused {
                            reused.schema.clone()
                        } else {
                            contract_fingerprint(descriptor.expect("fresh descriptor"), work)?
                        };
                        charge_fingerprint(&mut metadata_budget, &[&export.contract.0, &schema])?;
                        fingerprints.insert(export.contract.clone(), schema.clone());
                        schema
                    }
                };
                let contract_key = (scope_key.clone(), export.contract.clone());
                if let Some(previous) = contracts.get(&contract_key) {
                    if previous != &schema {
                        return Err(error(
                            PlatformErrorCode::IncompatibleContract,
                            "conflicting-contract-metadata",
                        ));
                    }
                } else {
                    charge_fingerprint(
                        &mut metadata_budget,
                        &[
                            &tenant.0,
                            &deployment.service.0,
                            &export.contract.0,
                            &schema,
                        ],
                    )?;
                    contracts.insert(contract_key, schema.clone());
                }
                let mut functions = BTreeSet::new();
                if let Some(reused) = reused {
                    for function in &reused.functions {
                        callable.insert((export.contract.0.clone(), function.clone()));
                    }
                } else {
                    let mut interface_ids = BTreeSet::new();
                    for interface in &descriptor.expect("fresh descriptor").interfaces {
                        if !interface_ids.insert(&interface.id) {
                            return Err(error(
                                PlatformErrorCode::AlreadyExists,
                                "duplicate-interface-id",
                            ));
                        }
                        for function in &interface.functions {
                            if !valid_identifier(&function.id.0, config.max_identifier_bytes) {
                                return Err(error(
                                    PlatformErrorCode::IncompatibleContract,
                                    "invalid-function-id",
                                ));
                            }
                            if !functions.insert(function.id.0.clone()) {
                                return Err(error(
                                    PlatformErrorCode::AlreadyExists,
                                    "duplicate-function-id",
                                ));
                            }
                            callable.insert((export.contract.0.clone(), function.id.0.clone()));
                        }
                    }
                    if functions.is_empty() {
                        return Err(error(
                            PlatformErrorCode::IncompatibleContract,
                            "export-has-no-functions",
                        ));
                    }
                }
                if release_surface.is_none() {
                    exported.insert(
                        export.contract.0.clone(),
                        json::json!({"schema":schema,"functions":functions}),
                    );
                }
            }
            let derivation_reuse = equal_prior.filter(|_| release_surface.is_some());
            let revision_id = if let Some(record) = derivation_reuse {
                record.revision.clone()
            } else {
                deployment_revision_id_observed(deployment, work)?
            };
            admission::charge_policy(&revision_id, deployment, &mut metadata_budget)?;
            if !revision_ids.insert(revision_id.clone()) {
                return Err(error(
                    PlatformErrorCode::AlreadyExists,
                    "duplicate-revision-policy",
                ));
            }
            let record = if let Some(record) = derivation_reuse {
                count!(work, record_derivation_reuses, 1);
                count!(work, record_payload_reuses, 1);
                Arc::clone(record)
            } else {
                let deployment_json = String::from_utf8(encoded.into_owned()).map_err(|_| {
                    error(PlatformErrorCode::Internal, "deployment-encoding-failed")
                })?;
                let exports_json = if let Some(surface) = &release_surface {
                    surface.fragment.to_owned()
                } else {
                    json::to_string(&exported).map_err(|_| {
                        error(PlatformErrorCode::Internal, "contract-encoding-failed")
                    })?
                };
                count!(work, record_derivations, 1);
                let candidate = RevisionRecord {
                    deployment: Arc::clone(deployment),
                    revision: revision_id,
                    attributes: Metadata::from([
                        ("lsf.deployment".to_owned(), deployment_json),
                        ("lsf.exports".to_owned(), exports_json),
                    ]),
                    execution: artifact.manifest().execution.clone(),
                };
                previous
                    .and_then(|catalog| catalog.record_by_id(&deployment.id))
                    .filter(|record| record.as_ref() == &candidate)
                    .map_or_else(
                        || Arc::new(candidate),
                        |record| {
                            count!(work, record_payload_reuses, 1);
                            Arc::clone(record)
                        },
                    )
            };
            indexes.charge_record(&record, callable.len(), config, &mut metadata_budget)?;
            records[position.0] = Some(record);
        }
        drop(release);
        drop(release_surface);
        drop(fingerprints);
        drop(contracts);
        let records = records
            .into_iter()
            .map(|record| record.expect("every deployment was verified"))
            .collect::<Vec<_>>()
            .into_boxed_slice();
        // Equal explicit reapply may have allocated a new manifest. Keep exactly the
        // finalized record's Arc in both owners; object versions remain independent.
        for (deployment, record) in deployments.values_mut().zip(records.iter()) {
            *deployment = Arc::clone(&record.deployment);
        }
        let packed = packing::assemble(&records, compatible, work)?;
        let paging_index = DeploymentIndex::build(&records, &versions, config, metadata_budget)?;
        charge(&mut metadata_budget, paging_index.retained_bytes())?;
        let catalog = CompiledCatalog {
            deployments,
            versions,
            generation,
            generated_at_unix_millis,
            records,
            paging_index,
            eligibility: eligibility.into_boxed_slice(),
            local_releases,
            routes: packed.routes,
            route_revisions: packed.route_revisions,
            endpoints: packed.endpoints,
            candidates: packed.candidates,
            reuse: memo.finish(config, &mut metadata_budget),
        };
        // Check exact persisted size, including JSON escaping, before publication.
        super::persistence::encode(catalog, config, work)
    }
    .await;
    if result.is_ok() {
        count!(work, compiler_completed, 1);
    } else {
        count!(work, compiler_failed, 1);
    }
    result
}

fn valid_identifier(value: &str, maximum: usize) -> bool {
    !value.is_empty() && value.len() <= maximum && !value.chars().any(char::is_control)
}

fn charge(remaining: &mut usize, bytes: usize) -> Result<(), PlatformError> {
    *remaining = remaining.checked_sub(bytes).ok_or_else(|| {
        error(
            PlatformErrorCode::ResourceExhausted,
            "catalog-state-byte-limit",
        )
    })?;
    Ok(())
}

fn charge_fingerprint(remaining: &mut usize, fields: &[&str]) -> Result<(), PlatformError> {
    // Charge key/digest storage and conservative per-entry tree bookkeeping before
    // retaining it. Charges are not refunded when the single-release cache rotates.
    charge(remaining, 256)?;
    for field in fields {
        charge(remaining, field.len())?;
    }
    Ok(())
}
