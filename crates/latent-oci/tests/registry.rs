//! Exact byte distribution fixtures; no guest execution or evidence trust claim.
#[path = "registry/fixtures.rs"]
mod fixtures;

use std::time::Duration;

use latent_artifacts::package::{package_digest, PackageLimits, OCI_MANIFEST_MEDIA_TYPE};
use latent_core::PlatformErrorCode;
use latent_oci::{
    HttpOciRegistry, OciReference, OciRegistry, RegistryConfig, RegistryCredentials, RegistryLimits,
};

const REPOSITORY: &str = "lsf-test/packages";

fn config(origin: &str, credentials: RegistryCredentials) -> RegistryConfig {
    RegistryConfig {
        origin: origin.into(),
        repository: REPOSITORY.into(),
        credentials,
        addresses: Vec::new(),
        additional_root_certificates: vec![std::fs::read(
            std::env::var("LSF_OCI_TEST_CA_DER").expect("run tools/run_oci_registry_tests.py"),
        )
        .unwrap()],
        allow_insecure_loopback: false,
        limits: RegistryLimits {
            max_retained_bytes: 2 * 1024 * 1024,
            connect_timeout: Duration::from_secs(2),
            request_timeout: Duration::from_secs(5),
            operation_timeout: Duration::from_secs(15),
            cleanup_timeout: Duration::from_secs(2),
            ..RegistryLimits::default()
        },
    }
}

fn credentials() -> RegistryCredentials {
    RegistryCredentials::Basic {
        username: "lsf-test-only".into(),
        password: "lsf-test-only-password".into(),
    }
}

fn reference(origin: &str, value: &str) -> OciReference {
    OciReference {
        registry: origin.strip_prefix("https://").unwrap().into(),
        repository: REPOSITORY.into(),
        reference: value.into(),
    }
}

async fn shutdown(client: &HttpOciRegistry) {
    client
        .shutdown(tokio::time::Instant::now() + Duration::from_secs(5))
        .await
        .unwrap();
}

async fn roundtrips(client: &HttpOciRegistry, origin: &str, packages: &[fixtures::Fixture]) {
    for fixture in packages {
        let tagged = reference(origin, &fixture.kind);
        let expected = package_digest(&fixture.manifest);
        assert_eq!(
            client.push(fixture.request(tagged.clone())).await.unwrap(),
            expected
        );
        assert_eq!(
            client.push(fixture.request(tagged.clone())).await.unwrap(),
            expected
        );
        let resolved = client.resolve(&tagged).await.unwrap().unwrap();
        assert_eq!(resolved.digest, expected.as_str());
        assert_eq!(resolved.size_bytes, fixture.manifest.len() as u64);
        assert_eq!(resolved.media_type, OCI_MANIFEST_MEDIA_TYPE);
        let pinned = reference(origin, expected.as_str());
        let received = client
            .pull_manifest(&pinned, PackageLimits::default().max_document_bytes)
            .await
            .unwrap();
        assert_eq!(received.as_bytes(), fixture.manifest);
        fixture.check(client.pull_package(&pinned).await.unwrap().request());
        fixture.check(client.pull_package(&tagged).await.unwrap().request());
    }
}

async fn tag_move(client: &HttpOciRegistry, origin: &str, packages: &[fixtures::Fixture]) {
    let browser = packages
        .iter()
        .find(|fixture| fixture.kind == "browser-assets")
        .unwrap();
    let ssr = packages
        .iter()
        .find(|fixture| fixture.kind == "ssr-package")
        .unwrap();
    // A second client moves the mutable tag after the first has resolved it.
    // Following content/evidence by the pinned digest must retain package A.
    let moved = reference(origin, "moves-after-resolution");
    client.push(browser.request(moved.clone())).await.unwrap();
    let pinned_before = client.resolve(&moved).await.unwrap().unwrap().digest;
    let writer = HttpOciRegistry::new(config(origin, credentials())).unwrap();
    writer.push(ssr.request(moved.clone())).await.unwrap();
    browser.check(
        client
            .pull_package(&reference(origin, &pinned_before))
            .await
            .unwrap()
            .request(),
    );
    ssr.check(client.pull_package(&moved).await.unwrap().request());
    shutdown(&writer).await;
}

async fn referrers(
    client: &HttpOciRegistry,
    origin: &str,
    subject: &OciReference,
    evidence: &[fixtures::Fixture],
) {
    assert!(client
        .list_referrers(subject, None)
        .await
        .unwrap()
        .is_empty());
    for fixture in evidence {
        let tagged = reference(origin, &fixture.kind);
        let expected = package_digest(&fixture.manifest);
        assert_eq!(
            client.push(fixture.request(tagged.clone())).await.unwrap(),
            expected
        );
        assert_eq!(
            client.push(fixture.request(tagged)).await.unwrap(),
            expected
        );
        let received = client
            .pull_package(&reference(origin, expected.as_str()))
            .await
            .unwrap();
        fixture.check(received.request());
        assert_eq!(
            received
                .request()
                .referrer()
                .unwrap()
                .subject
                .digest
                .as_str(),
            subject.reference
        );
        let artifact_type = fixture
            .request(subject.clone())
            .referrer()
            .unwrap()
            .artifact_type
            .clone();
        let found = client
            .list_referrers(subject, Some(&artifact_type))
            .await
            .unwrap();
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].digest, expected.as_str());
        assert_eq!(
            found[0].artifact_type.as_deref(),
            Some(artifact_type.as_str())
        );
    }
    let all = client.list_referrers(subject, None).await.unwrap();
    assert_eq!(
        all.len(),
        3,
        "idempotent evidence pushes must not duplicate referrers"
    );
    for fixture in evidence {
        assert!(all
            .iter()
            .any(|item| item.digest == package_digest(&fixture.manifest).as_str()));
    }
}

async fn authentication(origin: &str, subject: &OciReference) {
    for rejected in [
        RegistryCredentials::Anonymous,
        RegistryCredentials::Basic {
            username: "lsf-test-only".into(),
            password: "deliberately-wrong".into(),
        },
    ] {
        let denied = HttpOciRegistry::new(config(origin, rejected)).unwrap();
        let error = denied.resolve(subject).await.unwrap_err();
        assert_eq!(error.code, PlatformErrorCode::Unauthenticated);
        assert!(!error.message.contains("deliberately-wrong"));
        assert!(!error.message.contains("lsf-test-only-password"));
        shutdown(&denied).await;
    }
    let mut untrusted_config = config(origin, credentials());
    untrusted_config.additional_root_certificates.clear();
    let untrusted = HttpOciRegistry::new(untrusted_config).unwrap();
    assert!(
        untrusted.resolve(subject).await.is_err(),
        "test CA must be explicitly trusted"
    );
    shutdown(&untrusted).await;
}

#[tokio::test]
#[ignore = "requires the owned TLS registry from tools/run_oci_registry_tests.py"]
async fn real_tls_registry_roundtrips_tag_race_auth_and_referrers() {
    let origin = std::env::var("LSF_OCI_TEST_ORIGIN").expect("run tools/run_oci_registry_tests.py");
    let client = HttpOciRegistry::new(config(&origin, credentials())).unwrap();
    let (packages, evidence) = fixtures::load();
    assert_eq!(packages.len(), 3);
    assert_eq!(evidence.len(), 3);
    let capsule = packages
        .iter()
        .find(|fixture| fixture.kind == "capsule")
        .unwrap();
    let subject = reference(&origin, package_digest(&capsule.manifest).as_str());
    roundtrips(&client, &origin, &packages).await;
    tag_move(&client, &origin, &packages).await;
    referrers(&client, &origin, &subject, &evidence).await;
    authentication(&origin, &subject).await;
    shutdown(&client).await;
}
