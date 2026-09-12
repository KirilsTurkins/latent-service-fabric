mod cancellation;
mod server;
use super::*;
use crate::args::{PackagePullArgs, PackagePushArgs};
use latent_artifacts::{
    package::{self as format, EvidenceKind, LayerRole, PackageKind},
    AdmissionEvidence, ReleaseEvidenceUpload,
};
use latent_oci::OciReference;
use latent_packaging::{LayerInput, PackageBundle, PackageInput};
use std::{collections::BTreeMap, path::Path};

fn package() -> PackageBundle {
    latent_packaging::build_package(
        PackageInput {
            kind: PackageKind::BrowserAssets,
            name: "site".into(),
            version: "1.0.0".into(),
            entrypoint: "index.html".into(),
            annotations: BTreeMap::new(),
            layers: vec![LayerInput {
                path: "index.html".into(),
                role: LayerRole::Asset,
                media_type: "text/html".into(),
                bytes: b"<p>bounded</p>".to_vec(),
            }],
        },
        super::super::limits(),
    )
    .unwrap()
}
fn evidence(package: &PackageBundle) -> AdmissionEvidence {
    let payload = b"opaque untrusted evidence".to_vec();
    let descriptor = format::ArtifactDescriptor {
        media_type: EvidenceKind::Sbom.payload_media_type().into(),
        digest: format::artifact_blob_digest(&payload),
        size: payload.len() as u64,
        annotations: Some(BTreeMap::from([
            (format::LAYER_PATH_ANNOTATION.into(), "evidence.json".into()),
            (format::LAYER_ROLE_ANNOTATION.into(), "evidence".into()),
        ])),
    };
    let manifest = format::ReferrerManifest {
        schema_version: 2,
        media_type: format::OCI_MANIFEST_MEDIA_TYPE.into(),
        artifact_type: EvidenceKind::Sbom.artifact_type().into(),
        config: format::ArtifactDescriptor {
            media_type: format::EMPTY_CONFIG_MEDIA_TYPE.into(),
            digest: format::artifact_blob_digest(b"{}"),
            size: 2,
            annotations: None,
        },
        layers: vec![descriptor],
        subject: data::subject(package),
        annotations: BTreeMap::new(),
    };
    AdmissionEvidence {
        manifest: format::encode_referrer(&manifest, super::super::limits().package).unwrap(),
        configuration: b"{}".to_vec(),
        payload,
    }
}
fn input(root: &Path, package: &PackageBundle, entry: AdmissionEvidence) -> PackagePushArgs {
    let directory = root.join("package");
    latent_packaging::write_package_directory(package, &directory).unwrap();
    let evidence_root = root.join("evidence");
    latent_packaging::write_package_evidence(
        package.layout().digest(),
        &ReleaseEvidenceUpload {
            sboms: vec![entry],
            ..ReleaseEvidenceUpload::default()
        },
        &evidence_root,
        super::super::MAX_EVIDENCE,
    )
    .unwrap();
    PackagePushArgs {
        directory,
        registry_profile: root.join("unused"),
        reference: "release".into(),
        evidence_index: Some(evidence_root.join("index.json")),
        evidence_root: Some(evidence_root),
    }
}
fn runtime() -> tokio::runtime::Runtime {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap()
}

#[test]
fn copy_budget_and_complete_push_association_are_checked_before_transfer() {
    let root = tempfile::tempdir().unwrap();
    let package = package();
    let args = input(root.path(), &package, evidence(&package));
    let reference = OciReference {
        registry: "localhost".into(),
        repository: "repo".into(),
        reference: String::new(),
    };
    assert!(data::prepare(&args, reference.clone(), &budget::Budget::new(1)).is_err());
    let budget = budget::Budget::new(MAX_GRAPH_BYTES);
    let prepared = data::prepare(&args, reference.clone(), &budget).unwrap();
    assert_eq!(
        prepared.package.value.manifest().as_bytes(),
        package.manifest_bytes()
    );
    assert!(data::copy_package(&prepared.package.value, &budget::Budget::new(1)).is_err());
    let copy = data::copy_package(&prepared.package.value, &budget).unwrap();
    assert_eq!(copy.value.layout().digest(), package.layout().digest());
    let mut changed = evidence(&package);
    let mut manifest =
        format::decode_referrer(&changed.manifest, super::super::limits().package).unwrap();
    manifest.subject.digest = format::package_digest(b"other subject");
    changed.manifest = format::encode_referrer(&manifest, super::super::limits().package).unwrap();
    let other = tempfile::tempdir().unwrap();
    let args = input(other.path(), &package, changed);
    assert!(data::prepare(&args, reference, &budget).is_err());
    for invalid in ["", "../escape", "tag?query", "sha256:bad"] {
        assert!(validate_reference(invalid).is_err());
    }
}

#[test]
fn partial_push_retains_confirmed_package_and_uncertain_evidence_without_retry() {
    runtime().block_on(async {
        let root = tempfile::tempdir().unwrap();
        let package = package();
        let entry = evidence(&package);
        let evidence_digest = format::package_digest(&entry.manifest).to_string();
        let args = input(root.path(), &package, entry);
        let package_digest = package.layout().digest().to_string();
        let confirmed = package_digest.clone();
        let server = server::Server::start(move |method, path, _body| {
            if method == "HEAD" {
                return server::Reply::head();
            }
            if path.ends_with("/manifests/release") {
                return server::Reply::created(&confirmed);
            }
            server::Reply::status(500)
        })
        .await;
        let (registry, reference) = server.client();
        let mut progress = transfer::Progress::default();
        let result = transfer::run(
            &registry,
            reference,
            &PackageCommand::Push(args),
            &budget::Budget::new(MAX_GRAPH_BYTES),
            &mut progress,
            Instant::now() + Duration::from_secs(5),
        )
        .await;
        assert!(result.is_err());
        let summary = progress.summary(true);
        assert_eq!(
            summary["confirmedDigests"],
            serde_json::json!([package_digest])
        );
        assert_eq!(summary["uncertainDigest"], evidence_digest);
        assert_eq!(summary["notAttemptedDigests"], serde_json::json!([]));
        registry
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap();
        let requests = server.stop().await;
        assert_eq!(
            requests
                .iter()
                .filter(|(method, _)| method == "PUT")
                .count(),
            2
        );
        assert!(!requests.iter().any(|(method, _)| method == "POST"));
    });
}

#[test]
fn pull_pins_tag_once_exports_exact_evidence_and_releases_all_owners() {
    runtime().block_on(async {
        let root = tempfile::tempdir().unwrap();
        let package = package();
        let entry = evidence(&package);
        let mut routes = server::pull_routes(&package, &entry);
        let server = server::Server::start(move |method, path, _| {
            assert_eq!(method, "GET");
            routes
                .remove(path)
                .unwrap_or_else(|| server::Reply::status(404))
        })
        .await;
        let (registry, reference) = server.client();
        let args = PackagePullArgs {
            registry_profile: root.path().join("unused"),
            reference: "release".into(),
            output_dir: root.path().join("out"),
            evidence_output: root.path().join("proofs"),
        };
        let command = PackageCommand::Pull(args);
        let mut progress = transfer::Progress::default();
        let result = transfer::run(
            &registry,
            reference,
            &command,
            &budget::Budget::new(MAX_GRAPH_BYTES),
            &mut progress,
            Instant::now() + Duration::from_secs(5),
        )
        .await
        .unwrap();
        assert!(result.outcome_known);
        let read = super::super::read(&root.path().join("out")).unwrap();
        assert_eq!(read.manifest_bytes(), package.manifest_bytes());
        let output = super::super::evidence(
            &root.path().join("proofs/index.json"),
            &root.path().join("proofs"),
            package.layout().digest(),
        )
        .unwrap();
        assert_eq!(output.sboms[0].manifest, entry.manifest);
        assert_eq!(output.sboms[0].payload, entry.payload);
        registry
            .shutdown(Instant::now() + Duration::from_secs(2))
            .await
            .unwrap();
        let usage = registry.usage();
        assert_eq!(usage.retained_bytes, 0);
        let requests = server.stop().await;
        assert_eq!(
            requests
                .iter()
                .filter(|(_, path)| path.ends_with("/manifests/release"))
                .count(),
            1
        );
    });
}
