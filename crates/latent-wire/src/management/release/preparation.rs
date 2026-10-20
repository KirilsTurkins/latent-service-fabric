//! Bounded setup for an exact admitted tenant publication; never invocation.
use super::{
    platform_status, proto, selector, validation, ManagementServiceAdapter, RequestBudget,
};
use crate::management::{ManagementLimits, ManagementOperation};
use latent_artifacts::{ArtifactRepository, LifecycleScope, PublicationRef, ReleaseUseEligibility};
use latent_core::{ReleaseDigest, TenantId};
use latent_executor::{ExecutionBackend, PreparationKey, PreparedReadiness};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tonic::{Request, Response, Status};

#[cfg(test)]
mod tests;

pub const MAX_RELEASE_PREPARATION_WAIT_MILLIS: u64 = 300_000;
pub const RELEASE_PREPARATION_RPC_PATH: &str = "/latent.control.v1.ReleaseService/PrepareRelease";

impl ManagementServiceAdapter {
    pub(super) async fn release_prepare(
        &self,
        mut request: Request<proto::PrepareReleaseRequest>,
    ) -> Result<Response<proto::PrepareReleaseResponse>, Status> {
        // authenticate consumes the trusted context: retain its original expiry
        // before taking it, exactly as the existing web preparation operation.
        let expires = deadline(&request)?;
        let tenant = self
            .authenticate(&mut request, ManagementOperation::Tenant)?
            .tenant
            .expect("authenticated tenant");
        let generation = request.get_ref().lifecycle_generation;
        if generation == 0 {
            return Err(Status::invalid_argument(
                "release lifecycle generation is required",
            ));
        }
        let mut budget = RequestBudget::new::<proto::PrepareReleaseRequest>(&self.limits)?;
        let selected = selector::request(
            request.get_ref().publication.as_ref(),
            &tenant,
            &mut budget,
            &self.limits,
        )?;
        self.check_encoded(request.get_ref())?;
        drop(request);
        let backend = self
            .web_backend
            .as_ref()
            .ok_or_else(|| Status::unimplemented("release preparation is not configured"))?;
        let mut budget =
            RequestBudget::for_response::<proto::PrepareReleaseResponse>(&self.limits)?;
        let (release, eligibility) = self
            .release_preparation_selection(&selected, &tenant, generation, expires, &mut budget)
            .await?;
        eligibility
            .with_current(&mut |_| Ok(()))
            .map_err(|failure| platform_status(failure, &self.limits))?;
        let response = self.response(proto::PrepareReleaseResponse {
            publication: Some(selector::owned(&selected.id, &tenant)),
            lifecycle_generation: generation,
            component_digest: release.0.clone(),
            prepared: true,
        })?;
        let mut key = backend
            .preparation_key(&release)
            .map_err(|failure| platform_status(failure, &self.limits))?;
        if key.release != release {
            return Err(Status::internal("release preparation key mismatch"));
        }
        key.publication = Some(selected.id);
        let ready = ready(
            backend.as_ref(),
            Arc::clone(&self.services.artifacts),
            key.clone(),
            expires,
            &self.limits,
            "release preparation wait expired",
        )
        .await?;
        if ready.descriptor().key != key || ready.descriptor().backend != backend.backend_id() {
            return Err(Status::internal("release preparation identity mismatch"));
        }
        eligibility
            .with_current(&mut |_| Ok(()))
            .map_err(|failure| platform_status(failure, &self.limits))?;
        drop(ready);
        if Instant::now() >= expires {
            return Err(Status::deadline_exceeded(
                "release preparation wait expired",
            ));
        }
        Ok(response)
    }

    async fn release_preparation_selection(
        &self,
        selected: &PublicationRef,
        tenant: &TenantId,
        generation: u64,
        expires: Instant,
        budget: &mut RequestBudget,
    ) -> Result<(ReleaseDigest, ReleaseUseEligibility), Status> {
        let scope = LifecycleScope::Tenant(tenant.clone());
        let entry = tokio::time::timeout_at(
            expires.into(),
            self.services
                .artifacts
                .get_selected_catalog_entry(&scope, selected),
        )
        .await
        .map_err(|_| Status::deadline_exceeded("release preparation wait expired"))?
        .map_err(|failure| platform_status(failure, &self.limits))?
        .ok_or_else(|| Status::not_found("publication not found"))?;
        validation::entry(&entry, tenant, budget, &self.limits)?;
        if !selector::matches(selected, entry.publication.as_ref()) {
            return Err(Status::internal(
                "artifact repository returned a different release",
            ));
        }
        let release = entry.descriptor.release_digest;
        let eligibility = self
            .services
            .artifacts
            .execution_eligibility_selected(&release, Some(&selected.id))
            .map_err(|failure| platform_status(failure, &self.limits))?
            .ok_or_else(|| {
                Status::failed_precondition("release preparation eligibility unavailable")
            })?;
        // Sealed catalog authority, never a component-only/local-unscoped alias.
        if eligibility.scope() != &LifecycleScope::Tenant(tenant.clone())
            || eligibility.publication() != &selected.id
            || eligibility.release() != &release
            || eligibility.generation() != generation
        {
            return Err(Status::failed_precondition(
                "release preparation selection changed",
            ));
        }
        budget.allocation::<u8>(eligibility.retained_bytes())?;
        Ok((release, eligibility))
    }
}

// Shared with the existing web operation: same source, owned readiness/cache
// accounting, currentness timer and original transport cancellation semantics.
pub(super) async fn ready(
    backend: &dyn ExecutionBackend,
    repository: Arc<dyn ArtifactRepository>,
    key: PreparationKey,
    expires: Instant,
    limits: &ManagementLimits,
    expired: &'static str,
) -> Result<PreparedReadiness, Status> {
    if Instant::now() >= expires {
        return Err(Status::deadline_exceeded(expired));
    }
    let timer = latent_node::CurrentnessReadTimer;
    tokio::time::timeout_at(
        expires.into(),
        backend.prepare_ready_from_repository_with_wait(repository, key, &timer),
    )
    .await
    .map_err(|_| Status::deadline_exceeded(expired))?
    .map_err(|failure| platform_status(failure, limits))
}

fn deadline(request: &Request<proto::PrepareReleaseRequest>) -> Result<Instant, Status> {
    let millis = request.get_ref().maximum_wait_millis;
    if !(1..=MAX_RELEASE_PREPARATION_WAIT_MILLIS).contains(&millis) {
        return Err(Status::invalid_argument(
            "release preparation wait is outside its finite limit",
        ));
    }
    let maximum = Instant::now() + Duration::from_millis(millis);
    Ok(request
        .extensions()
        .get::<crate::invocation::AuthenticatedInvocationContext>()
        .and_then(crate::invocation::AuthenticatedInvocationContext::transport_expires_at)
        .map_or(maximum, |expires| expires.min(maximum)))
}
