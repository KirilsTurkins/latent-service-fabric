use std::path::Path;

use latent_artifacts::package::{
    decode_manifest, decode_referrer, package_digest, ArtifactDescriptor, PackageLimits,
};
use latent_oci::{OciManifestBytes, OciPushRequest, OciReference};
use serde_json::Value;

pub struct Fixture {
    pub kind: String,
    pub manifest: Vec<u8>,
    pub config: Vec<u8>,
    pub layers: Vec<(ArtifactDescriptor, Vec<u8>)>,
    pub evidence: bool,
}

impl Fixture {
    pub fn request(&self, reference: OciReference) -> OciPushRequest {
        let limits = PackageLimits::default();
        let manifest =
            OciManifestBytes::new(self.manifest.clone(), limits.max_document_bytes).unwrap();
        if self.evidence {
            OciPushRequest::new_referrer(
                reference,
                manifest,
                self.config.clone(),
                self.layers.clone(),
                limits,
            )
        } else {
            OciPushRequest::new(
                reference,
                manifest,
                self.config.clone(),
                self.layers.clone(),
                limits,
            )
        }
        .unwrap()
    }

    pub fn check(&self, actual: &OciPushRequest) {
        assert_eq!(actual.manifest().as_bytes(), self.manifest);
        assert_eq!(actual.manifest().digest(), &package_digest(&self.manifest));
        assert_eq!(actual.config_bytes(), self.config);
        assert_eq!(actual.layers().len(), self.layers.len());
        for ((descriptor, bytes), (expected_descriptor, expected_bytes)) in
            actual.layers().zip(&self.layers)
        {
            assert_eq!(descriptor, expected_descriptor);
            assert_eq!(bytes, expected_bytes);
        }
    }
}

fn bytes(record: &Value) -> Vec<u8> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../examples/package-format")
        .join(record["file"].as_str().unwrap());
    let content = std::fs::read(path).unwrap();
    assert!(content.len() < 16 * 1024, "golden fixture must remain tiny");
    assert_eq!(content.len() as u64, record["size"].as_u64().unwrap());
    assert_eq!(
        package_digest(&content).as_str(),
        record["digest"].as_str().unwrap()
    );
    content
}

pub fn load() -> (Vec<Fixture>, Vec<Fixture>) {
    let golden: Value = serde_json::from_str(include_str!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../examples/package-format/golden.json"
    )))
    .unwrap();
    let limits = PackageLimits::default();
    let packages = golden["packages"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| {
            let manifest = bytes(&value["manifest"]);
            let parsed = decode_manifest(&manifest, limits).unwrap();
            let layers = parsed
                .layers
                .into_iter()
                .zip(value["blobs"].as_array().unwrap().iter().map(bytes))
                .collect();
            Fixture {
                kind: value["kind"].as_str().unwrap().into(),
                manifest,
                config: bytes(&value["config"]),
                layers,
                evidence: false,
            }
        })
        .collect();
    let evidence = golden["evidence"]
        .as_array()
        .unwrap()
        .iter()
        .map(|value| {
            let manifest = bytes(&value["manifest"]);
            let parsed = decode_referrer(&manifest, limits).unwrap();
            Fixture {
                kind: value["kind"].as_str().unwrap().into(),
                manifest,
                config: b"{}".to_vec(),
                layers: vec![(parsed.layers[0].clone(), bytes(&value["payload"]))],
                evidence: true,
            }
        })
        .collect();
    (packages, evidence)
}
