//! Real ingress, catalog and shared asset ownership; no executable publication.
use super::{fixture, integration::Harness, Request};
use crate::standalone::http::tests::fixture as node;
use latent_artifacts::{web::*, PublicationRef, ReleaseLifecycleAction, ReleaseLifecycleReason};
use latent_control_store::http_routes::{TriggerOperationContext, TriggerOperationRequest};
use latent_core::{TenantId, TriggerId};
use latent_ingress::http::{CanonicalTarget, Method, Scheme};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use std::{sync::Arc, time::Duration};
use tokio::{io::AsyncWriteExt, net::TcpStream, time::Instant};

const HTML: &str = "Accept: text/html\r\n";
const NAVIGATION: &str = "Accept: text/html\r\nSec-Fetch-Mode: navigate\r\nSec-Fetch-Dest: document\r\nSec-Fetch-Site: same-origin\r\n";

fn publish(h: &Harness, operation: &str, page: &[u8]) -> PublicationRef {
    let upload = fixture::configured_upload(
        &[
            ("/exact.html", "text/html", b"asset-shadow"),
            ("/guide/index.html", "text/html", b"guide"),
            ("/index.html", "text/html", page),
            ("/main.js", "text/javascript", b"script"),
            ("/other.html", "text/html", b"explicit"),
        ],
        Some(StaticWebRouting {
            profile: StaticWebRoutingProfile::StaticSiteV1,
            entry_document: "/index.html".into(),
            directory_index: StaticDirectoryIndexMode::Redirect,
            directory_index_document: "/index.html".into(),
            fallback: StaticWebFallback {
                mode: StaticFallbackMode::Spa,
                document: Some("/index.html".into()),
            },
        }),
        vec![WebRoute {
            path: "/exact.html".into(),
            mode: WebRenderMode::Prerender,
            asset: Some("/other.html".into()),
        }],
    );
    h.repository
        .publish_web_package(fixture::context(operation, 0), upload, &mut |_| Ok(()))
        .unwrap()
        .receipt
        .publication
}
fn context(h: &Harness, id: &str, operation: &str) -> TriggerOperationContext {
    TriggerOperationContext {
        tenant: TenantId("tests".into()),
        actor: fixture::context(operation, 0).actor,
        operation_id: operation.into(),
        expected_state_version: h
            .deployments
            .get_trigger(&TenantId("tests".into()), &TriggerId(id.into()))
            .unwrap()
            .value()
            .state_version,
    }
}
fn apply(
    h: &Harness,
    id: &str,
    reference: &PublicationRef,
    mount: &str,
    kind: &str,
    method: &str,
    generation: u64,
) -> u64 {
    let document = serde_json::json!({"apiVersion":"latent.dev/v1alpha1", "kind":"HttpTrigger", "metadata":{"name":id,"tenant":"tests"},
        "spec":{"target":{"kind":"static-web","publication":reference.id.as_str()},"configuration":{
            "profile":"static-site-v1","scheme":"http","host":node::AUTHORITY,"path":mount,"pathMatch":kind,"method":method}}});
    let operation = format!("{id}-{generation}");
    let mut context = context(h, id, &operation);
    context.operation_id = format!("{operation}-{}", context.expected_state_version);
    let prepared = h
        .deployments
        .prepare_trigger_operation(TriggerOperationRequest::Apply {
            context,
            manifest: JsonManifestCodec::default()
                .decode_trigger(&serde_json::to_vec(&document).unwrap())
                .unwrap(),
            expected_generation: generation,
        })
        .unwrap();
    let result = h.deployments.commit_trigger_operation(prepared).unwrap();
    result.value().durability.as_ref().unwrap();
    result.value().receipt.object_generation
}
fn delete(h: &Harness, id: &str, generation: u64) -> u64 {
    let prepared = h
        .deployments
        .prepare_trigger_operation(TriggerOperationRequest::Delete {
            context: context(h, id, &format!("delete-{id}-{generation}")),
            id: TriggerId(id.into()),
            expected_generation: generation,
        })
        .unwrap();
    let result = h.deployments.commit_trigger_operation(prepared).unwrap();
    result.value().durability.as_ref().unwrap();
    result.value().receipt.object_generation
}
fn etag(headers: &str) -> &str {
    headers
        .lines()
        .find_map(|line| line.strip_prefix("ETag: "))
        .unwrap()
}
fn no_execution(h: &Harness) {
    let journal = h.node.node.manager.journal().snapshot();
    assert_eq!((journal.begun, journal.active, journal.terminal), (0, 0, 0));
    assert_eq!(h.node.node.manager.observation_snapshot().attempted, 0);
    assert_eq!(h.node.node.quotas.usage().unwrap().active_activations, 0);
    let runtime = h.node.node.backend.resource_snapshot();
    assert_eq!((runtime.stores_created, runtime.live_stores), (0, 0));
}
async fn get(h: &Harness, path: &str, headers: &str) -> (u16, String, Vec<u8>) {
    h.call("GET", path, headers, node::TOKEN).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn static_routes_resolve_mounts_routes_assets_indexes_fallback_and_revalidation_without_execution(
) {
    let h = Harness::static_site().await;
    let reference = publish(&h, "first", b"root");
    for (id, mount) in [("root", "/"), ("docs", "/docs")] {
        for method in ["GET", "HEAD"] {
            apply(
                &h,
                &format!("{id}-{method}"),
                &reference,
                mount,
                "prefix",
                method,
                0,
            );
        }
    }
    for (path, headers, body) in [
        ("/", "", b"root".as_slice()),
        ("/docs/", "", b"root"),
        ("/docs/exact.html", "", b"explicit"),
        ("/docs/main.js?version=1", "", b"script"),
        ("/guide/", "", b"guide"),
        ("/docs/guide/", "", b"guide"),
        ("/orders/42?tab=history", NAVIGATION, b"root"),
        ("/docs/orders/42", HTML, b"root"),
    ] {
        let response = get(&h, path, headers).await;
        assert_eq!((response.0, response.2.as_slice()), (200, body), "{path}");
        assert!(response.1.contains("Cache-Control: private, no-cache\r\n"));
        assert!(response.1.contains("Sec-Fetch-Dest"));
        let conditional = format!("{headers}If-None-Match: {}\r\n", etag(&response.1));
        let cached = get(&h, path, &conditional).await;
        assert_eq!((cached.0, cached.2.len()), (304, 0));
        let head = h.call("HEAD", path, headers, node::TOKEN).await;
        assert_eq!((head.0, head.2.len()), (200, 0));
        assert_eq!(etag(&head.1), etag(&response.1));
    }
    for (path, location) in [
        ("/guide", "/guide/"),
        ("/docs", "/docs/"),
        ("/docs/guide?tab=history", "/docs/guide/?tab=history"),
    ] {
        let response = get(&h, path, "").await;
        assert_eq!((response.0, response.2.len()), (308, 0));
        assert!(response.1.contains(&format!("Location: {location}\r\n")));
    }
    let immutable = h
        .repository
        .select_web_publication(&reference)
        .unwrap()
        .asset_url("/index.html")
        .unwrap();
    assert!(get(&h, &immutable, "")
        .await
        .1
        .contains("private, max-age=31536000, immutable"));
    assert!(h.store().snapshot().cache_hits > 0);
    no_execution(&h);
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn static_misses_methods_negotiation_and_hostile_paths_never_become_spa_documents() {
    let h = Harness::static_site().await;
    let reference = publish(&h, "first", b"root");
    apply(&h, "docs", &reference, "/docs", "prefix", "GET", 0);
    for (path, extra, expected) in [
        ("/docs2/", HTML, 404), ("/_lsf/unknown", HTML, 404),
        ("/docs/main.old.js", "Sec-Fetch-Dest: script\r\n", 404),
        ("/docs/style.css", "Sec-Fetch-Mode: no-cors\r\nSec-Fetch-Dest: style\r\n", 404),
        ("/docs/image", "Sec-Fetch-Dest: image\r\n", 404),
        ("/docs/api/users", "Accept: application/json\r\n", 404),
        ("/docs/absent", "", 404), ("/docs/absent", "Accept: */*\r\n", 404),
        ("/docs/absent", "Accept: text/html;q=0\r\n", 404),
        ("/docs/index.html", "Accept: application/json\r\n", 406),
        ("/docs/main.js", "Accept-Encoding: identity;q=0\r\n", 406),
        ("/docs/absent", "Accept: text/html;q=1.1\r\n", 400),
        ("/docs/absent", "Accept: text/html\r\nAccept: text/html\r\n", 400),
        ("/docs/index.html", "If-None-Match: broken\r\n", 400),
        ("/docs/missing", "If-None-Match: broken\r\n", 400),
        ("/docs/orders", "Sec-Fetch-Mode: navigate\r\nSec-Fetch-Dest: document\r\nSec-Fetch-Site: cross-site\r\n", 403),
        ("/docs/%2e%2e/private", HTML, 400), ("/docs%2fguide", HTML, 400),
        ("/docs//guide", HTML, 400), ("/docs/../guide", HTML, 400), ("/docs\\guide", HTML, 400),
    ] {
        let response = get(&h, path, extra).await;
        assert_eq!(response.0, expected, "{path} {extra}");
        assert!(response.2.is_empty());
        assert!(response.1.contains("no-store"));
    }
    for method in ["POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"] {
        assert_eq!(
            h.call(method, "/docs/orders", HTML, node::TOKEN).await.0,
            405,
            "{method}"
        );
    }
    let mut socket = TcpStream::connect(h.owner.local_addr()).await.unwrap();
    socket
        .write_all(node::request("GET", "/docs/index.html", node::TOKEN, 1, true).as_bytes())
        .await
        .unwrap();
    assert_eq!(node::response(&mut socket).await.0, 400);
    drop(socket);
    assert_eq!(h.call("GET", "/docs/", "", node::OTHER).await.0, 403);
    assert_eq!(h.store().snapshot().cache_misses, 0);
    no_execution(&h);
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn static_cutover_rollback_delete_recreate_and_specific_precedence_keep_captured_publication()
{
    let h = Harness::static_site().await;
    let first = publish(&h, "first", b"first");
    let second = publish(&h, "second", b"second");
    apply(&h, "broad", &second, "/", "prefix", "GET", 0);
    let mut generation = apply(&h, "specific", &first, "/docs", "prefix", "GET", 0);
    let target = CanonicalTarget::parse(Scheme::Http, node::AUTHORITY, "/docs/index.html").unwrap();
    let selected = h.deployments.select_http(&target, Method::Get).unwrap();
    let raw = node::request("GET", "/docs/index.html", node::TOKEN, 0, true);
    let mut captured = Request::parse_routed(
        raw.as_bytes(),
        &TenantId("tests".into()),
        first.clone(),
        "/index.html".into(),
    )
    .unwrap();
    captured.route = Some(selected);
    let before = get(&h, "/docs/index.html", "").await;
    generation = apply(
        &h, "specific", &second, "/docs", "prefix", "GET", generation,
    );
    let after = get(
        &h,
        "/docs/index.html",
        &format!("If-None-Match: {}\r\n", etag(&before.1)),
    )
    .await;
    assert_eq!((after.0, after.2.as_slice()), (200, b"second".as_slice()));
    assert_ne!(etag(&before.1), etag(&after.1));
    let held = h.store().begin(captured).unwrap().await.unwrap().unwrap();
    held.accept(&TenantId("tests".into())).unwrap();
    assert_eq!(held.buffer.bytes.as_slice(), b"first");
    drop(held);
    generation = apply(&h, "specific", &first, "/docs", "prefix", "GET", generation);
    assert_eq!(get(&h, "/docs/index.html", "").await.2, b"first");
    delete(&h, "specific", generation);
    assert_eq!(get(&h, "/docs/orders", HTML).await.2, b"second");
    apply(&h, "specific", &first, "/docs", "prefix", "GET", 0);
    apply(&h, "exact", &second, "/docs", "exact", "GET", 0);
    assert_eq!(get(&h, "/docs/index.html", "").await.2, b"first");
    assert_eq!(get(&h, "/docs", HTML).await.0, 308);
    h.repository
        .transition_web_publication(
            fixture::context("revoke", 1),
            &first,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert_eq!(
        get(&h, "/docs/index.html", HTML).await.0,
        403,
        "stale specific route never falls through to broad"
    );
    assert_eq!(get(&h, "/elsewhere", HTML).await.2, b"second");
    no_execution(&h);
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn static_cached_head_and_prepared_304_recheck_current_publication_authority() {
    let h = Harness::static_site().await;
    let reference = publish(&h, "first", b"root");
    for method in ["GET", "HEAD"] {
        apply(&h, method, &reference, "/", "prefix", method, 0);
    }
    let initial = get(&h, "/index.html", "").await;
    let raw = node::request("GET", "/index.html", node::TOKEN, 0, true).replace(
        "\r\n\r\n",
        &format!("\r\nIf-None-Match: {}\r\n\r\n", etag(&initial.1)),
    );
    let target = CanonicalTarget::parse(Scheme::Http, node::AUTHORITY, "/index.html").unwrap();
    let mut request = Request::parse_routed(
        raw.as_bytes(),
        &TenantId("tests".into()),
        reference.clone(),
        "/index.html".into(),
    )
    .unwrap();
    request.route = Some(h.deployments.select_http(&target, Method::Get).unwrap());
    let prepared = h.store().begin(request).unwrap().await.unwrap().unwrap();
    assert_eq!(prepared.code, 304);
    h.repository
        .transition_web_publication(
            fixture::context("revoke", 1),
            &reference,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert_eq!(prepared.accept(&TenantId("tests".into())), Err(403));
    drop(prepared);
    for method in ["GET", "HEAD"] {
        assert_eq!(
            h.call(method, "/index.html", "If-None-Match: *\r\n", node::TOKEN)
                .await
                .0,
            403
        );
    }
    assert!(h.store().snapshot().retained_buffer_bytes > 0);
    no_execution(&h);
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn static_concurrency_corruption_and_read_saturation_never_enter_renderer_or_fallback() {
    let h = Harness::static_site().await;
    let reference = publish(&h, "first", b"root");
    apply(&h, "root", &reference, "/", "prefix", "GET", 0);
    for _ in 0..4 {
        let (left, right) = tokio::join!(get(&h, "/index.html", ""), get(&h, "/orders/42", HTML));
        assert_eq!((left.0, right.0), (200, 200));
    }
    let store = h.store();
    let held = Arc::clone(&store.work).try_acquire_many_owned(4).unwrap();
    for path in ["/index.html", "/guide/", "/orders/42"] {
        assert_eq!(get(&h, path, HTML).await.0, 503);
    }
    assert_eq!(store.snapshot().capacity_rejections, 3);
    drop(held);
    let digest = latent_artifacts::package::artifact_blob_digest(b"script");
    std::fs::write(
        h.repository
            .root()
            .join("blobs")
            .join(digest.as_str().strip_prefix("sha256:").unwrap()),
        b"broken",
    )
    .unwrap();
    assert_eq!(
        get(&h, "/main.js", "Accept: text/html, text/javascript\r\n")
            .await
            .0,
        502
    );
    assert_eq!(
        get(&h, "/missing.js", "Sec-Fetch-Dest: script\r\n").await.0,
        404
    );
    no_execution(&h);
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn static_disconnect_and_shutdown_retain_actual_blocking_read_and_captured_route() {
    let h = Harness::static_site().await;
    let reference = publish(&h, "first", b"root");
    let generation = apply(&h, "root", &reference, "/", "prefix", "GET", 0);
    let store = h.store();
    let (entered, started) = std::sync::mpsc::channel();
    let (resume, blocked) = std::sync::mpsc::channel();
    *store.pause.lock().unwrap() = Some((entered, blocked));
    let mut socket = TcpStream::connect(h.owner.local_addr()).await.unwrap();
    socket
        .write_all(node::request("GET", "/index.html", node::TOKEN, 0, true).as_bytes())
        .await
        .unwrap();
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    delete(&h, "root", generation);
    drop(socket);
    node::wait(|| h.owner.handle().snapshot().connections == 0).await;
    assert_eq!(store.snapshot().active_reads, 1);
    assert!(
        !store
            .shutdown(Instant::now() + Duration::from_millis(10))
            .await
    );
    assert_eq!(store.snapshot().active_reads, 1);
    no_execution(&h);
    resume.send(()).unwrap();
    node::wait(|| store.snapshot().active_reads == 0).await;
    h.finish().await;
}
