use super::{authenticate, control, Service};
use std::sync::atomic::Ordering;
use tonic::{Request, Response, Status};

#[tonic::async_trait]
impl control::policy_service_server::PolicyService for Service {
    async fn apply_policy(
        &self,
        request: Request<control::ApplyPolicyRequest>,
    ) -> Result<Response<control::ApplyPolicyResponse>, Status> {
        authenticate(&request)?;
        let request = request.into_inner();
        let (value, new) = {
            let mut policies = self.0.policies.lock().unwrap();
            if let Some(value) = policies.get(&request.operation_id) {
                (value.clone(), false)
            } else {
                let mut policy = request
                    .policy
                    .ok_or_else(|| Status::invalid_argument("missing policy"))?;
                policy.generation = 2;
                policy.content_digest = format!("sha256:{}", "2".repeat(64));
                let receipt = control::CapabilityPolicyOperation {
                    operation_id: request.operation_id.clone(),
                    tenant: "tests".into(),
                    id: policy.id.clone(),
                    record_kind: policy.record_kind,
                    generation: policy.generation,
                    content_digest: policy.content_digest.clone(),
                    revoked: false,
                };
                let value = control::ApplyPolicyResponse {
                    policy: Some(policy),
                    receipt: Some(receipt),
                };
                policies.insert(request.operation_id.clone(), value.clone());
                self.0.mutations.fetch_add(1, Ordering::AcqRel);
                (value, true)
            }
        };
        if new && request.operation_id == "lost-operation" {
            std::future::pending::<()>().await;
        }
        let mut response = Response::new(value);
        response
            .metadata_mut()
            .insert("latent-audit-status", "durable".parse().unwrap());
        response.metadata_mut().insert(
            "latent-audit-attempt",
            u64::MAX.to_string().parse().unwrap(),
        );
        Ok(response)
    }

    async fn get_policy(
        &self,
        request: Request<control::GetPolicyRequest>,
    ) -> Result<Response<control::GetPolicyResponse>, Status> {
        authenticate(&request)?;
        let identity = request.into_inner().id;
        let policy = self
            .0
            .policies
            .lock()
            .unwrap()
            .values()
            .filter_map(|value| value.policy.clone())
            .find(|policy| policy.id == identity);
        Ok(Response::new(control::GetPolicyResponse { policy }))
    }

    async fn list_policies(
        &self,
        request: Request<control::ListPoliciesRequest>,
    ) -> Result<Response<control::ListPoliciesResponse>, Status> {
        authenticate(&request)?;
        let size = request.into_inner().page.map_or(1, |page| page.page_size);
        let policies = self
            .0
            .policies
            .lock()
            .unwrap()
            .values()
            .filter_map(|value| value.policy.clone())
            .take(size as usize)
            .collect();
        Ok(Response::new(control::ListPoliciesResponse {
            policies,
            catalog_generation: 2,
            page: Some(control::PageResponse::default()),
        }))
    }

    async fn get_policy_operation(
        &self,
        request: Request<control::GetPolicyOperationRequest>,
    ) -> Result<Response<control::GetPolicyOperationResponse>, Status> {
        authenticate(&request)?;
        let receipt = self
            .0
            .policies
            .lock()
            .unwrap()
            .get(&request.into_inner().operation_id)
            .and_then(|value| value.receipt.clone());
        Ok(Response::new(control::GetPolicyOperationResponse {
            receipt,
        }))
    }

    async fn evaluate_policy(
        &self,
        _request: Request<control::EvaluatePolicyRequest>,
    ) -> Result<Response<control::EvaluatePolicyResponse>, Status> {
        Err(Status::unimplemented("not in client profile"))
    }
    async fn delete_policy(
        &self,
        _request: Request<control::DeletePolicyRequest>,
    ) -> Result<Response<control::Empty>, Status> {
        Err(Status::unimplemented("not in client profile"))
    }
}

#[tonic::async_trait]
impl control::capability_service_server::CapabilityService for Service {
    async fn list_capabilities(
        &self,
        request: Request<control::ListCapabilitiesRequest>,
    ) -> Result<Response<control::ListCapabilitiesResponse>, Status> {
        authenticate(&request)?;
        Ok(Response::new(control::ListCapabilitiesResponse {
            capabilities: vec![control::CapabilityDescriptor {
                id: "http".into(),
                contract: "latent:http/client@0.2.0".into(),
                provider: "http".into(),
                operations: vec!["request".into()],
                inspection: Some(control::CapabilityBindingInspection {
                    provider_profile: "outbound-http-v1".into(),
                    provider_configuration_epoch: u64::MAX,
                    state: "current".into(),
                    ..Default::default()
                }),
                ..Default::default()
            }],
            page: Some(control::PageResponse::default()),
            state: "current".into(),
            ..Default::default()
        }))
    }
    async fn explain_capability_grant(
        &self,
        _request: Request<control::ExplainCapabilityGrantRequest>,
    ) -> Result<Response<control::ExplainCapabilityGrantResponse>, Status> {
        Err(Status::unimplemented("not in client profile"))
    }
}
