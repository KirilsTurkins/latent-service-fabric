use super::fixture::*;
use latent_artifacts::{
    LifecycleScope, PublicationRef, ReleaseLifecycleAction, ReleaseLifecycleReason,
};
use latent_core::TenantId;
use latent_ingress::http;
use serde_json::json;
use tempfile::TempDir;
use tokio::io::AsyncWriteExt;

async fn public_call(fixture: &Fixture, path: &str, extra: &str) -> (u16, String, Vec<u8>) {
    let mut socket = fixture.connect().await;
    let request =
        format!("GET {path} HTTP/1.1\r\nHost: {AUTHORITY}\r\nConnection: close\r\n{extra}\r\n");
    socket.write_all(request.as_bytes()).await.unwrap();
    response(&mut socket).await
}
async fn enabled_fixture() -> Fixture {
    let root = TempDir::new().unwrap();
    let mut value = config(&root);
    value["httpIngress"]["authentication"] = json!({
        "mode": "public-origins",
        "origins": [{"authority": AUTHORITY, "subject": "public-web", "tenant": "tests"}]
    });
    let bytes = std::fs::read(std::env::var_os("LSF_WEB_COMPONENT").unwrap()).unwrap();
    let fixture = Fixture::start(root, value.clone(), Some(bytes)).await;
    let reply = public_call(&fixture, "/cache", "").await;
    assert_eq!(reply.0, 200);
    assert!(reply.1.contains("cache-control: no-store\r\n"));
    assert_eq!(
        fixture.node.http_snapshot().unwrap().response_cache_entries,
        0
    );
    let selected = fixture
        .deployments
        .select_http(
            &http::CanonicalTarget::parse(http::Scheme::Http, AUTHORITY, "/cache").unwrap(),
            http::Method::Get,
        )
        .unwrap();
    let revision = selected.revision().expect("application route");
    value["httpIngress"]["responseCache"] = json!([{
        "dependencyProfile": "immutable-public-v1",
        "tenant": "tests", "publication": revision.publication.as_ref().unwrap().as_str(),
        "release": revision.release.0.as_str(), "rendererProfile": http::PROFILE,
        "authority": AUTHORITY, "path": "/cache", "generation": 1,
        "maximumAgeSeconds": 60, "vary": []
    }]);
    drop(selected);
    let root = fixture.shutdown().await;
    Fixture::start(root, value, None).await
}

#[tokio::test]
#[ignore = "requires the public web component built by contract CI"]
async fn actual_http_component_cache_preserves_admission_revocation_and_owner_reclamation() {
    let fixture = enabled_fixture().await;
    let first = public_call(&fixture, "/cache", "").await;
    assert_eq!(first.0, 200);
    assert_eq!(first.2, b"public");
    assert!(!first.1.contains("\r\nage: "));
    fixture.idle().await;
    let stores = fixture.node.backend.resource_snapshot().stores_created;
    let second = public_call(&fixture, "/cache", "").await;
    assert_eq!(second.0, 200);
    assert_eq!(second.2, first.2);
    assert!(second.1.contains("cache-control: no-store\r\n"));
    assert!(second.1.contains("\r\nage: "));
    fixture.idle().await;
    assert_eq!(
        fixture.node.backend.resource_snapshot().stores_created,
        stores
    );
    assert_eq!(
        fixture.node.http_snapshot().unwrap().response_cache_entries,
        1
    );
    for (cookie, personal) in [
        ("Cookie: session=alice\r\n", b"alice".as_slice()),
        ("Cookie: session=bob\r\n", b"bob".as_slice()),
    ] {
        let reply = public_call(&fixture, "/cache", cookie).await;
        assert_eq!(reply.0, 200);
        assert_eq!(reply.2, personal);
        assert!(!reply.1.contains("\r\nage: "));
    }
    fixture.idle().await;
    assert_eq!(
        fixture.node.backend.resource_snapshot().stores_created,
        stores + 2
    );
    let still_public = public_call(&fixture, "/cache", "").await;
    assert_eq!(still_public.2, b"public");
    assert!(still_public.1.contains("\r\nage: "));
    assert_eq!(call(&fixture, "/cache").await.0, 401);
    let selected = fixture
        .deployments
        .select_http(
            &http::CanonicalTarget::parse(http::Scheme::Http, AUTHORITY, "/cache").unwrap(),
            http::Method::Get,
        )
        .unwrap();
    let publication = selected
        .revision()
        .expect("application route")
        .publication
        .clone()
        .unwrap();
    drop(selected);
    fixture
        .artifacts
        .change_publication_lifecycle(
            context("revoke-cache", 1),
            &PublicationRef {
                id: publication,
                scope: LifecycleScope::Tenant(TenantId("tests".into())),
            },
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    let rejected = public_call(&fixture, "/cache", "").await;
    assert_ne!(rejected.0, 200);
    assert_ne!(rejected.2, b"public");
    assert!(!rejected.1.contains("\r\nage: "));
    fixture.idle().await;
    assert_eq!(
        fixture.node.backend.resource_snapshot().stores_created,
        stores + 2
    );
    fixture.shutdown().await;
}
