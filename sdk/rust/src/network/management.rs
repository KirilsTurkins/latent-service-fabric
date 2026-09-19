use super::{
    invocation::bounded_id, FailureKind, RecoveryIdentity, RpcClient, RpcFailure, RpcResponse,
};
use latent_rpc::control::v1::{
    capability_service_client::CapabilityServiceClient, policy_service_client::PolicyServiceClient,
};
use tokio::time::Instant;

pub use latent_rpc::control::v1::{
    ApplyPolicyRequest, ApplyPolicyResponse, CapabilityBindingInspection, CapabilityDescriptor,
    CapabilityInspectionRevision, CapabilityPolicyOperation, CapabilityPolicyRecordKind,
    CapabilityResourceUsage, GetPolicyOperationRequest, GetPolicyOperationResponse,
    GetPolicyRequest, GetPolicyResponse, ListCapabilitiesRequest, ListCapabilitiesResponse,
    ListPoliciesRequest, ListPoliciesResponse, ObjectMetadata, PageRequest, PageResponse, Policy,
};

impl RpcClient {
    pub async fn get_policy_until(
        &self,
        request: GetPolicyRequest,
        deadline: Instant,
    ) -> Result<RpcResponse<GetPolicyResponse>, RpcFailure> {
        bounded_id(&request.id)?;
        let limits = self.limits();
        self.unary(
            request,
            deadline,
            RecoveryIdentity::default(),
            move |channel, request| async move {
                PolicyServiceClient::new(channel)
                    .max_decoding_message_size(limits.maximum_response_bytes)
                    .max_encoding_message_size(limits.maximum_request_bytes)
                    .get_policy(request)
                    .await
            },
        )
        .await
    }

    pub async fn list_policies_until(
        &self,
        request: ListPoliciesRequest,
        deadline: Instant,
    ) -> Result<RpcResponse<ListPoliciesResponse>, RpcFailure> {
        let size = page(request.page.as_ref())?;
        let limits = self.limits();
        let response = self
            .unary(
                request,
                deadline,
                RecoveryIdentity::default(),
                move |channel, request| async move {
                    PolicyServiceClient::new(channel)
                        .max_decoding_message_size(limits.maximum_response_bytes)
                        .max_encoding_message_size(limits.maximum_request_bytes)
                        .list_policies(request)
                        .await
                },
            )
            .await?;
        response_page(
            response.value.page.as_ref(),
            response.value.policies.len(),
            size,
        )
        .map_err(|error| error.received(&RecoveryIdentity::default(), response.audit.as_ref()))?;
        Ok(response)
    }

    pub async fn list_capabilities_until(
        &self,
        request: ListCapabilitiesRequest,
        deadline: Instant,
    ) -> Result<RpcResponse<ListCapabilitiesResponse>, RpcFailure> {
        bounded_id(&request.deployment_id)?;
        for filter in [&request.contract_prefix, &request.provider]
            .into_iter()
            .flatten()
        {
            bounded_id(filter)?;
        }
        let size = page(request.page.as_ref())?;
        let limits = self.limits();
        let response = self
            .unary(
                request,
                deadline,
                RecoveryIdentity::default(),
                move |channel, request| async move {
                    CapabilityServiceClient::new(channel)
                        .max_decoding_message_size(limits.maximum_response_bytes)
                        .max_encoding_message_size(limits.maximum_request_bytes)
                        .list_capabilities(request)
                        .await
                },
            )
            .await?;
        response_page(
            response.value.page.as_ref(),
            response.value.capabilities.len(),
            size,
        )
        .map_err(|error| error.received(&RecoveryIdentity::default(), response.audit.as_ref()))?;
        Ok(response)
    }

    pub async fn apply_policy_until(
        &self,
        request: ApplyPolicyRequest,
        deadline: Instant,
    ) -> Result<RpcResponse<ApplyPolicyResponse>, RpcFailure> {
        bounded_id(&request.operation_id)?;
        let recovery = RecoveryIdentity {
            activation_id: None,
            operation_id: Some(request.operation_id.clone()),
        };
        let invalid = || RpcFailure::local(FailureKind::InvalidRequest).context(&recovery, false);
        if request.operation_id.is_empty() || request.expected_generation.is_none() {
            return Err(invalid());
        }
        let policy = request.policy.as_ref().ok_or_else(invalid)?;
        bounded_id(&policy.id).map_err(|error| error.context(&recovery, false))?;
        if policy.document.len() > self.limits().maximum_request_bytes
            || policy
                .metadata
                .as_ref()
                .and_then(|value| value.tenant.as_ref())
                .is_some_and(|tenant| tenant != &self.inner.tenant.0)
        {
            return Err(invalid());
        }
        let identity = policy.id.clone();
        let limits = self.limits();
        let response = self
            .unary(
                request,
                deadline,
                recovery.clone(),
                move |channel, request| async move {
                    PolicyServiceClient::new(channel)
                        .max_decoding_message_size(limits.maximum_response_bytes)
                        .max_encoding_message_size(limits.maximum_request_bytes)
                        .apply_policy(request)
                        .await
                },
            )
            .await?;
        let invalid = || {
            RpcFailure::local(FailureKind::InvalidResponse)
                .received(&recovery, response.audit.as_ref())
        };
        let policy = response.value.policy.as_ref().ok_or_else(invalid)?;
        let receipt = response.value.receipt.as_ref().ok_or_else(invalid)?;
        if receipt.operation_id != recovery.operation_id.as_deref().unwrap_or_default()
            || receipt.id != identity
            || policy.id != identity
            || receipt.tenant != self.inner.tenant.0
            || receipt.record_kind != policy.record_kind
            || receipt.generation != policy.generation
            || receipt.content_digest != policy.content_digest
            || receipt.revoked != policy.revoked
        {
            return Err(invalid());
        }
        Ok(response)
    }

    pub async fn get_policy_operation_until(
        &self,
        request: GetPolicyOperationRequest,
        deadline: Instant,
    ) -> Result<RpcResponse<GetPolicyOperationResponse>, RpcFailure> {
        bounded_id(&request.operation_id)?;
        let recovery = RecoveryIdentity {
            activation_id: None,
            operation_id: Some(request.operation_id.clone()),
        };
        let limits = self.limits();
        let response = self
            .unary(
                request,
                deadline,
                recovery.clone(),
                move |channel, request| async move {
                    PolicyServiceClient::new(channel)
                        .max_decoding_message_size(limits.maximum_response_bytes)
                        .max_encoding_message_size(limits.maximum_request_bytes)
                        .get_policy_operation(request)
                        .await
                },
            )
            .await?;
        if response.value.receipt.as_ref().is_some_and(|receipt| {
            receipt.operation_id != recovery.operation_id.as_deref().unwrap_or_default()
                || receipt.tenant != self.inner.tenant.0
        }) {
            return Err(RpcFailure::local(FailureKind::InvalidResponse)
                .received(&recovery, response.audit.as_ref()));
        }
        Ok(response)
    }
}

fn page(value: Option<&PageRequest>) -> Result<usize, RpcFailure> {
    let value = value.ok_or_else(|| RpcFailure::local(FailureKind::InvalidRequest))?;
    if !(1..=64).contains(&value.page_size)
        || value
            .page_token
            .as_ref()
            .is_some_and(|token| token.len() > 2048)
    {
        return Err(RpcFailure::local(FailureKind::InvalidRequest));
    }
    Ok(value.page_size as usize)
}

fn response_page(
    value: Option<&PageResponse>,
    count: usize,
    maximum: usize,
) -> Result<(), RpcFailure> {
    let value = value.ok_or_else(|| RpcFailure::local(FailureKind::InvalidResponse))?;
    if count > maximum
        || value
            .next_page_token
            .as_ref()
            .is_some_and(|token| token.is_empty() || token.len() > 2048)
    {
        return Err(RpcFailure::local(FailureKind::InvalidResponse));
    }
    Ok(())
}
