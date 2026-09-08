//! Fully prepared RPC messages; no file or network work is hidden here.
use latent_rpc::{control::v1 as control, invocation::v1 as invocation};
use prost::Message;

pub enum Operation {
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
