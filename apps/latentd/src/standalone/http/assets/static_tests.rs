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
const SITEMAP: &[u8] =
    b"<?xml version=\"1.0\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\"/>";
const NAVIGATION: &str = "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7\r\nSec-Fetch-Mode: navigate\r\nSec-Fetch-Dest: document\r\nSec-Fetch-Site: same-origin\r\n";

fn publish(h: &Harness, operation: &str, page: &[u8]) -> PublicationRef {
    let upload = fixture::configured_upload(
        &[
            ("/exact.html", "text/html", b"asset-shadow"),
            ("/guide/index.html", "text/html", b"guide"),
            ("/index.html", "text/html", page),
            ("/main.js", "text/javascript", b"script"),
            ("/other.html", "text/html", b"explicit"),
            ("/sitemap.xml", "application/xml", SITEMAP),
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
            error_document: None,
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
fn publish_error_site(h: &Harness, operation: &str, error: Option<&[u8]>) -> PublicationRef {
    let upload = fixture::configured_upload(
        &[
            ("/404.html", "text/html", error.unwrap_or(b"unconfigured")),
            ("/guide/index.html", "text/html", b"guide"),
            ("/index.html", "text/html", b"generator root"),
        ],
        Some(StaticWebRouting {
            profile: StaticWebRoutingProfile::StaticSiteV1,
            entry_document: "/index.html".into(),
            directory_index: StaticDirectoryIndexMode::Redirect,
            directory_index_document: "/index.html".into(),
            fallback: StaticWebFallback {
                mode: StaticFallbackMode::None,
                document: None,
            },
            error_document: error.map(|_| StaticWebErrorDocument {
                profile: StaticWebErrorDocumentProfile::HtmlNotFoundV1,
                document: "/404.html".into(),
            }),
        }),
        vec![WebRoute {
            path: "/exact".into(),
            mode: WebRenderMode::Client,
            asset: Some("/index.html".into()),
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
async fn signed_style_policy_requires_host_opt_in_and_never_leaks_through_shared_byte_cache() {
    for enabled in [false, true] {
        let h = Harness::configured_catalog(
            |value| {
                value["httpIngress"]["allowStaticStyleHashes"] = enabled.into();
            },
            None,
            true,
        )
        .await;
        let mut references = Vec::new();
        for (name, hashes) in [
            ("plain", Vec::new()),
            ("style-a", vec![format!("sha256:{}", "00".repeat(32))]),
            ("style-b", vec![format!("sha256:{}", "ff".repeat(32))]),
        ] {
            let upload = fixture::styled_upload(
                &[("/index.html", "text/html", b"same immutable HTML")],
                Some(StaticWebRouting {
                    profile: StaticWebRoutingProfile::StaticSiteV1,
                    entry_document: "/index.html".into(),
                    directory_index: StaticDirectoryIndexMode::Redirect,
                    directory_index_document: "/index.html".into(),
                    fallback: StaticWebFallback {
                        mode: StaticFallbackMode::None,
                        document: None,
                    },
                    error_document: None,
                }),
                Vec::new(),
                hashes.clone(),
            );
            let reference = h
                .repository
                .publish_web_package(fixture::context(name, 0), upload, &mut |_| Ok(()))
                .unwrap()
                .receipt
                .publication;
            for method in ["GET", "HEAD"] {
                apply(
                    &h,
                    &format!("{name}-{method}"),
                    &reference,
                    &format!("/{name}"),
                    "prefix",
                    method,
                    0,
                );
            }
            let expected = if enabled || hashes.is_empty() {
                200
            } else {
                403
            };
            let (status, headers, body) = get(&h, &format!("/{name}/"), "").await;
            assert_eq!(status, expected);
            if expected == 200 {
                assert_eq!(body, b"same immutable HTML");
                let policy = super::csp::policy(&hashes)
                    .unwrap()
                    .unwrap_or_else(|| latent_ingress::http::browser::CSP.into());
                assert!(headers.contains(&format!("content-security-policy: {policy}\r\n")));
                for (method, extra, code) in [
                    ("HEAD", String::new(), 200),
                    ("GET", format!("If-None-Match: {}\r\n", etag(&headers)), 304),
                ] {
                    let response = h
                        .call(method, &format!("/{name}/"), &extra, node::TOKEN)
                        .await;
                    assert_eq!(response.0, code);
                    assert!(response.2.is_empty());
                    assert!(response
                        .1
                        .contains(&format!("content-security-policy: {policy}\r\n")));
                }
                let redirect = get(&h, &format!("/{name}"), "").await;
                assert_eq!(redirect.0, 308);
                assert!(redirect.1.contains(&policy));
            } else {
                assert!(body.is_empty());
                assert!(!headers.contains("'sha256-"));
            }
            references.push(reference);
        }
        assert_ne!(references[0], references[1]);
        assert_ne!(references[1], references[2]);
        let (_, plain, _) = get(&h, "/plain/", "").await;
        assert!(!plain.contains("'sha256-"));
        let (missing, headers, _) = get(&h, "/style-a/missing.js", "").await;
        assert_eq!(missing, 404);
        assert!(!headers.contains("'sha256-"));
        assert!(h.store().snapshot().cache_hits > 0);
        no_execution(&h);
        h.finish().await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn public_document_navigation_never_grants_asset_private_mount_or_unsafe_access() {
    let h = Harness::configured_catalog(|value| {
        value["httpIngress"]["authentication"] = serde_json::json!({"mode":"public-origins", "origins":[
            {"authority":node::AUTHORITY, "subject":"reader", "tenant":"tests"}]});
        value["httpIngress"]["publicDocumentNavigation"] = serde_json::json!([
            {"authority":node::AUTHORITY, "tenant":"tests", "mount":"/docs"}]);
    }, None, true).await;
    let reference = publish(&h, "navigation", b"public document");
    for (id, mount) in [("docs", "/docs"), ("private", "/private")] {
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
    let metadata =
        "Sec-Fetch-Site: cross-site\r\nSec-Fetch-Mode: navigate\r\nSec-Fetch-Dest: document\r\n";
    for (method, path, extra, expected) in [
        ("GET", "/docs/", metadata, 200),
        ("HEAD", "/docs/", metadata, 200),
        ("GET", "/docs/guide", metadata, 308),
        ("GET", "/docs/main.js", metadata, 403),
        ("GET", "/private/", metadata, 403),
        ("GET", "/docs-other/", metadata, 403),
        ("POST", "/docs/", metadata, 403),
        ("OPTIONS", "/docs/", metadata, 403),
        (
            "GET",
            "/docs/",
            "Sec-Fetch-Site: cross-site\r\nSec-Fetch-Mode: cors\r\nSec-Fetch-Dest: empty\r\n",
            403,
        ),
        (
            "GET",
            "/docs/",
            "Sec-Fetch-Site: cross-site\r\nSec-Fetch-Mode: navigate\r\nSec-Fetch-Dest: iframe\r\n",
            403,
        ),
    ] {
        let (status, headers, body) = h.call(method, path, extra, "").await;
        assert_eq!(status, expected, "{method} {path}");
        assert!(!headers
            .to_ascii_lowercase()
            .contains("access-control-allow"));
        assert!(headers.contains("frame-ancestors 'none'"));
        if method == "HEAD" {
            assert!(body.is_empty());
        }
    }
    no_execution(&h);
    h.finish().await;
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
        ("/sitemap.xml", "", SITEMAP),
        ("/docs/sitemap.xml", "", SITEMAP),
        ("/guide/", "", b"guide"),
        ("/docs/guide/", "", b"guide"),
        ("/orders/42?tab=history", NAVIGATION, b"root"),
        ("/docs/orders/42", HTML, b"root"),
    ] {
        let response = get(&h, path, headers).await;
        assert_eq!((response.0, response.2.as_slice()), (200, body), "{path}");
        assert!(response.1.contains("Cache-Control: private, no-cache\r\n"));
        assert!(response.1.contains("Sec-Fetch-Dest"));
        if matches!(path, "/sitemap.xml" | "/docs/sitemap.xml") {
            assert!(response.1.contains("Content-Type: application/xml\r\n"));
            assert!(response
                .1
                .to_ascii_lowercase()
                .contains("x-content-type-options: nosniff\r\n"));
        }
        let conditional = format!("{headers}If-None-Match: {}\r\n", etag(&response.1));
        let cached = get(&h, path, &conditional).await;
        assert_eq!((cached.0, cached.2.len()), (304, 0));
        let head = h.call("HEAD", path, headers, node::TOKEN).await;
        assert_eq!((head.0, head.2.len()), (200, 0));
        assert_eq!(etag(&head.1), etag(&response.1));
        if matches!(path, "/sitemap.xml" | "/docs/sitemap.xml") {
            for headers in [&cached.1, &head.1] {
                assert!(headers
                    .to_ascii_lowercase()
                    .contains("x-content-type-options: nosniff\r\n"));
            }
        }
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
    let error = publish_error_site(&h, "configured-error", Some(b"signed not found"));
    for method in ["GET", "HEAD"] {
        apply(
            &h,
            &format!("root-{method}"),
            &error,
            "/",
            "prefix",
            method,
            1,
        );
        apply(
            &h,
            &format!("error-docs-{method}"),
            &error,
            "/docs/nested",
            "prefix",
            method,
            0,
        );
    }
    for path in [
        "/unknown",
        "/docs/nested/guide/missing",
        "/docs/nested/missing.html",
    ] {
        let (code, headers, body) = get(&h, path, NAVIGATION).await;
        assert_eq!(
            (code, body.as_slice()),
            (404, b"signed not found".as_slice())
        );
        assert!(headers.contains("Cache-Control: private, no-store\r\n"));
        assert!(headers.contains("Content-Type: text/html\r\n"));
        assert!(headers.contains("Content-Length: 16\r\n"));
        assert!(headers
            .to_ascii_lowercase()
            .contains("content-security-policy:"));
        let (head_code, head_headers, body) = h.call("HEAD", path, NAVIGATION, node::TOKEN).await;
        assert_eq!((head_code, body.len()), (404, 0));
        assert_eq!(etag(&head_headers), etag(&headers));
        assert!(head_headers.contains("Content-Length: 16\r\n"));
        for condition in [
            format!("If-None-Match: {}\r\n", etag(&headers)),
            "If-None-Match: *\r\n".into(),
            "If-Match: \"other\"\r\n".into(),
        ] {
            let response = get(&h, path, &format!("{NAVIGATION}{condition}")).await;
            assert_eq!(
                (response.0, response.2.as_slice()),
                (404, b"signed not found".as_slice())
            );
        }
    }
    assert_eq!(get(&h, "/docs/nested/exact", NAVIGATION).await.0, 200);
    assert_eq!(get(&h, "/docs/nested/guide", NAVIGATION).await.0, 308);
    let plain = publish_error_site(&h, "unconfigured-error", None);
    apply(&h, "plain", &plain, "/plain", "prefix", "GET", 0);
    let empty = get(&h, "/plain/unknown", NAVIGATION).await;
    assert_eq!((empty.0, empty.2.len()), (404, 0));
    for (path, headers, status) in [
        ("/docs/nested/missing.js", NAVIGATION, 404),
        ("/docs/nested/missing.css", NAVIGATION, 404),
        ("/docs/nested/missing.png", NAVIGATION, 404),
        ("/docs/nested/missing.woff2", NAVIGATION, 404),
        ("/docs/nested/api/users", NAVIGATION, 404),
        (
            "/docs/nested/unknown",
            "Accept: text/html\r\nSec-Fetch-Mode: cors\r\nSec-Fetch-Dest: empty\r\n",
            404,
        ),
        (
            "/docs/nested/unknown",
            "Accept: text/html\r\nSec-Fetch-Mode: broken\r\n",
            403,
        ),
        ("/docs/nested/unknown", "Accept: */*\r\n", 404),
        (
            "/docs/nested/unknown",
            "Accept: text/html\r\nSec-Fetch-Dest: document\r\nsec-fetch-dest: document\r\n",
            400,
        ),
        ("/docs/nested/unknown", "Accept: broken\r\n", 400),
        (
            "/docs/nested/unknown",
            "Accept: text/html\r\nIf-None-Match: broken\r\n",
            400,
        ),
    ] {
        let response = get(&h, path, headers).await;
        assert_eq!((response.0, response.2.len()), (status, 0), "{path}");
    }
    assert_eq!(
        h.call("POST", "/docs/nested/unknown", HTML, node::TOKEN)
            .await
            .0,
        405
    );
    assert!(matches!(
        h.call("GET", "/docs/nested/unknown", NAVIGATION, "invalid")
            .await
            .0,
        401 | 403
    ));
    let old = get(&h, "/docs/nested/unknown", HTML).await;
    assert_eq!(
        (old.0, old.2.as_slice()),
        (404, b"signed not found".as_slice())
    );
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
    let error_first = publish_error_site(&h, "error-first", Some(b"error A"));
    let error_second = publish_error_site(&h, "error-second", Some(b"error B"));
    let mut error_generation = apply(&h, "error", &error_first, "/errors", "prefix", "GET", 0);
    let first_error = get(&h, "/errors/missing", HTML).await;
    assert_eq!(
        (first_error.0, first_error.2.as_slice()),
        (404, b"error A".as_slice())
    );
    error_generation = apply(
        &h,
        "error",
        &error_second,
        "/errors",
        "prefix",
        "GET",
        error_generation,
    );
    assert_eq!(get(&h, "/errors/missing", HTML).await.2, b"error B");
    apply(
        &h,
        "error",
        &error_first,
        "/errors",
        "prefix",
        "GET",
        error_generation,
    );
    assert_eq!(get(&h, "/errors/missing", HTML).await.2, b"error A");
    h.repository
        .transition_web_publication(
            fixture::context("retire-error", 1),
            &error_first,
            ReleaseLifecycleAction::Retire,
            ReleaseLifecycleReason::OperatorRetirement,
            &mut |_| Ok(()),
        )
        .unwrap();
    let retired = get(&h, "/errors/missing", NAVIGATION).await;
    assert_eq!((retired.0, retired.2.len()), (403, 0));
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
    let error = publish_error_site(&h, "prepared-error", Some(b"prepared not found"));
    for method in ["GET", "HEAD"] {
        apply(
            &h,
            &format!("error-{method}"),
            &error,
            "/errors",
            "prefix",
            method,
            0,
        );
    }
    let initial = get(&h, "/errors/missing", HTML).await;
    assert_eq!(initial.0, 404);
    let raw = node::request("GET", "/errors/missing", node::TOKEN, 0, true);
    let target = CanonicalTarget::parse(Scheme::Http, node::AUTHORITY, "/errors/missing").unwrap();
    let mut request = Request::parse_routed(
        raw.as_bytes(),
        &TenantId("tests".into()),
        error.clone(),
        "/404.html".into(),
    )
    .unwrap();
    request.not_found = true;
    request.route = Some(h.deployments.select_http(&target, Method::Get).unwrap());
    let prepared = h.store().begin(request).unwrap().await.unwrap().unwrap();
    assert_eq!(prepared.code, 404);
    h.repository
        .transition_web_publication(
            fixture::context("revoke-error", 1),
            &error,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert_eq!(prepared.accept(&TenantId("tests".into())), Err(403));
    drop(prepared);
    for method in ["GET", "HEAD"] {
        let rejected = h
            .call(method, "/errors/missing", NAVIGATION, node::TOKEN)
            .await;
        assert_eq!((rejected.0, rejected.2.len()), (403, 0));
    }
    no_execution(&h);
    h.finish().await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn static_concurrency_corruption_and_read_saturation_never_enter_renderer_or_fallback() {
    let h = Harness::static_site().await;
    let reference = publish(&h, "first", b"root");
    apply(&h, "root", &reference, "/", "prefix", "GET", 0);
    for _ in 0..4 {
        // Receiving EOF can precede the server's final owner retirement. Each
        // round deliberately uses exactly the two available ingress exchanges.
        node::wait(|| {
            let snapshot = h.owner.handle().snapshot();
            snapshot.connections == 0 && snapshot.exchanges == 0
        })
        .await;
        let (left, right) = tokio::join!(get(&h, "/index.html", ""), get(&h, "/orders/42", HTML));
        // Mandatory catalog read admission is nonqueueing and can report busy
        // before asset dispatch. Every admitted response must remain coherent;
        // a bounded rejection must never turn into HTML or renderer fallback.
        for (status, headers, bytes) in [left, right] {
            match status {
                200 => assert_eq!(bytes, b"root"),
                503 => {
                    assert!(bytes.is_empty());
                    assert!(headers.contains("Cache-Control: no-store"));
                }
                other => panic!("unexpected concurrent status: {other}"),
            }
        }
        node::wait(|| {
            let snapshot = h.owner.handle().snapshot();
            snapshot.connections == 0 && snapshot.exchanges == 0
        })
        .await;
        let recovered = get(&h, "/orders/42", HTML).await;
        assert_eq!(
            (recovered.0, recovered.2.as_slice()),
            (200, b"root".as_slice())
        );
    }
    let store = h.store();
    // Client EOF is not the completion signal for the blocking read owner.
    // Saturate only after that owner and its ingress exchange have retired.
    node::wait(|| {
        let snapshot = h.owner.handle().snapshot();
        snapshot.connections == 0
            && snapshot.exchanges == 0
            && store.work.available_permits() == super::MAX_READS
    })
    .await;
    let rejected_before_saturation = store.snapshot().capacity_rejections;
    let held = Arc::clone(&store.work)
        .try_acquire_many_owned(u32::try_from(super::MAX_READS).unwrap())
        .unwrap();
    for path in ["/index.html", "/guide/", "/orders/42"] {
        assert_eq!(get(&h, path, HTML).await.0, 503);
    }
    assert_eq!(
        store.snapshot().capacity_rejections,
        rejected_before_saturation + 3
    );
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
    let error = publish_error_site(&h, "corrupt-error", Some(b"unique error document"));
    apply(&h, "error", &error, "/errors", "prefix", "GET", 0);
    let digest = latent_artifacts::package::artifact_blob_digest(b"unique error document");
    std::fs::write(
        h.repository
            .root()
            .join("blobs")
            .join(digest.as_str().strip_prefix("sha256:").unwrap()),
        b"corrupt",
    )
    .unwrap();
    let rejected = get(&h, "/errors/missing", NAVIGATION).await;
    assert_eq!((rejected.0, rejected.2.len()), (502, 0));
    assert_eq!(get(&h, "/errors/guide/", HTML).await.0, 200);
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
