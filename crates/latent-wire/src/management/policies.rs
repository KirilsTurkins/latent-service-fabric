//! Tenant-scoped policy control, never a guest-facing permission mint.
mod conversion;
mod lease;
mod reads;
mod validation;
pub use lease::PolicyResponseService;

use super::{proto, ManagementOperation, ManagementServiceAdapter, RequestBudget};
use latent_policy::capability as domain;
use prost::Message;
use tonic::{Request, Response, Status};

pub(super) const MAX_REQUEST_BYTES: usize = 128 * 1024;
pub(super) const MAX_RESPONSE_BYTES: usize = 1024 * 1024;
impl ManagementServiceAdapter {
    fn policy_control(&self) -> Result<&domain::PolicyControlHandle, Status> {
        self.policies
            .as_ref()
            .ok_or_else(|| Status::unimplemented("capability-policy-unavailable"))
    }
}
#[tonic::async_trait]
impl proto::policy_service_server::PolicyService for ManagementServiceAdapter {
    async fn apply_policy(
        &self,
        mut request: Request<proto::ApplyPolicyRequest>,
    ) -> Result<Response<proto::ApplyPolicyResponse>, Status> {
        let deadline = validation::deadline(&request);
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let tenant = validation::identity(&principal)?.to_owned();
        let request = request.into_inner();
        let mut budget = RequestBudget::new::<proto::ApplyPolicyRequest>(&self.limits)?;
        validation::id(&request.operation_id, &mut budget)?;
        let expected = request
            .expected_generation
            .ok_or_else(validation::invalid)?;
        let permit = self
            .policy_control()?
            .reserve()
            .map_err(validation::platform)?;
        let policy = request.policy.as_ref().ok_or_else(validation::invalid)?;
        let (kind, document) = validation::normalize(policy, &tenant, &mut budget)?;
        validation::encoded(&request, &self.limits)?;
        let id = policy.id.clone();
        let operation = request.operation_id;
        let maximum = self.limits.max_response_bytes.min(MAX_RESPONSE_BYTES);
        let read = permit.run(move |store| {
            let read = store.mutate(
                domain::MutationRequest {
                    tenant: &tenant,
                    actor: &principal.subject,
                    id: &id,
                    kind,
                    operation_id: &operation,
                    expected_revision: expected,
                    document: Some(document.as_bytes()),
                },
                deadline,
                |receipt| {
                    if conversion::applied(receipt, &document).encoded_len() > maximum {
                        return Err(validation::too_large());
                    }
                    Ok(())
                },
            )?;
            let (receipt, lease) = read.into_parts();
            Ok((conversion::applied(&receipt, &document), lease))
        });
        let (value, lease) = tokio::time::timeout_at(deadline.into(), read)
            .await
            .map_err(|_| Status::deadline_exceeded("capability-policy-deadline"))?
            .map_err(validation::platform)?;
        conversion::finish(value, lease, maximum, deadline)
    }
    async fn delete_policy(
        &self,
        mut request: Request<proto::DeletePolicyRequest>,
    ) -> Result<Response<proto::Empty>, Status> {
        let deadline = validation::deadline(&request);
        let principal = self.authenticate(&mut request, ManagementOperation::Tenant)?;
        let tenant = validation::identity(&principal)?.to_owned();
        let request = request.into_inner();
        let mut budget = RequestBudget::new::<proto::DeletePolicyRequest>(&self.limits)?;
        validation::id(&request.id, &mut budget)?;
        validation::id(&request.operation_id, &mut budget)?;
        let kind = validation::kind(request.record_kind)?;
        let expected = request
            .expected_generation
            .ok_or_else(validation::invalid)?;
        validation::encoded(&request, &self.limits)?;
        let permit = self
            .policy_control()?
            .reserve()
            .map_err(validation::platform)?;
        let read = permit.run(move |store| {
            store.mutate(
                domain::MutationRequest {
                    tenant: &tenant,
                    actor: &principal.subject,
                    id: &request.id,
                    kind,
                    operation_id: &request.operation_id,
                    expected_revision: expected,
                    document: None,
                },
                deadline,
                |_| Ok(()),
            )
        });
        let read = tokio::time::timeout_at(deadline.into(), read)
            .await
            .map_err(|_| Status::deadline_exceeded("capability-policy-deadline"))?
            .map_err(validation::platform)?;
        let (_, lease) = read.into_parts();
        conversion::finish(
            proto::Empty {},
            lease,
            self.limits.max_response_bytes,
            deadline,
        )
    }
    async fn get_policy(
        &self,
        request: Request<proto::GetPolicyRequest>,
    ) -> Result<Response<proto::GetPolicyResponse>, Status> {
        reads::get(self, request).await
    }
    async fn list_policies(
        &self,
        request: Request<proto::ListPoliciesRequest>,
    ) -> Result<Response<proto::ListPoliciesResponse>, Status> {
        reads::list(self, request).await
    }
    async fn get_policy_operation(
        &self,
        request: Request<proto::GetPolicyOperationRequest>,
    ) -> Result<Response<proto::GetPolicyOperationResponse>, Status> {
        reads::outcome(self, request).await
    }
    async fn evaluate_policy(
        &self,
        request: Request<proto::EvaluatePolicyRequest>,
    ) -> Result<Response<proto::EvaluatePolicyResponse>, Status> {
        reads::explain(self, request).await
    }
}
