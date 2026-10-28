//! Actual native sockets and storage with the explicitly test-only authority.
//! Cryptographic publication/browser qualification is a separate signed workflow.
use super::super::super::{fixture, integration::Harness};
use crate::{
    config::NodeConfig,
    standalone::http::{tests::fixture as node, HttpOwner, HttpServices},
};
use latent_artifacts::{web::*, PublicationRef};
use latent_control_store::http_routes::{TriggerOperationContext, TriggerOperationRequest};
use latent_core::{TenantId, TriggerId};
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use serde_json::{json, Value};
use std::time::Duration;
use tokio::time::Instant;

pub(super) const ORIGIN: &str = "https://portal.example.test";
pub(super) const COOKIE: &str = "Cookie: __Host-lsf_demo=test-only\r\n";

pub(super) fn public_config(value: &mut Value) {
    value["httpIngress"]["transport"] =
        json!({"mode": "trusted-proxy", "peers": ["127.0.0.1"]});
    value["httpIngress"]["authentication"] = json!({
        "mode": "public-origins", "origins": [{
            "authority": node::AUTHORITY, "subject": "public-web", "tenant": "tests"
        }]
    });
    value["httpIngress"]["browserOrigins"] = json!([]);
}

pub(super) async fn start() -> Harness {
    Harness::configured_catalog(public_config, None, true).await
}

pub(super) fn publish(h: &Harness, operation: &str, script: &[u8]) -> PublicationRef {
    // Different package identity while preserving the script's exact bytes and
    // ETag: content-addressed bodies must not confer cross-publication authority.
    let document = format!("<!doctype html><title>Never a CORS asset: {operation}</title>");
    let upload = fixture::configured_upload(
        &[
            ("/app.js", "text/javascript", script),
            ("/index.html", "text/html", document.as_bytes()),
            ("/guide/index.html", "text/html", b"<!doctype html><title>Directory</title>"),
            ("/style.css", "text/css", b"body{color:rgb(20,50,80)}"),
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

pub(super) fn grant(publication: &PublicationRef, credentials: &str) -> Value {
    json!({
        "authority": node::AUTHORITY, "tenant": "tests",
        "publication": publication.id.as_str(), "origins": [ORIGIN],
        "credentials": credentials
    })
}

pub(super) async fn restart(h: &mut Harness, grants: Value) {
    let mut value = node::config(&h.node.root);
    public_config(&mut value);
    value["httpIngress"]["bind"] = json!("127.0.0.1:0");
    value["httpIngress"]["crossOriginAssets"] = grants;
    let settings = serde_json::from_value::<NodeConfig>(value)
        .unwrap()
        .derive()
        .unwrap();
    let owner = HttpOwner::start(
        settings.http.unwrap(),
        HttpServices {
            manager: h.node.node.manager.clone(),
            deployments: h.deployments.clone(),
            cleanup: h.node.node.cleanup.as_ref().unwrap().handle(),
            clock: h.node.node.clock.clone(),
            budget: settings.admission.budget_ceiling.clone(),
            transactions: None,
        },
    )
    .unwrap();
    owner.install_assets(h.repository.clone()).unwrap();
    let previous = std::mem::replace(&mut h.owner, owner);
    let handle = previous.handle();
    previous
        .shutdown(Instant::now() + Duration::from_secs(5))
        .await
        .unwrap();
    assert!(handle.snapshot().clean());
    h.owner.handle().start_accepting().unwrap();
}

pub(super) fn apply(h: &Harness, reference: &PublicationRef, method: &str, generation: u64) -> u64 {
    let id = format!("cross-origin-{}", method.to_lowercase());
    let state = h.deployments
        .get_trigger(&TenantId("tests".into()), &TriggerId(id.clone()))
        .unwrap()
        .value()
        .state_version;
    let document = json!({
        "apiVersion": "latent.dev/v1alpha1", "kind": "HttpTrigger",
        "metadata": {"name": id, "tenant": "tests"},
        "spec": {"target": {"kind": "static-web", "publication": reference.id.as_str()},
            "configuration": {"profile": "static-site-v1", "scheme": "https",
                "host": node::AUTHORITY, "path": "/", "pathMatch": "prefix", "method": method}}
    });
    let prepared = h.deployments
        .prepare_trigger_operation(TriggerOperationRequest::Apply {
            context: TriggerOperationContext {
                tenant: TenantId("tests".into()),
                actor: fixture::context("cross-origin", 0).actor,
                operation_id: format!("{id}-{generation}-{state}"),
                expected_state_version: state,
            },
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

pub(super) fn metadata(origin: &str) -> String {
    format!("Origin: {origin}\r\nSec-Fetch-Site: cross-site\r\nSec-Fetch-Mode: cors\r\nSec-Fetch-Dest: empty\r\n")
}

pub(super) fn immutable(reference: &PublicationRef, path: &str) -> String {
    format!("/_lsf/assets/{}{path}", reference.id.as_str())
}

pub(super) async fn call(h: &Harness, method: &str, path: &str, extra: &str) -> (u16, String, Vec<u8>) {
    node::wait(|| {
        let snapshot = h.owner.handle().snapshot();
        snapshot.connections == 0 && snapshot.exchanges == 0
    }).await;
    h.call(method, path, extra, "").await
}

pub(super) fn field<'a>(headers: &'a str, name: &str) -> Option<&'a str> {
    headers.lines().find_map(|line| {
        let (key, value) = line.split_once(':')?;
        key.eq_ignore_ascii_case(name).then_some(value.trim())
    })
}

pub(super) fn authorized(headers: &str, include: bool, error: bool) {
    assert_eq!(field(headers, "access-control-allow-origin"), Some(ORIGIN));
    assert_eq!(field(headers, "access-control-allow-credentials"), include.then_some("true"));
    assert_eq!(field(headers, "cross-origin-resource-policy"), Some("cross-origin"));
    assert_eq!(field(headers, "access-control-expose-headers"), Some("ETag"));
    assert_eq!(field(headers, "cache-control"), Some(if error { "no-store" } else { "private, no-cache" }));
    assert_eq!(field(headers, "vary"), Some(super::super::VARY));
    assert_eq!(field(headers, "x-content-type-options"), Some("nosniff"));
    assert!(field(headers, "set-cookie").is_none());
}

pub(super) fn denied(headers: &str) {
    assert!(field(headers, "access-control-allow-origin").is_none());
    assert_eq!(field(headers, "cross-origin-resource-policy"), Some("same-origin"));
    assert_eq!(field(headers, "cache-control"), Some("no-store"));
}

pub(super) fn no_execution(h: &Harness) {
    let journal = h.node.node.manager.journal().snapshot();
    assert_eq!((journal.begun, journal.active, journal.terminal), (0, 0, 0));
    assert_eq!(h.node.node.manager.observation_snapshot().attempted, 0);
    assert_eq!(h.node.node.quotas.usage().unwrap().active_activations, 0);
    let runtime = h.node.node.backend.resource_snapshot();
    assert_eq!((runtime.stores_created, runtime.live_stores), (0, 0));
}
