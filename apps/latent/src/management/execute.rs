use latent_wire::management::proto::{
    self, deployment_service_client::DeploymentServiceClient,
    node_service_client::NodeServiceClient, release_service_client::ReleaseServiceClient,
    route_service_client::RouteServiceClient,
};

use crate::client::Session;
use crate::error::Failure;
use crate::operation::Operation;
use crate::output::Outcome;

use super::{association, bounds, response};

macro_rules! call {
    ($session:ident, $client:ident, $method:ident, $request:expr) => {{
        let mut client = $client::new($session.channel())
            .max_decoding_message_size($session.max_response_bytes())
            .max_encoding_message_size($session.max_request_bytes());
        let request = $session.request($request)?;
        let value = $session.call(client.$method(request)).await?.into_inner();
        bounds::checked(&value, $session.max_response_bytes())?;
        value
    }};
}

pub async fn execute(operation: Operation, session: &Session) -> Result<Outcome, Failure> {
    match operation {
        Operation::PublishRelease(request) => {
            let digest = publication_digest(&request)?;
            let value = call!(session, ReleaseServiceClient, publish_release, request);
            association::release(
                value.release.as_ref(),
                session.tenant(),
                Some(&digest),
                None,
            )?;
            response::published(value)
        }
        Operation::GetRelease(request) => {
            let digest = request.digest.clone();
            let value = call!(session, ReleaseServiceClient, get_release, request);
            association::release(
                value.release.as_ref(),
                session.tenant(),
                Some(&digest),
                None,
            )?;
            response::got_release(value)
        }
        Operation::ListReleases(request) => list_releases(request, session).await,
        Operation::ApplyDeployment(request) => {
            let id = request
                .deployment
                .as_ref()
                .ok_or_else(|| {
                    Failure::local("invalid-deployment", "A validated deployment is required.")
                })?
                .id
                .clone();
            let value = call!(session, DeploymentServiceClient, apply_deployment, request);
            association::deployment(value.deployment.as_ref(), session.tenant(), Some(&id), None)?;
            response::applied(value)
        }
        Operation::GetDeployment(request) => {
            let id = request.id.clone();
            let value = call!(session, DeploymentServiceClient, get_deployment, request);
            association::deployment(value.deployment.as_ref(), session.tenant(), Some(&id), None)?;
            response::got_deployment(value)
        }
        Operation::ListDeployments(request) => list_deployments(request, session).await,
        Operation::DeleteDeployment(request) => {
            let _empty = call!(session, DeploymentServiceClient, delete_deployment, request);
            Ok(Outcome::success(serde_json::json!({})))
        }
        Operation::GetRouteSnapshot(request) => {
            let generation = request.generation;
            let value = call!(session, RouteServiceClient, get_route_snapshot, request);
            association::route(value.snapshot.as_ref(), session.tenant(), generation)?;
            Ok(response::route(value))
        }
        Operation::GetNode(request) => {
            let id = request.node_id.clone();
            let value = call!(session, NodeServiceClient, get_node, request);
            association::node(value.inventory.as_ref(), &id)?;
            response::got_node(value)
        }
        Operation::ListNodes(request) => list_nodes(request, session).await,
        _ => Err(Failure::local(
            "invalid-operation",
            "This is not a management operation.",
        )),
    }
}

async fn list_releases(
    request: proto::ListReleasesRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let service = request.service.clone();
    let page_size = request.page.as_ref().map_or(0, |page| page.page_size);
    let value = call!(session, ReleaseServiceClient, list_releases, request);
    association::page_count(value.releases.len(), page_size)?;
    for row in &value.releases {
        association::release(Some(row), session.tenant(), None, service.as_deref())?;
    }
    response::releases(value)
}

async fn list_deployments(
    request: proto::ListDeploymentsRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let service = request.service.clone();
    let page_size = request.page.as_ref().map_or(0, |page| page.page_size);
    let value = call!(session, DeploymentServiceClient, list_deployments, request);
    association::page_count(value.deployments.len(), page_size)?;
    for row in &value.deployments {
        association::deployment(Some(row), session.tenant(), None, service.as_deref())?;
    }
    response::deployments(value)
}

async fn list_nodes(
    request: proto::ListNodesRequest,
    session: &Session,
) -> Result<Outcome, Failure> {
    let trust_class = request.trust_class.clone();
    let region = request.region.clone();
    let zone = request.zone.clone();
    let page_size = request.page.as_ref().map_or(0, |page| page.page_size);
    let value = call!(session, NodeServiceClient, list_nodes, request);
    association::page_count(value.nodes.len(), page_size)?;
    for row in &value.nodes {
        association::node_filters(
            row,
            trust_class.as_deref(),
            region.as_deref(),
            zone.as_deref(),
        )?;
    }
    response::nodes(value)
}

fn publication_digest(
    request: &latent_wire::management::proto::PublishReleaseRequest,
) -> Result<String, Failure> {
    let artifact = request.artifact.as_ref().ok_or_else(|| {
        Failure::local(
            "invalid-publication",
            "A validated publication upload is required.",
        )
    })?;
    Ok(latent_artifacts::content_digest(&artifact.component_bytes).0)
}
