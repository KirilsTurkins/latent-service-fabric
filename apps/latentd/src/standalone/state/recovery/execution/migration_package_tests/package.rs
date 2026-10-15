use latent_packaging::{LayerInput, PackageInput, PackageSource};
use latent_signing::BuildObservation;
use sha2::{Digest, Sha256};

macro_rules! captured {
    ($path:literal) => {
        include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/tests/fixtures/current-java-writer/",
            $path
        ))
    };
}

pub(super) fn input(annotation: &str) -> (PackageInput, BuildObservation) {
    let source: PackageSource = serde_json::from_slice(captured!("package-source.json")).unwrap();
    assert_eq!(source.layers.len(), 19);
    let inputs: serde_json::Value = serde_json::from_slice(captured!("inputs.json")).unwrap();
    for file in inputs["files"].as_array().unwrap() {
        let bytes = bytes(file["path"].as_str().unwrap());
        assert_eq!(bytes.len() as u64, file["bytes"].as_u64().unwrap());
        assert_eq!(
            format!(
                "{:x}",
                latent_core::digest::HexDigest(Sha256::digest(bytes))
            ),
            file["sha256"].as_str().unwrap()
        );
    }
    let layers = source
        .layers
        .into_iter()
        .map(|file| {
            assert_eq!(file.path, file.source);
            LayerInput {
                bytes: bytes(&file.path).to_vec(),
                path: file.path,
                role: file.role,
                media_type: file.media_type,
            }
        })
        .collect();
    let mut annotations = source.annotations;
    annotations.insert("tests.current-migration-package".into(), annotation.into());
    let model: serde_json::Value =
        serde_json::from_slice(captured!("fixture-provenance-input.json")).unwrap();
    let observed: BuildObservation =
        serde_json::from_value(model["provenanceModel"].clone()).unwrap();
    assert_eq!(
        observed.component_digest,
        format!(
            "sha256:{:x}",
            latent_core::digest::HexDigest(Sha256::digest(bytes("component.wasm")))
        )
    );
    (
        PackageInput {
            kind: source.kind,
            name: source.name,
            version: source.version,
            entrypoint: source.entrypoint,
            annotations,
            layers,
        },
        observed,
    )
}

fn bytes(path: &str) -> &'static [u8] {
    use super::super::super::profile;
    match path {
        "component.wasm" => captured!("component.wasm"),
        "capsule.json" => captured!("capsule.json"),
        "contracts.json" => captured!("contracts.json"),
        "wit-lock.json" => captured!("wit-lock.json"),
        "package-source.json" => captured!("package-source.json"),
        "fixture-provenance-input.json" => captured!("fixture-provenance-input.json"),
        "wit/world.wit" => captured!("wit/world.wit"),
        "wit/deps/clock/package.wit" => captured!("wit/deps/clock/package.wit"),
        "wit/deps/intents/package.wit" => captured!("wit/deps/intents/package.wit"),
        "wit/deps/state/package.wit" => captured!("wit/deps/state/package.wit"),
        "transaction-binding.json" => captured!("transaction-binding.json"),
        "transaction-profile.json" => captured!("transaction-profile.json"),
        "application-schema-inputs.json" => captured!("application-schema-inputs.json"),
        "src/dev/latent/app/Capsule.java" => captured!("src/dev/latent/app/Capsule.java"),
        "src/dev/latent/app/AggregateCodec.java" => {
            captured!("src/dev/latent/app/AggregateCodec.java")
        }
        "java-current-http-profile.json" => captured!("java-current-http-profile.json"),
        "deferred-http-requirements.json" => captured!("deferred-http-requirements.json"),
        "schemas/application-aggregate-v1.schema.json" => profile::V1,
        "schemas/application-aggregate-v2.schema.json" | "state-schema.json" => profile::V2,
        "java-aggregate-v1-to-v2-migration.json" => profile::RECIPE,
        _ => panic!("unlisted captured public fixture input"),
    }
}
