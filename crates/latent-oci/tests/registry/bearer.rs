use super::{fixtures, reference, shutdown, REPOSITORY};
use latent_artifacts::package::{decode_referrer, package_digest, PackageLimits};
use latent_core::{PlatformErrorCode, TenantId};
use latent_oci::{
    BearerIdentity, HttpOciRegistry, OciRegistry, RegistryActions, RegistryCredentials,
};
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Credential {
    username: String,
    password: String,
}

fn client(origin: &str, actions: RegistryActions) -> HttpOciRegistry {
    let path = std::env::var("LSF_HARBOR_CREDENTIAL_FILE")
        .expect("run tools/run_harbor_registry_tests.py");
    let bytes = std::fs::read(path).unwrap();
    assert!(bytes.len() <= 4096);
    let credential: Credential = serde_json::from_slice(&bytes).unwrap();
    HttpOciRegistry::new(super::config(
        origin,
        RegistryCredentials::BearerChallenge {
            realm: format!("{origin}/service/token"),
            service: "harbor-registry".into(),
            identity: BearerIdentity {
                tenant: TenantId("lsf-test".into()),
                principal: credential.username.clone(),
                credential_epoch: 1,
            },
            actions,
            username: credential.username,
            password: credential.password,
            addresses: vec![],
        },
    ))
    .unwrap()
}

#[tokio::test]
#[ignore = "requires owned Harbor 2.15.2 fixture: tools/run_harbor_registry_tests.py"]
async fn real_harbor_bearer_roundtrip() {
    let origin =
        std::env::var("LSF_OCI_TEST_ORIGIN").expect("run tools/run_harbor_registry_tests.py");
    let writer = client(&origin, RegistryActions::PullPush);
    let reader = client(&origin, RegistryActions::Pull);
    let (packages, evidence) = fixtures::load();
    let mut package_digests = Vec::new();
    for fixture in &packages {
        let expected = package_digest(&fixture.manifest);
        let tagged = reference(&origin, &fixture.kind);
        assert_eq!(
            writer.push(fixture.request(tagged)).await.unwrap(),
            expected
        );
        let pinned = reference(&origin, expected.as_str());
        assert_eq!(
            reader
                .pull_manifest(&pinned, 64 * 1024)
                .await
                .unwrap()
                .as_bytes(),
            fixture.manifest
        );
        let pulled = reader.pull_package(&pinned).await.unwrap();
        fixture.check(pulled.request());
        package_digests.push(expected.to_string());
    }
    let mut evidence_digests = Vec::new();
    for fixture in &evidence {
        let expected = package_digest(&fixture.manifest);
        let tagged = reference(&origin, &fixture.kind);
        assert_eq!(
            writer.push(fixture.request(tagged)).await.unwrap(),
            expected
        );
        let subject = decode_referrer(&fixture.manifest, PackageLimits::default())
            .unwrap()
            .subject;
        let discovered = reader
            .list_referrers(&reference(&origin, subject.digest.as_str()), None)
            .await
            .unwrap();
        assert!(discovered
            .iter()
            .any(|descriptor| descriptor.digest == expected.as_str()));
        evidence_digests.push(expected.to_string());
    }
    assert_eq!(
        reader
            .push(packages[0].request(reference(&origin, "read-only-must-not-publish")))
            .await
            .unwrap_err()
            .code,
        PlatformErrorCode::PermissionDenied
    );
    assert_eq!(writer.usage().bearer.unwrap().cached_tokens, 1);
    assert_eq!(reader.usage().bearer.unwrap().cached_tokens, 1);
    shutdown(&reader).await;
    shutdown(&writer).await;
    assert_eq!(writer.usage().bearer.unwrap().retained_token_bytes, 0);
    assert_eq!(reader.usage().bearer.unwrap().retained_token_bytes, 0);
    println!(
        "LSF_HARBOR_EVIDENCE {}",
        serde_json::json!({
            "registryVersion": "2.15.2", "repository": REPOSITORY,
            "profile": "lsf-oci-bearer-v1", "authentication": "scoped-challenge",
            "packageDigests": package_digests, "evidenceDigests": evidence_digests,
            "digestPinnedPull": true, "leastPrivilegeWriteDenial": true, "cleanShutdown": true,
            "dnsAndRedirects": "not-tested-here",
        })
    );
}
