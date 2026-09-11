use crate::{OciManifestBytes, OciReference};
use latent_artifacts::package::{
    artifact_blob_digest, encode_config, encode_manifest, encode_referrer, package_digest,
    ArtifactDescriptor as LayerDescriptor, EvidenceKind, LayerRole, PackageConfig, PackageKind,
    PackageLayer, PackageLimits, PackageManifest, PackageSubject, ReferrerManifest,
    EMPTY_CONFIG_MEDIA_TYPE, LAYER_PATH_ANNOTATION, LAYER_ROLE_ANNOTATION, OCI_MANIFEST_MEDIA_TYPE,
    PACKAGE_CONFIG_MEDIA_TYPE,
};
use std::collections::BTreeMap;

pub(crate) fn reference() -> OciReference {
    OciReference {
        registry: "registry.example".into(),
        repository: "tenant/site".into(),
        reference: "candidate".into(),
    }
}

fn descriptor(path: &str, role: &str, media_type: &str, bytes: &[u8]) -> LayerDescriptor {
    LayerDescriptor {
        media_type: media_type.into(),
        digest: artifact_blob_digest(bytes),
        size: bytes.len() as u64,
        annotations: Some(BTreeMap::from([
            (LAYER_PATH_ANNOTATION.into(), path.into()),
            (LAYER_ROLE_ANNOTATION.into(), role.into()),
        ])),
    }
}

pub(crate) type UploadFixture = (OciManifestBytes, Vec<u8>, Vec<(LayerDescriptor, Vec<u8>)>);

pub(crate) fn fixture(kind: PackageKind) -> UploadFixture {
    let content: Vec<(LayerRole, &str, &str, &[u8])> = match kind {
        PackageKind::BrowserAssets => {
            vec![(LayerRole::Asset, "index.html", "text/html", b"hello")]
        }
        PackageKind::SsrPackage => vec![(
            LayerRole::Renderer,
            "render.js",
            "text/javascript",
            b"renderer",
        )],
        // These opaque bytes intentionally establish association only, not
        // capsule semantic validity or permission to execute a component.
        PackageKind::Capsule => vec![
            (
                LayerRole::Component,
                "a-component.wasm",
                "application/wasm",
                b"component",
            ),
            (
                LayerRole::CapsuleManifest,
                "b-capsule.json",
                "application/vnd.latent.capsule.manifest.v1+json",
                b"{}",
            ),
            (
                LayerRole::Contracts,
                "c-contracts.json",
                "application/vnd.latent.contracts.v1+json",
                b"{}",
            ),
            (
                LayerRole::WitLock,
                "d-lock.json",
                "application/vnd.latent.wit-lock.v1+json",
                b"{}",
            ),
        ],
    };
    let limits = PackageLimits::default();
    let layers: Vec<_> = content
        .iter()
        .map(|(role, path, media_type, bytes)| PackageLayer {
            path: (*path).into(),
            role: *role,
            media_type: (*media_type).into(),
            digest: artifact_blob_digest(bytes),
            size: bytes.len() as u64,
        })
        .collect();
    let config = PackageConfig {
        format_version: 1,
        kind,
        name: "fixture".into(),
        version: "1.0.0".into(),
        entrypoint: layers[0].path.clone(),
        component_digest: (kind == PackageKind::Capsule).then(|| layers[0].digest.clone()),
        layers,
        annotations: BTreeMap::new(),
    };
    let config_bytes = encode_config(&config, limits).unwrap();
    let uploads: Vec<_> = content
        .iter()
        .map(|(role, path, media_type, bytes)| {
            (
                descriptor(path, role.as_str(), media_type, bytes),
                bytes.to_vec(),
            )
        })
        .collect();
    let manifest = PackageManifest {
        schema_version: 2,
        media_type: OCI_MANIFEST_MEDIA_TYPE.into(),
        artifact_type: kind.artifact_type().into(),
        config: LayerDescriptor {
            media_type: PACKAGE_CONFIG_MEDIA_TYPE.into(),
            digest: artifact_blob_digest(&config_bytes),
            size: config_bytes.len() as u64,
            annotations: None,
        },
        layers: uploads
            .iter()
            .map(|(descriptor, _)| descriptor.clone())
            .collect(),
        annotations: BTreeMap::new(),
    };
    (
        OciManifestBytes::new(
            encode_manifest(&manifest, limits).unwrap(),
            limits.max_document_bytes,
        )
        .unwrap(),
        config_bytes,
        uploads,
    )
}

pub(crate) fn evidence_fixture(kind: EvidenceKind) -> UploadFixture {
    let limits = PackageLimits::default();
    let payload = b"unverified evidence".to_vec();
    let layer = descriptor(
        "evidence.json",
        "evidence",
        kind.payload_media_type(),
        &payload,
    );
    let manifest = ReferrerManifest {
        schema_version: 2,
        media_type: OCI_MANIFEST_MEDIA_TYPE.into(),
        artifact_type: kind.artifact_type().into(),
        config: LayerDescriptor {
            media_type: EMPTY_CONFIG_MEDIA_TYPE.into(),
            digest: artifact_blob_digest(b"{}"),
            size: 2,
            annotations: None,
        },
        layers: vec![layer.clone()],
        subject: PackageSubject {
            media_type: OCI_MANIFEST_MEDIA_TYPE.into(),
            digest: package_digest(b"subject"),
            size: 7,
        },
        annotations: BTreeMap::new(),
    };
    (
        OciManifestBytes::new(
            encode_referrer(&manifest, limits).unwrap(),
            limits.max_document_bytes,
        )
        .unwrap(),
        b"{}".to_vec(),
        vec![(layer, payload)],
    )
}
