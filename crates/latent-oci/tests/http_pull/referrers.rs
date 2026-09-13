use super::support::{Fixture, Reply, Server};
use latent_artifacts::package::{package_digest, OCI_MANIFEST_MEDIA_TYPE};
use latent_core::PlatformErrorCode;
use latent_oci::{OciRegistry, RegistryLimits};
use serde_json::{json, Value};

const INDEX: &str = "application/vnd.oci.image.index.v1+json";
const SIGNATURE: &str = "application/vnd.latent.signature.v1";
const SBOM: &str = "application/vnd.latent.sbom.v1";

fn subject() -> String {
    format!("sha256:{}", "a".repeat(64))
}

fn descriptor(digit: char, kind: &str) -> Value {
    json!({
        "mediaType": OCI_MANIFEST_MEDIA_TYPE,
        "digest": format!("sha256:{}", digit.to_string().repeat(64)),
        "size": 10,
        "artifactType": kind,
    })
}

fn page(entries: &[Value]) -> Vec<u8> {
    serde_json::to_vec(&json!({"schemaVersion":2,"mediaType":INDEX,"manifests":entries})).unwrap()
}

#[tokio::test]
async fn tag_is_pinned_and_filtering_is_applied_after_bounded_pagination() {
    let fixture = Fixture::load(false);
    let expected = package_digest(&fixture.manifest);
    let server = Server::start(move |path| {
        if path.contains("/manifests/") {
            return fixture.reply(path);
        }
        if path.contains("page=2") {
            Reply::ok(INDEX, page(&[descriptor('3', SIGNATURE)]))
        } else {
            // The server deliberately ignores the requested type filter.
            Reply::ok(
                INDEX,
                page(&[descriptor('1', SIGNATURE), descriptor('2', SBOM)]),
            )
            .header("Link", "<?page=2>; rel=\"next\"")
        }
    })
    .await;
    let registry = server.registry(RegistryLimits::default());
    let descriptors = registry
        .list_referrers(&server.reference("latest"), Some(SIGNATURE))
        .await
        .unwrap();
    assert_eq!(descriptors.len(), 2);
    assert!(descriptors
        .iter()
        .all(|value| value.artifact_type.as_deref() == Some(SIGNATURE)));
    let requests = server.requests();
    assert_eq!(requests.len(), 3);
    assert_eq!(requests[0], "/v2/tenant/site/manifests/latest");
    assert!(requests[1].starts_with(&format!(
        "/v2/tenant/site/referrers/{expected}?artifactType="
    )));
    assert_eq!(
        requests[2],
        format!("/v2/tenant/site/referrers/{expected}?page=2")
    );
    assert_eq!(registry.usage().retained_bytes, 0);
}

#[tokio::test]
async fn native_referrers_unavailable_is_an_error_not_an_empty_evidence_set() {
    let server = Server::start(|_| {
        let mut reply = Reply::ok("application/json", b"{}".to_vec());
        reply.status = 404;
        reply
    })
    .await;
    let registry = server.registry(RegistryLimits::default());
    let error = registry
        .list_referrers(&server.reference(&subject()), None)
        .await
        .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
    assert_eq!(error.message, "oci-native-referrers-unsupported");
}

#[tokio::test]
async fn nonmatching_entries_still_consume_the_descriptor_limit() {
    let server =
        Server::start(|_| Reply::ok(INDEX, page(&[descriptor('1', SBOM), descriptor('2', SBOM)])))
            .await;
    let registry = server.registry(RegistryLimits {
        max_referrers: 1,
        ..RegistryLimits::default()
    });
    assert_eq!(
        registry
            .list_referrers(&server.reference(&subject()), Some(SIGNATURE))
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(registry.usage().retained_bytes, 0);
}

#[tokio::test]
async fn repeated_digests_deduplicate_only_when_all_metadata_agrees() {
    for conflicting in [false, true] {
        let server = Server::start(move |_| {
            Reply::ok(
                INDEX,
                page(&[
                    descriptor('1', SIGNATURE),
                    descriptor('1', if conflicting { SBOM } else { SIGNATURE }),
                ]),
            )
        })
        .await;
        let registry = server.registry(RegistryLimits::default());
        let result = registry
            .list_referrers(&server.reference(&subject()), Some(SIGNATURE))
            .await;
        if conflicting {
            assert_eq!(result.unwrap_err().code, PlatformErrorCode::CorruptArtifact);
        } else {
            assert_eq!(result.unwrap().len(), 1);
        }
        assert_eq!(registry.usage().retained_bytes, 0);
    }
}

#[tokio::test]
async fn pagination_rejects_cycles_and_cross_origin_or_subject_targets() {
    for target in [
        "http://127.0.0.1:1/v2/tenant/site/referrers/other".to_owned(),
        format!("/v2/tenant/site/referrers/{}/extra", subject()),
        format!("/v2/tenant/another/referrers/{}", subject()),
        "?page=repeat".to_owned(),
    ] {
        let cycle = target.starts_with('?');
        let server = Server::start(move |_| {
            Reply::ok(INDEX, page(&[])).header("Link", &format!("<{target}>; rel=next"))
        })
        .await;
        let registry = server.registry(RegistryLimits::default());
        assert!(registry
            .list_referrers(&server.reference(&subject()), None)
            .await
            .is_err());
        assert_eq!(server.requests().len(), if cycle { 2 } else { 1 });
        assert_eq!(registry.usage().retained_bytes, 0);
    }
}

#[tokio::test]
async fn page_and_aggregate_byte_limits_stop_before_unbounded_discovery() {
    let server =
        Server::start(|_| Reply::ok(INDEX, page(&[])).header("Link", "<?page=2>; rel=next")).await;
    let registry = server.registry(RegistryLimits {
        max_referrer_pages: 1,
        ..RegistryLimits::default()
    });
    assert_eq!(
        registry
            .list_referrers(&server.reference(&subject()), None)
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(server.requests().len(), 1);
    let maximum = page(&[]).len() - 1;
    let registry = server.registry(RegistryLimits {
        max_referrer_total_bytes: maximum,
        ..RegistryLimits::default()
    });
    assert_eq!(
        registry
            .list_referrers(&server.reference(&subject()), None)
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(registry.usage().retained_bytes, 0);
}
