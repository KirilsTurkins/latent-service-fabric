use latent_artifacts::ArtifactRepository;
use latent_control_store::CompiledRouteStore;
use latent_wire::management::{proto, ManagementLimits};
use tonic::{Code, Request};

use super::super::support::{artifact, deployment, Harness};
use super::{apply, delete, get};

#[tokio::test]
async fn authenticated_admin_is_tenant_scoped_and_invalid_apply_never_commits() {
    let harness = Harness::new(ManagementLimits::default()).await;
    let release = harness
        .artifacts
        .publish(artifact("acme", "echo", "auth"))
        .await
        .unwrap();
    let desired = deployment("ship", "acme", "echo", &release.release_digest);
    let message = proto::ApplyDeploymentRequest {
        deployment: Some(desired.clone()),
        expected_generation: Some(0),
    };
    assert_eq!(
        harness
            .deployments_client()
            .apply_deployment(Request::new(message))
            .await
            .unwrap_err()
            .code(),
        Code::Unauthenticated
    );
    for identity in ["caller", "bob"] {
        assert_eq!(
            apply(&harness, identity, desired.clone(), Some(0))
                .await
                .unwrap_err()
                .code(),
            Code::PermissionDenied
        );
    }
    let generation = harness.deployments.current().await.unwrap().generation;
    for (invalid, code) in invalid_inputs(&desired) {
        assert_eq!(
            apply(&harness, "alice", invalid, None)
                .await
                .unwrap_err()
                .code(),
            code
        );
    }
    assert_eq!(
        harness.deployments.current().await.unwrap().generation,
        generation
    );
    apply(&harness, "alice", desired, Some(0)).await.unwrap();
    assert!(get(&harness, "bob", "ship").await.is_none());
    assert_eq!(
        delete(&harness, "bob", "ship", None)
            .await
            .unwrap_err()
            .code(),
        Code::NotFound
    );
    let missing = deployment(
        "absent-release",
        "acme",
        "echo",
        &latent_artifacts::content_digest(b"unpublished"),
    );
    assert_eq!(
        apply(&harness, "alice", missing, None)
            .await
            .unwrap_err()
            .code(),
        Code::NotFound
    );
    harness.shutdown().await;
}

fn invalid_inputs(desired: &proto::Deployment) -> [(proto::Deployment, Code); 4] {
    let mut wrong_name = desired.clone();
    "different".clone_into(&mut wrong_name.metadata.as_mut().unwrap().name);
    let mut later_phase = desired.clone();
    later_phase.resources.as_mut().unwrap().child_calls = 1;
    let mut no_tenant = desired.clone();
    no_tenant.metadata.as_mut().unwrap().tenant = None;
    let mut oversized = desired.clone();
    oversized.id = "x".repeat(513);
    [
        (wrong_name, Code::InvalidArgument),
        (later_phase, Code::InvalidArgument),
        (no_tenant, Code::PermissionDenied),
        (oversized, Code::ResourceExhausted),
    ]
}
