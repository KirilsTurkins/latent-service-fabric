#[path = "deployment/authorization.rs"]
mod authorization;
#[path = "deployment/pagination.rs"]
mod pagination;
#[path = "deployment/versions.rs"]
mod versions;

use latent_wire::management::proto;
use tonic::{Response, Status};

use super::support::{request, Harness};

async fn apply(
    harness: &Harness,
    identity: &str,
    desired: proto::Deployment,
    expected: Option<u64>,
) -> Result<proto::Deployment, Status> {
    harness
        .deployments_client()
        .apply_deployment(request(
            identity,
            proto::ApplyDeploymentRequest {
                deployment: Some(desired),
                expected_generation: expected,
            },
        ))
        .await
        .map(|response| response.into_inner().deployment.unwrap())
}

async fn get(harness: &Harness, identity: &str, id: &str) -> Option<proto::Deployment> {
    harness
        .deployments_client()
        .get_deployment(request(
            identity,
            proto::GetDeploymentRequest { id: id.to_owned() },
        ))
        .await
        .unwrap()
        .into_inner()
        .deployment
}

async fn delete(
    harness: &Harness,
    identity: &str,
    id: &str,
    expected: Option<u64>,
) -> Result<Response<proto::Empty>, Status> {
    harness
        .deployments_client()
        .delete_deployment(request(
            identity,
            proto::DeleteDeploymentRequest {
                id: id.to_owned(),
                expected_generation: expected,
            },
        ))
        .await
}
