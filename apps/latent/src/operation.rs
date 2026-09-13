//! Fully prepared RPC messages; no file or network work is hidden here.
use latent_rpc::{control::v1 as control, invocation::v1 as invocation};
use prost::Message;

pub enum Operation {
    GetReleaseLifecycle(control::GetReleaseLifecycleRequest),
    LookupReleaseReceipt(control::GetReleaseOperationRequest),
    ChangeReleaseLifecycle(control::ChangeReleaseLifecycleRequest),
    RenewReleaseEvidence(control::RenewReleaseEvidenceRequest),
    LookupDeploymentReceipt(control::GetDeploymentOperationRequest),
    StartRollout(control::StartRolloutRequest),
    ChangeRollout(control::ChangeRolloutRequest),
    GetRollout(control::GetRolloutRequest),
    ListRollouts(control::ListRolloutsRequest),
    LookupRolloutReceipt(control::GetRolloutOperationRequest),
    EvaluateRollout(control::EvaluateRolloutRequest),
    QueryAudit(control::QueryPhase2AuditRequest),
    PublishRelease(control::PublishReleaseRequest),
    GetRelease(control::GetReleaseRequest),
    ListReleases(control::ListReleasesRequest),
    ApplyDeployment(control::ApplyDeploymentRequest),
    GetDeployment(control::GetDeploymentRequest),
    ListDeployments(control::ListDeploymentsRequest),
    DeleteDeployment(control::DeleteDeploymentRequest),
    GetRouteSnapshot(control::GetRouteSnapshotRequest),
    GetNode(control::GetNodeRequest),
    ListNodes(control::ListNodesRequest),
    Invoke(invocation::InvokeRequest),
    Cancel(invocation::CancelRequest),
    GetActivation(invocation::GetActivationRequest),
}
impl Operation {
    pub fn encoded_len(&self) -> usize {
        match self {
            Self::GetReleaseLifecycle(request) => request.encoded_len(),
            Self::LookupReleaseReceipt(request) => request.encoded_len(),
            Self::ChangeReleaseLifecycle(request) => request.encoded_len(),
            Self::RenewReleaseEvidence(request) => request.encoded_len(),
            Self::LookupDeploymentReceipt(request) => request.encoded_len(),
            Self::StartRollout(request) => request.encoded_len(),
            Self::ChangeRollout(request) => request.encoded_len(),
            Self::GetRollout(request) => request.encoded_len(),
            Self::ListRollouts(request) => request.encoded_len(),
            Self::LookupRolloutReceipt(request) => request.encoded_len(),
            Self::EvaluateRollout(request) => request.encoded_len(),
            Self::QueryAudit(request) => request.encoded_len(),
            Self::PublishRelease(request) => request.encoded_len(),
            Self::GetRelease(request) => request.encoded_len(),
            Self::ListReleases(request) => request.encoded_len(),
            Self::ApplyDeployment(request) => request.encoded_len(),
            Self::GetDeployment(request) => request.encoded_len(),
            Self::ListDeployments(request) => request.encoded_len(),
            Self::DeleteDeployment(request) => request.encoded_len(),
            Self::GetRouteSnapshot(request) => request.encoded_len(),
            Self::GetNode(request) => request.encoded_len(),
            Self::ListNodes(request) => request.encoded_len(),
            Self::Invoke(request) => request.encoded_len(),
            Self::Cancel(request) => request.encoded_len(),
            Self::GetActivation(request) => request.encoded_len(),
        }
    }
    pub fn is_invocation(&self) -> bool {
        matches!(
            self,
            Self::Invoke(_) | Self::Cancel(_) | Self::GetActivation(_)
        )
    }
}
