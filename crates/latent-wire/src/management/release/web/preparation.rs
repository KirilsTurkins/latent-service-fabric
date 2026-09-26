use super::{
    platform_status, proto, validation, Arc, ManagementOperation, ManagementServiceAdapter,
    PlatformError, PlatformErrorCode, Request, RequestBudget, Response, Status,
    MAX_WEB_PREPARATION_WAIT_MILLIS,
};
use latent_core::ReleaseDigest;
use latent_executor::ExecutionBackend;
use std::time::{Duration, Instant};

impl ManagementServiceAdapter {
    pub fn with_web_preparation(
        mut self,
        backend: Arc<dyn ExecutionBackend>,
    ) -> Result<Self, PlatformError> {
        if self.web.is_none() || self.web_backend.is_some() {
            return Err(PlatformError {
                code: PlatformErrorCode::InvalidArgument,
                message: "web-preparation-owner-invalid".into(),
                retryable: false,
                details: Vec::new(),
            });
        }
        self.web_backend = Some(backend);
        Ok(self)
    }

    pub(in crate::management::release) async fn web_prepare(
        &self,
        mut request: Request<proto::PrepareWebPublicationRequest>,
    ) -> Result<Response<proto::PrepareWebPublicationResponse>, Status> {
        let expires = deadline(&request)?;
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let tenant = principal.tenant.expect("authenticated tenant");
        let mut budget = RequestBudget::new::<proto::PrepareWebPublicationRequest>(&self.limits)?;
        let reference = validation::publication(
            request.get_ref().publication.as_ref(),
            &tenant,
            &mut budget,
            &self.limits,
        )?;
        if request.get_ref().lifecycle_generation == 0 {
            return Err(Status::invalid_argument(
                "web lifecycle generation is required",
            ));
        }
        self.check_encoded(request.get_ref())?;
        let backend = self
            .web_backend
            .as_ref()
            .ok_or_else(|| Status::unimplemented("web preparation is not configured"))?;
        let selection = self
            .web_catalog()?
            .select_web_publication(&reference)
            .map_err(|failure| platform_status(failure, &self.limits))?;
        let eligibility = selection.eligibility();
        if eligibility.generation() != request.get_ref().lifecycle_generation {
            return Err(Status::failed_precondition(
                "web lifecycle generation changed",
            ));
        }
        let renderer = eligibility
            .layout()
            .manifest()
            .renderer
            .as_ref()
            .ok_or_else(|| Status::failed_precondition("web publication has no renderer"))?;
        let mut budget =
            RequestBudget::for_response::<proto::PrepareWebPublicationResponse>(&self.limits)?;
        super::super::selector::charge(Some(&reference.id), &tenant, &mut budget, &self.limits)?;
        budget.string(&renderer.digest, 71)?;
        let response = self.response(proto::PrepareWebPublicationResponse {
            publication: Some(super::super::selector::owned(&reference.id, &tenant)),
            lifecycle_generation: eligibility.generation(),
            component_digest: renderer.digest.clone(),
            prepared: true,
        })?;
        let mut key = backend
            .preparation_key(&ReleaseDigest(renderer.digest.clone()))
            .map_err(|failure| platform_status(failure, &self.limits))?;
        key.publication = Some(reference.id.clone());
        let ready = tokio::time::timeout_at(
            expires.into(),
            backend.prepare_ready_from_repository(self.services.artifacts.clone(), key.clone()),
        )
        .await
        .map_err(|_| Status::deadline_exceeded("web preparation wait expired"))?
        .map_err(|failure| platform_status(failure, &self.limits))?;
        if ready.descriptor().key != key || ready.descriptor().backend != backend.backend_id() {
            return Err(Status::internal("web preparation identity mismatch"));
        }
        eligibility
            .with_current(&tenant, &mut |_| Ok(()))
            .map_err(|failure| platform_status(failure, &self.limits))?;
        drop(ready);
        if Instant::now() >= expires {
            return Err(Status::deadline_exceeded("web preparation wait expired"));
        }
        Ok(response)
    }
}

fn deadline(request: &Request<proto::PrepareWebPublicationRequest>) -> Result<Instant, Status> {
    let millis = request.get_ref().maximum_wait_millis;
    if !(1..=MAX_WEB_PREPARATION_WAIT_MILLIS).contains(&millis) {
        return Err(Status::invalid_argument(
            "web preparation wait is outside its finite limit",
        ));
    }
    let maximum = Instant::now() + Duration::from_millis(millis);
    Ok(request
        .extensions()
        .get::<crate::invocation::AuthenticatedInvocationContext>()
        .and_then(crate::invocation::AuthenticatedInvocationContext::transport_expires_at)
        .map_or(maximum, |expires| expires.min(maximum)))
}
