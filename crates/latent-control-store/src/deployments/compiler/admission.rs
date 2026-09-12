//! Small trusted policy records compiled alongside the immutable route indexes.

use latent_core::{PlatformError, PlatformErrorCode, RevisionId};
use latent_manifest::DeploymentManifest;
use latent_routing::{ResolvedRevision, RevisionAdmissionPolicy, RevisionPolicySource};

use super::super::PinnedRouteResolver;
use super::{charge, error, valid_identifier};

pub(super) fn charge_policy(
    revision: &RevisionId,
    deployment: &DeploymentManifest,
    remaining: &mut usize,
) -> Result<(), PlatformError> {
    // Preserve the original policy/tree allowance while the immutable record
    // borrows placement from its own manifest instead of retaining a second copy.
    charge(
        remaining,
        512 + std::mem::size_of::<RevisionAdmissionPolicy>(),
    )?;
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
        ] {
            if !valid_identifier(id, self.config.max_identifier_bytes) {
                return Err(error(
                    PlatformErrorCode::InvalidArgument,
                    "invalid-pinned-revision",
                ));
            }
        }
        if revision.route_generation != self.catalog.generation {
            return Err(missing_policy());
        }
        let route = self.catalog.find_route(target).ok_or_else(missing_policy)?;
        let endpoint = self
            .catalog
            .find_endpoint(route, target)
            .ok_or_else(missing_policy)?;
        let candidates = &self.catalog.candidates[endpoint.candidates.clone()];
        // Compilation sorts candidate revisions by their stable identities. No
        // scan across services, caller metadata parsing, or re-resolution with a
        // different routing key is performed at this boundary.
        // Generated revision/release identities can exceed the configured route
        // identifier limit. Their exact stored values below are the authority;
        // comparisons inspect at most the corresponding stored identity length.
        let index = candidates
            .binary_search_by(|candidate| {
                self.catalog
                    .record(candidate.record)
                    .revision
                    .cmp(&revision.revision)
            })
            .map_err(|_| missing_policy())?;
        let record = self.catalog.record(candidates[index].record);
        if record.deployment.release != revision.release {
            return Err(missing_policy());
        }
        crate::deployments::admission_fence::check_selected(
            self.catalog
                .selected_eligibility(&revision.release)
                .as_ref(),
            &target.tenant,
        )?;
        Ok(RevisionAdmissionPolicy {
            deployment_ceiling: record.deployment.resources.clone(),
            execution: record.execution.clone(),
            placement: record.deployment.placement.clone(),
        })
    }
}

fn missing_policy() -> PlatformError {
    error(
        PlatformErrorCode::RouteUnavailable,
        "pinned-revision-not-found",
    )
}
