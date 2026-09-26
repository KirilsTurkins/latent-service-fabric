//! Exact targets for the bounded, opaque-payload local service adapter.
use super::{denied, invalid, token, CapabilitySession, PlatformError};
use latent_core::TenantId;
use latent_routing::{InvocationTarget, ResolvedRevision};

pub const SERVICE_INVOCATION_CAPABILITY: &str = "latent:service/invoke@0.1.0";
pub const LOCAL_SERVICE_INVOCATION_PROFILE: &str = "lsf-local-service-invocation-v1";

/// Trusted compiler input, after checking the consumer's canonical service ABI
/// and the provider package's actual exported interface and value signatures.
/// It is a bounded descriptor, not permission to execute the publication.
#[derive(Clone)]
pub struct InvocationBindingTarget {
    pub(super) revision: ResolvedRevision,
    functions: Box<[String]>,
}
impl InvocationBindingTarget {
    pub fn new(revision: ResolvedRevision, functions: &[String]) -> Result<Self, PlatformError> {
        if functions.is_empty()
            || functions.len() > 128
            || functions.iter().any(|name| !token(name))
            || functions.iter().map(String::len).sum::<usize>() > 4096
            || functions.windows(2).any(|pair| pair[0] >= pair[1])
            || !token(&revision.target.tenant.0)
            || !token(&revision.target.service.0)
            || !token(&revision.target.contract.0)
            || !token(&revision.revision.0)
            || !revision.target.function.0.is_empty()
            || !revision.attributes.is_empty()
            || revision.publication.is_none()
            || revision
                .target
                .route
                .as_ref()
                .is_none_or(|route| !token(route))
        {
            return Err(invalid());
        }
        Ok(Self {
            revision,
            functions: functions.into(),
        })
    }

    pub(super) fn resolve(
        &self,
        requested: &InvocationTarget,
    ) -> Result<ResolvedRevision, PlatformError> {
        let target = &self.revision.target;
        if requested.tenant != target.tenant
            || requested.service != target.service
            || requested.contract != target.contract
            || requested
                .route
                .as_ref()
                .is_some_and(|route| Some(route) != target.route.as_ref())
            || self.functions.binary_search(&requested.function.0).is_err()
        {
            return Err(denied());
        }
        let mut revision = self.revision.clone();
        revision.target.function.clone_from(&requested.function);
        Ok(revision)
    }

    pub(super) fn permits_dependency(
        &self,
        dependency: &latent_artifacts::ReleaseUseEligibility,
    ) -> bool {
        self.revision.publication.as_ref() == Some(dependency.publication())
            && self.revision.release == *dependency.release()
            && dependency.tenant() == Some(&self.revision.target.tenant)
    }
}

pub(super) fn validate_targets(
    revision: &ResolvedRevision,
    imports: &[super::CapabilityBindingSpec<'_>],
    dependencies: &[latent_artifacts::ReleaseUseEligibility],
    targets: &[InvocationBindingTarget],
    has_fence: bool,
) -> Result<(), PlatformError> {
    for target in targets {
        if !has_fence
            || target.revision.route_generation != revision.route_generation
            || !dependencies
                .iter()
                .any(|dependency| target.permits_dependency(dependency))
            || !imports.iter().any(|import| {
                import.provider.capability() == SERVICE_INVOCATION_CAPABILITY
                    && import.provider.profile() == LOCAL_SERVICE_INVOCATION_PROFILE
                    && import.imported_operations == ["call"]
            })
        {
            return Err(invalid());
        }
    }
    Ok(())
}
impl CapabilitySession {
    /// A target lookup only. The adapter must still open and dispatch a Service
    /// resource handle for this exact scoped publication before child admission.
    pub fn local_invocation_target(
        &self,
        requested: &InvocationTarget,
    ) -> Result<ResolvedRevision, PlatformError> {
        self.core.check()?;
        self.core
            .plan
            .bindings
            .iter()
            .find_map(|binding| binding.invocation_target.as_ref())
            .ok_or_else(denied)?
            .resolve(requested)
    }

    #[must_use]
    pub fn tenant(&self) -> &TenantId {
        &self.core.plan.target.tenant
    }
}
