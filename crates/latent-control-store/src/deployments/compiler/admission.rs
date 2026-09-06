//! Small trusted policy records compiled alongside the immutable route indexes.

use std::collections::BTreeMap;

use latent_core::{PlatformError, PlatformErrorCode, RevisionId};
use latent_manifest::{DeploymentManifest, ExecutionRequirements};
use latent_routing::{ResolvedRevision, RevisionAdmissionPolicy, RevisionPolicySource};

use super::super::PinnedRouteResolver;
use super::{charge, error, valid_identifier};

pub(super) fn retain_policy(
    policies: &mut BTreeMap<RevisionId, RevisionAdmissionPolicy>,
    revision: RevisionId,
    deployment: &DeploymentManifest,
    execution: &ExecutionRequirements,
    remaining: &mut usize,
) -> Result<(), PlatformError> {
    // Charge the fixed record, key, and conservative B-tree bookkeeping before
    // cloning. Only placement strings and fixed-size execution requirements are
    // retained; never component bytes, contract trees, or a full artifact.
    charge(remaining, 512 + std::mem::size_of::<RevisionAdmissionPolicy>())?;
    charge(remaining, revision.0.len())?;
    charge(remaining, deployment.placement.trust_class.len())?;
    for values in [
        &deployment.placement.architectures,
        &deployment.placement.regions,
        &deployment.placement.zones,
        &deployment.placement.required_features,
    ] {
        for value in values {
            charge(remaining, std::mem::size_of::<String>())?;
            charge(remaining, value.len())?;
        }
    }
    let policy = RevisionAdmissionPolicy {
        deployment_ceiling: deployment.resources.clone(),
        execution: execution.clone(),
        placement: deployment.placement.clone(),
    };
    if policies.insert(revision, policy).is_some() {
        return Err(error(PlatformErrorCode::AlreadyExists, "duplicate-revision-policy"));
    }
    Ok(())
}

impl RevisionPolicySource for PinnedRouteResolver {
    fn admission_policy(
        &self,
        revision: &ResolvedRevision,
    ) -> Result<RevisionAdmissionPolicy, PlatformError> {
        let target = &revision.target;
        let route = target.route.as_deref().unwrap_or("default");
        for id in [
            target.tenant.0.as_str(),
            target.service.0.as_str(),
            target.contract.0.as_str(),
            target.function.0.as_str(),
            route,
            revision.revision.0.as_str(),
            revision.release.0.as_str(),
        ] {
            if !valid_identifier(id, self.config.max_identifier_bytes) {
                return Err(error(PlatformErrorCode::InvalidArgument, "invalid-pinned-revision"));
            }
        }
        if revision.route_generation != self.catalog.snapshot.generation {
            return Err(missing_policy());
        }
        let key = (
            (target.tenant.0.clone(), target.service.0.clone(), route.to_owned()),
            target.contract.0.clone(),
            target.function.0.clone(),
        );
        let candidates = self.catalog.endpoints.get(&key).ok_or_else(missing_policy)?;
        // Compilation sorts candidate revisions by their stable identities. No
        // scan across services, caller metadata parsing, or re-resolution with a
        // different routing key is performed at this boundary.
        let index = candidates.revisions.binary_search_by(|(_, candidate)| {
            candidate.revision.cmp(&revision.revision)
        }).map_err(|_| missing_policy())?;
        if candidates.revisions[index].1.release != revision.release {
            return Err(missing_policy());
        }
        self.catalog.admission_policies.get(&revision.revision).cloned().ok_or_else(missing_policy)
    }
}

fn missing_policy() -> PlatformError {
    error(PlatformErrorCode::RouteUnavailable, "pinned-revision-not-found")
}
