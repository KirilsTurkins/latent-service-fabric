use latent_artifacts::ArtifactRepository;
use latent_wire::management::{proto, ManagementLimits};
use tonic::{Code, Status};

use super::super::support::{artifact, deployment, request, Harness};
use super::{apply, delete};

#[tokio::test]
async fn scoped_pages_preserve_defaults_filters_and_token_expiry() {
    let harness = Harness::new(ManagementLimits {
        default_page_size: 1,
        max_page_size: 2,
        ..ManagementLimits::default()
    })
    .await;
    seed_pages(&harness).await;
    let first = harness
        .deployments_client()
        .list_deployments(request(
            "alice",
            proto::ListDeploymentsRequest {
                service: Some("echo".to_owned()),
                page: None,
            },
        ))
        .await
        .unwrap()
        .into_inner();
    assert_eq!(ids(&first), ["a"]);
    let token = first.page.clone().unwrap().next_page_token.unwrap();
    let zero = list(&harness, "alice", "echo", 0, None).await.unwrap();
    assert_eq!(zero.deployments, first.deployments);
    let next = list(&harness, "alice", "echo", 2, Some(token.clone()))
        .await
        .unwrap();
    assert_eq!(ids(&next), ["b", "c"]);
    assert!(next.page.unwrap().next_page_token.is_none());
    for (identity, service) in [("bob", "echo"), ("alice", "other")] {
        assert_eq!(
            list(&harness, identity, service, 1, Some(token.clone()))
                .await
                .unwrap_err()
                .code(),
            Code::InvalidArgument
        );
    }
    assert_eq!(
        list(&harness, "alice", "echo", 3, None)
            .await
            .unwrap_err()
            .code(),
        Code::ResourceExhausted
    );
    assert_eq!(
        list(&harness, "alice", "", 1, None)
            .await
            .unwrap_err()
            .code(),
        Code::InvalidArgument
    );
    delete(&harness, "alice", "d", None).await.unwrap();
    assert_eq!(
        list(&harness, "alice", "echo", 1, Some(token))
            .await
            .unwrap_err()
            .code(),
        Code::Aborted
    );
    harness.shutdown().await;
}

async fn seed_pages(harness: &Harness) {
    for (tenant, service, marker, ids, identity) in [
        ("acme", "echo", "paging-echo", &["a", "b", "c"][..], "alice"),
        ("acme", "other", "paging-other", &["d"][..], "alice"),
        ("other", "echo", "paging-foreign", &["foreign"][..], "bob"),
    ] {
        let release = harness
            .artifacts
            .publish(artifact(tenant, service, marker))
            .await
            .unwrap();
        for id in ids {
            apply(
                harness,
                identity,
                deployment(id, tenant, service, &release.release_digest),
                Some(0),
            )
            .await
            .unwrap();
        }
    }
}

async fn list(
    harness: &Harness,
    identity: &str,
    service: &str,
    size: u32,
    token: Option<String>,
) -> Result<proto::ListDeploymentsResponse, Status> {
    harness
        .deployments_client()
        .list_deployments(request(
            identity,
            proto::ListDeploymentsRequest {
                service: Some(service.to_owned()),
                page: Some(proto::PageRequest {
                    page_size: size,
                    page_token: token,
                }),
            },
        ))
        .await
        .map(tonic::Response::into_inner)
}

fn ids(page: &proto::ListDeploymentsResponse) -> Vec<&str> {
    page.deployments.iter().map(|row| row.id.as_str()).collect()
}
