mod association;
mod inventory;
mod preparation;

use latent_control_store::VersionedDeployment;
use latent_manifest::ManifestCodec;
use latent_wire::management::{deployment_to_proto, proto};

use super::{bounds, node, prepare, response};

fn release() -> proto::ReleaseDescriptor {
    proto::ReleaseDescriptor {
        digest: format!("sha256:{}", "a".repeat(64)),
        artifact_reference: "local:release:opaque".to_owned(),
        service: "examples/echo".to_owned(),
        semantic_version: "0.1.0".to_owned(),
        world: "examples:echo/service@0.1.0".to_owned(),
        publisher: String::new(),
        media_type: "application/wasm".to_owned(),
        size_bytes: u64::MAX,
        created_at_unix_millis: 0,
        admitted: true,
        annotations: [("purpose".to_owned(), "quoted\n\"value".to_owned())].into(),
        tenant: Some("examples".to_owned()),
    }
}

fn deployment() -> proto::Deployment {
    let manifest = prepare::codec()
        .decode_deployment(include_bytes!(
            "../../../../examples/echo-contract/deployment.json"
        ))
        .unwrap();
    deployment_to_proto(&VersionedDeployment {
        manifest,
        generation: u64::MAX,
    })
    .unwrap()
}

#[test]
fn release_receipt_keeps_exact_decimal_size_and_optional_publisher() {
    let expected = release();
    bounds::checked(&expected, 4096).unwrap();
    let value = response::release(expected).unwrap();
    assert_eq!(value["sizeBytes"], u64::MAX.to_string());
    assert_eq!(value["publisher"], serde_json::Value::Null);
    assert_eq!(value["createdAtUnixMillis"], "0");
    assert_eq!(value["admitted"], true);
    assert_eq!(value["annotations"]["purpose"], "quoted\n\"value");
    let encoded = serde_json::to_string(&value).unwrap();
    assert!(!encoded.contains('\n'));
}

#[test]
fn unrepresentable_publication_receipts_are_rejected_without_coercion() {
    let mut value = release();
    value.created_at_unix_millis = 1;
    assert!(response::release(value).is_err());
    let mut value = release();
    value.admitted = false;
    assert!(response::release(value).is_err());
    assert!(response::published(proto::PublishReleaseResponse::default()).is_err());
}

#[test]
fn deployment_version_is_exact_and_manifest_numeric_fields_stay_canonical() {
    let expected = deployment();
    bounds::checked(&expected, 4096).unwrap();
    let value = response::deployment(expected).unwrap();
    assert_eq!(value["generation"], u64::MAX.to_string());
    assert_eq!(value["manifest"]["metadata"]["name"], "echo-production");
    assert_eq!(value["manifest"]["spec"]["resources"]["cpuFuel"], 1_000_000);
    assert!(value.get("catalogGeneration").is_none());
}

#[test]
fn malformed_deployment_identity_and_missing_budget_fail_conversion() {
    let mut value = deployment();
    value.id = "another-deployment".to_owned();
    assert!(response::deployment(value).is_err());
    let mut value = deployment();
    value.resources = None;
    assert!(response::deployment(value).is_err());
    let mut value = deployment();
    value.generation = 0;
    assert!(bounds::checked(&value, 4096).is_err());
}

#[test]
fn bounded_traversal_rejects_large_collections_strings_and_page_tokens() {
    let mut value = proto::ListReleasesResponse {
        releases: vec![release()],
        page: Some(proto::PageResponse::default()),
    };
    assert!(bounds::checked(&value, 1).is_err());
    value.releases[0]
        .annotations
        .insert("large".to_owned(), "x".repeat(4097));
    assert!(bounds::checked(&value, 1024 * 1024).is_err());
    value.releases.clear();
    value.page.as_mut().unwrap().next_page_token = Some("x".repeat(8193));
    assert!(bounds::checked(&value, 1024 * 1024).is_err());
    value.page = Some(proto::PageResponse::default());
    value.releases = vec![proto::ReleaseDescriptor::default(); 4097];
    assert!(bounds::checked(&value, 1024 * 1024).is_err());
}

#[test]
fn route_scope_mismatch_is_not_rendered_as_a_successful_projection() {
    let value = proto::GetRouteSnapshotResponse {
        snapshot: Some(proto::RouteSnapshot {
            tenant: Some("examples".to_owned()),
            snapshot_digest: format!("sha256:{}", "a".repeat(64)),
            services: vec![proto::ServiceRoute {
                route_id: "route".to_owned(),
                service: "examples/echo".to_owned(),
                tenant: "foreign".to_owned(),
                revisions: Vec::new(),
            }],
            ..proto::RouteSnapshot::default()
        }),
    };
    assert!(bounds::checked(&value, 4096).is_err());
}
