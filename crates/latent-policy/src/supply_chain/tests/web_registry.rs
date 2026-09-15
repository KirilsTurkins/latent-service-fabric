//! Authenticated OCI bytes are still untrusted until the real catalog admits them.
use super::{authority, context, fixture, open, revoke, support, tenant};
use latent_artifacts::{
    package::{
        decode_manifest, decode_referrer, package_digest, EvidenceKind, PackageLimits,
        LAYER_PATH_ANNOTATION,
    },
    AdmissionEvidence, PackageAdmissionUpload,
};
use latent_oci::{
    HttpOciRegistry, OciManifestBytes, OciPushRequest, OciReference, OciRegistry, RegistryConfig,
    RegistryCredentials, RegistryLimits,
};
use latent_packaging::{
    attach_package_sbom, inspect_bundle, BundleInput, PackagingLimits, SbomEvidenceLimits,
};
use std::{io::Read, time::Duration};

const REPOSITORY: &str = "lsf-test/packages";

fn reference(origin: &str, value: &str) -> OciReference {
    OciReference {
        registry: origin.strip_prefix("https://").unwrap().into(),
        repository: REPOSITORY.into(),
        reference: value.into(),
    }
}

fn client(origin: &str) -> HttpOciRegistry {
    HttpOciRegistry::new(RegistryConfig {
        origin: origin.into(),
        repository: REPOSITORY.into(),
        credentials: RegistryCredentials::Basic {
            username: "lsf-test-only".into(),
            password: "lsf-test-only-password".into(),
        },
        addresses: Vec::new(),
        additional_root_certificates: vec![std::fs::read(
            std::env::var("LSF_OCI_TEST_CA_DER").expect("use the owned TLS registry runner"),
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
    })
    .unwrap()
}

fn attach_inventory(upload: &mut PackageAdmissionUpload) {
    let bundle = inspect_bundle(
        BundleInput {
            manifest: upload.manifest.clone(),
            configuration: upload.configuration.clone(),
            layers: upload.layers.clone(),
        },
        PackagingLimits::default(),
    )
    .unwrap();
    let sbom = attach_package_sbom(&bundle, SbomEvidenceLimits::default()).unwrap();
    upload.sboms.push(AdmissionEvidence {
        manifest: sbom.manifest_bytes().to_vec(),
        configuration: sbom.config_bytes().to_vec(),
        payload: sbom.payload_bytes().to_vec(),
    });
}

async fn push(client: &HttpOciRegistry, origin: &str, upload: &PackageAdmissionUpload) {
    let limits = PackageLimits::default();
    let manifest = decode_manifest(&upload.manifest, limits).unwrap();
    let layers: Vec<_> = manifest
        .layers
        .into_iter()
        .map(|descriptor| {
            let path = &descriptor.annotations.as_ref().unwrap()[LAYER_PATH_ANNOTATION];
            let bytes = upload.layers.iter().find(|(name, _)| name == path).unwrap();
            (descriptor, bytes.1.clone())
        })
        .collect();
    let digest = package_digest(&upload.manifest);
    // Keep an immutable retention tag in this disposable registry. OCI digest
    // selection alone does not require a registry to retain an untagged manifest.
    let retained = format!("web-{}", digest.as_str().strip_prefix("sha256:").unwrap());
    for tag in [retained.as_str(), "web-current"] {
        let request = OciPushRequest::new(
            reference(origin, tag),
            OciManifestBytes::new(upload.manifest.clone(), limits.max_document_bytes).unwrap(),
            upload.configuration.clone(),
            layers.clone(),
            limits,
        )
        .unwrap();
        assert_eq!(client.push(request).await.unwrap(), digest);
    }
    for evidence in upload
        .signatures
        .iter()
        .chain(&upload.provenance)
        .chain(&upload.sboms)
    {
        let manifest = decode_referrer(&evidence.manifest, limits).unwrap();
        let digest = package_digest(&evidence.manifest);
        let request = OciPushRequest::new_referrer(
            reference(origin, digest.as_str()),
            OciManifestBytes::new(evidence.manifest.clone(), limits.max_document_bytes).unwrap(),
            evidence.configuration.clone(),
            vec![(manifest.layers[0].clone(), evidence.payload.clone())],
            limits,
        )
        .unwrap();
        assert_eq!(client.push(request).await.unwrap(), digest);
    }
}

async fn pull_evidence(
    client: &HttpOciRegistry,
    origin: &str,
    subject: &OciReference,
    kind: EvidenceKind,
) -> Vec<AdmissionEvidence> {
    let found = client
        .list_referrers(subject, Some(kind.artifact_type()))
        .await
        .unwrap();
    assert_eq!(found.len(), 1);
    let received = client
        .pull_package(&reference(origin, &found[0].digest))
        .await
        .unwrap();
    let request = received.request();
    assert_eq!(
        request.referrer().unwrap().subject.digest.as_str(),
        subject.reference
    );
    let (_, payload) = request.layers().next().unwrap();
    vec![AdmissionEvidence {
        manifest: request.manifest().as_bytes().to_vec(),
        configuration: request.config_bytes().to_vec(),
        payload: payload.to_vec(),
    }]
    // The registry's returned-byte owner is released before the next pull.
}

async fn pull(client: &HttpOciRegistry, origin: &str, digest: &str) -> PackageAdmissionUpload {
    let subject = reference(origin, digest);
    let received = client.pull_package(&subject).await.unwrap();
    let request = received.request();
    let mut upload = PackageAdmissionUpload {
        manifest: request.manifest().as_bytes().to_vec(),
        configuration: request.config_bytes().to_vec(),
        layers: request
            .layers()
            .map(|(descriptor, bytes)| {
                (
                    descriptor.annotations.as_ref().unwrap()[LAYER_PATH_ANNOTATION].clone(),
                    bytes.to_vec(),
                )
            })
            .collect(),
        signatures: vec![],
        provenance: vec![],
        sboms: vec![],
    };
    drop(received);
    upload.signatures = pull_evidence(client, origin, &subject, EvidenceKind::Signature).await;
    upload.provenance = pull_evidence(client, origin, &subject, EvidenceKind::Provenance).await;
    upload.sboms = pull_evidence(client, origin, &subject, EvidenceKind::Sbom).await;
    upload
}

fn actual_component() -> Vec<u8> {
    let path = std::env::var("LSF_WEB_COMPONENT").expect("pass --web-admission-component");
    let mut bytes = Vec::new();
    std::fs::File::open(path)
        .unwrap()
        .take(1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .unwrap();
    assert!(
        bytes.len() <= 1024 * 1024,
        "use the bounded public web-contract fixture"
    );
    bytes
}

#[tokio::test]
#[ignore = "requires the owned TLS registry and actual public web-contract component; required in CI"]
async fn authenticated_web_registry_admission_roundtrip() {
    let origin = std::env::var("LSF_OCI_TEST_ORIGIN").expect("use the owned TLS registry runner");
    let client = client(&origin);
    let mut fixture = fixture();
    fixture.policy["sbom"]["detached"] = "required".into();
    let component = actual_component();
    let root = tempfile::tempdir().unwrap();
    let authority = authority(&fixture, &root.path().join("trust"));
    let path = root.path().join("catalog");
    let repo = open(&path, &authority);
    let mut publications = Vec::new();
    for (name, renderer) in [("browser", None), ("ssr", Some(component.as_slice()))] {
        let mut original = fixture.web_upload(support::web_input(renderer), true, false);
        attach_inventory(&mut original);
        push(&client, &origin, &original).await;
        let digest = package_digest(&original.manifest);
        let received = pull(&client, &origin, digest.as_str()).await;
        assert_eq!(received.manifest, original.manifest);
        assert_eq!(received.configuration, original.configuration);
        assert_eq!(received.layers, original.layers);
        authority.renew_clock_lease().unwrap();
        let published = repo
            .publish_web_package(context("tests", name, 0), received, &mut |_| Ok(()))
            .unwrap()
            .receipt
            .publication;
        let selected = repo.select_web_publication(&published).unwrap();
        assert_eq!(
            selected.layout().manifest().renderer.is_some(),
            renderer.is_some()
        );
        let url = selected.asset_url("/index.html").unwrap();
        publications.push((published, url));
    }
    // The mutable tag now names SSR. Digest-pinned browser bytes/evidence still
    // select the original componentless publication, including after restart.
    let browser = &publications[0].0;
    let browser_package = repo
        .select_web_publication(browser)
        .unwrap()
        .layout()
        .package()
        .clone();
    let old = pull(&client, &origin, browser_package.as_str()).await;
    authority.renew_clock_lease().unwrap();
    assert_eq!(package_digest(&old.manifest), browser_package);
    assert!(repo
        .publish_web_package(context("tests", "browser", 0), old, &mut |_| Ok(()))
        .is_ok());
    let ssr = &publications[1].0;
    assert_eq!(repo.read_web_renderer(ssr).unwrap().bytes(), component);
    let held = repo.read_web_asset(browser, "/index.html").unwrap();
    revoke(&repo, ssr, "revoke-ssr", 1).unwrap();
    assert!(repo.read_web_renderer(ssr).is_err());
    held.with_current(&tenant(), &mut |check| check.check())
        .unwrap();
    drop(held);
    drop(repo);
    let reopened = open(&path, &authority);
    assert!(reopened.select_web_publication(ssr).is_err());
    assert_eq!(
        reopened
            .select_web_publication(browser)
            .unwrap()
            .asset_url("/index.html")
            .unwrap(),
        publications[0].1
    );
    assert_eq!(
        reopened
            .read_web_asset(browser, "/index.html")
            .unwrap()
            .bytes(),
        b"<h1>Example</h1>"
    );
    client
        .shutdown(tokio::time::Instant::now() + Duration::from_secs(5))
        .await
        .unwrap();
}
