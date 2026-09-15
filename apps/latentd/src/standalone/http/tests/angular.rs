//! Actual Angular code uses the ordinary catalog, preparation workers, cells,
//! HTTP cancellation handoff and guarded publication start.
use super::fixture::*;
use latent_artifacts::{
    LifecycleScope, PublicationRef, PublicationSelector, ReleaseLifecycleAction,
    ReleaseLifecycleReason,
};
use latent_core::TenantId;
use latent_executor::ExecutionBackend;
use latent_ingress::http;
use latent_manifest::RendererRequirement;
use serde_json::json;
use std::time::{Duration, Instant};
use tempfile::TempDir;
use tokio::io::AsyncWriteExt;

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires LSF_ANGULAR_COMPONENT from the renderer gate"]
#[expect(
    clippy::too_many_lines,
    reason = "one compiled application and its ordered queue, cleanup and revocation owners form this regression"
)]
async fn actual_angular_http_queue_disconnect_recovery_and_revocation() {
    let root = TempDir::new().unwrap();
    let mut value = config(&root);
    value["rendererProfile"] = json!("angular-ssr-component-v1");
    value["limits"]["maximumComponentBytes"] = json!(32 * 1024 * 1024);
    value["execution"]["maximumCpuFuel"] = json!(2_000_000_000u64);
    value["cells"][0]["maximumMemoryBytes"] = json!(256 * 1024 * 1024);
    value["httpIngress"]["limits"]["bodyTimeoutMillis"] = json!(1000);
    let bytes =
        std::fs::read(std::env::var_os("LSF_ANGULAR_COMPONENT").expect("renderer gate fixture"))
            .unwrap();
    let mut artifact = artifact(bytes);
    artifact.manifest.runtime_requirements.renderer = Some(RendererRequirement::angular());
    artifact.manifest.execution.resource_budget_ceiling.cpu_fuel = 2_000_000_000;
    artifact
        .manifest
        .execution
        .resource_budget_ceiling
        .memory_bytes = 256 * 1024 * 1024;
    let fixture = Fixture::start_with_artifact(root, value, Some(artifact)).await;
    let selected = fixture
        .deployments
        .select_http(
            &http::CanonicalTarget::parse(http::Scheme::Http, AUTHORITY, "/").unwrap(),
            http::Method::Get,
        )
        .unwrap();
    let revision = selected.revision().clone();
    drop(selected);
    let mut key = fixture
        .node
        .backend
        .preparation_key(&revision.release)
        .unwrap();
    key.publication.clone_from(&revision.publication);
    // Preparation is a bounded shared control operation, outside the request's
    // five-second activation budget. It cannot retain an application instance.
    // Debug compilation exceeded five minutes on a shared CI runner. Leave
    // headroom for it within the harness's existing ten-minute process limit;
    // the request and cleanup deadlines below are unchanged.
    let preparation_started = Instant::now();
    let ready = tokio::time::timeout(
        Duration::from_mins(8),
        fixture
            .node
            .backend
            .prepare_ready_from_repository(fixture.artifacts.clone(), key),
    )
    .await
    .expect("debug Angular preparation exceeded the eight-minute gate budget")
    .unwrap();
    eprintln!(
        "Angular HTTP: preparation finished in {:?}",
        preparation_started.elapsed()
    );
    drop(fixture.node.backend.materialize_ready(ready).unwrap());
    assert_eq!(fixture.node.backend.resource_snapshot().stores_created, 0);
    let response = call(&fixture, "/").await;
    assert_eq!(response.0, 200);
    assert!(String::from_utf8(response.2).unwrap().contains("ngh="));
    fixture.idle().await;
    assert_eq!(call(&fixture, "/exception").await.0, 502);
    assert_eq!(call(&fixture, "/").await.0, 200);
    let mut first = fixture.connect().await;
    first
        .write_all(request("GET", "/spin", TOKEN, 0, true).as_bytes())
        .await
        .unwrap();
    wait(|| fixture.node.backend.resource_snapshot().active_invocations == 1).await;
    let mut second = fixture.connect().await;
    second
        .write_all(request("GET", "/", TOKEN, 0, true).as_bytes())
        .await
        .unwrap();
    wait(|| {
        fixture
            .node
            .scheduler
            .observations(latent_scheduler::CellClass::Standard)
            .queue_depth
            == 1
    })
    .await;
    assert_eq!(call(&fixture, "/").await.0, 503);
    drop(first);
    assert_eq!(super::fixture::response(&mut second).await.0, 200);
    drop(second);
    fixture.idle().await;
    assert_eq!(fixture.node.cleanup_snapshot().unwrap().handoffs, 1);
    assert_eq!(fixture.node.cleanup_snapshot().unwrap().completed, 1);
    assert_eq!(call(&fixture, "/").await.0, 200);
    fixture.idle().await;
    let mut pending = fixture.connect().await;
    pending
        .write_all(request("POST", "/", TOKEN, 1, true).as_bytes())
        .await
        .unwrap();
    wait(|| fixture.node.http_snapshot().unwrap().exchanges == 1).await;
    let stores = fixture.node.backend.resource_snapshot().stores_created;
    fixture
        .artifacts
        .change_publication_lifecycle(
            context("revoke-angular", 1),
            &PublicationSelector::Publication(PublicationRef {
                id: revision.publication.unwrap(),
                scope: LifecycleScope::Tenant(TenantId("tests".into())),
            }),
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    pending.write_all(b"x").await.unwrap();
    assert_eq!(super::fixture::response(&mut pending).await.0, 503);
    drop(pending);
    fixture.idle().await;
    assert_eq!(
        fixture.node.backend.resource_snapshot().stores_created,
        stores
    );
    fixture.shutdown().await;
}
