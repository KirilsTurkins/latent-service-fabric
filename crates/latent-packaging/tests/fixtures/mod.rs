#![allow(dead_code)]
pub mod component;

use latent_artifacts::package::{
    artifact_blob_digest, encode_wit_lock, LayerRole, PackageKind, PackageLimits, WitLock,
    WitLockedPackage,
};
use latent_packaging::{BundleInput, LayerInput, PackageBundle, PackageInput};
use serde_json::{json, Value};

pub fn capsule(options: component::Options) -> PackageInput {
    let bytes = component::component(options);
    let contracts = contracts();
    let manifest = capsule_manifest(&bytes);
    let lock = WitLock {
        format_version: 1,
        world: "tests:packaging/service@1.0.0".into(),
        contracts_digest: artifact_blob_digest(&contracts),
        packages: vec![
            WitLockedPackage {
                id: "latent:clock@0.1.0".into(),
                source_path: "wit/clock.wit".into(),
                digest: artifact_blob_digest(component::CLOCK_WIT),
                dependencies: vec![],
            },
            WitLockedPackage {
                id: "tests:packaging@1.0.0".into(),
                source_path: "wit/service.wit".into(),
                digest: artifact_blob_digest(component::SERVICE_WIT),
                dependencies: vec!["latent:clock@0.1.0".into()],
            },
        ],
    };
    PackageInput {
        kind: PackageKind::Capsule,
        name: "packaging-fixture".into(),
        version: "1.0.0".into(),
        entrypoint: "component.wasm".into(),
        annotations: std::collections::BTreeMap::default(),
        layers: vec![
            layer(
                "component.wasm",
                LayerRole::Component,
                "application/wasm",
                bytes,
            ),
            layer(
                "capsule.json",
                LayerRole::CapsuleManifest,
                "application/vnd.latent.capsule.manifest.v1+json",
                manifest,
            ),
            layer(
                "contracts.json",
                LayerRole::Contracts,
                "application/vnd.latent.contracts.v1+json",
                contracts,
            ),
            layer(
                "wit-lock.json",
                LayerRole::WitLock,
                "application/vnd.latent.wit-lock.v1+json",
                encode_wit_lock(&lock, PackageLimits::default()).unwrap(),
            ),
            layer(
                "wit/clock.wit",
                LayerRole::Asset,
                "text/plain",
                component::CLOCK_WIT.to_vec(),
            ),
            layer(
                "wit/service.wit",
                LayerRole::Asset,
                "text/plain",
                component::SERVICE_WIT.to_vec(),
            ),
        ],
    }
}

pub fn layer(path: &str, role: LayerRole, media_type: &str, bytes: Vec<u8>) -> LayerInput {
    LayerInput {
        path: path.into(),
        role,
        media_type: media_type.into(),
        bytes,
    }
}

pub fn pruned_context_capsule(wrong_signature: bool) -> PackageInput {
    let mut input = capsule(component::Options {
        pruned_context: true,
        wrong_clock_signature: wrong_signature,
        ..component::Options::default()
    });
    let source = String::from_utf8(component::SERVICE_WIT.to_vec())
        .unwrap()
        .replace(component::CLOCK, component::CONTEXT)
        .into_bytes();
    for layer in &mut input.layers {
        if layer.path == "wit/clock.wit" {
            layer.path = "wit/context.wit".into();
            layer.bytes = component::CONTEXT_WIT.to_vec();
        } else if layer.path == "wit/service.wit" {
            layer.bytes.clone_from(&source);
        }
    }
    mutate_json(&mut input, "capsule.json", |manifest| {
        manifest["imports"][0]["contract"] = json!(component::CONTEXT);
    });
    mutate_json(&mut input, "wit-lock.json", |lock| {
        lock["packages"][0] = json!({
            "id": "latent:context@0.1.0",
            "sourcePath": "wit/context.wit",
            "digest": artifact_blob_digest(component::CONTEXT_WIT).as_str(),
            "dependencies": [],
        });
        lock["packages"][1]["digest"] = json!(artifact_blob_digest(&source).as_str());
        lock["packages"][1]["dependencies"] = json!(["latent:context@0.1.0"]);
    });
    input
}

pub fn capsule_manifest(component: &[u8]) -> Vec<u8> {
    let mut manifest: Value = serde_json::from_slice(include_bytes!(
        "../../../../examples/echo-contract/capsule.json"
    ))
    .unwrap();
    manifest["metadata"]["name"] = json!("tests/packaging");
    manifest["metadata"]["tenant"] = json!("tests");
    manifest["component"] = json!({"digest": artifact_blob_digest(component).as_str(), "version": "1.0.0", "world": "tests:packaging/service@1.0.0"});
    manifest["exports"] = json!([component::CONTRACT]);
    manifest["imports"] = json!([{"contract": component::CLOCK, "optional": false}]);
    serde_json::to_vec(&manifest).unwrap()
}

pub fn contracts() -> Vec<u8> {
    let function = json!({
        "id": "inspect", "name": "inspect", "asynchronous": false,
        "parameters": [{"name": "input", "value_type": {"Record": "input"}, "documentation": null}],
        "results": [{"name": "result", "value_type": "U32", "documentation": null}],
        "documentation": null, "attributes": {}
    });
    let mut interface =
        json!({"id": component::CONTRACT, "functions": [function], "documentation": null});
    interface["digest"] =
        json!(artifact_blob_digest(&serde_json::to_vec(&interface).unwrap()).as_str());
    let mut contract = json!({"id": component::CONTRACT, "package_name": "tests:packaging", "semantic_version": "1.0.0", "interfaces": [interface], "dependencies": []});
    contract["digest"] =
        json!(artifact_blob_digest(&serde_json::to_vec(&contract).unwrap()).as_str());
    serde_json::to_vec(&json!({"format_version": 1, "contracts": [contract]})).unwrap()
}

pub fn raw(bundle: &PackageBundle) -> BundleInput {
    BundleInput {
        manifest: bundle.manifest_bytes().to_vec(),
        configuration: bundle.config_bytes().to_vec(),
        layers: bundle
            .layers()
            .iter()
            .map(|blob| (blob.path().to_owned(), blob.bytes().to_vec()))
            .collect(),
    }
}

pub fn mutate_json(input: &mut PackageInput, path: &str, change: impl FnOnce(&mut Value)) {
    let layer = input
        .layers
        .iter_mut()
        .find(|layer| layer.path == path)
        .unwrap();
    let mut value = serde_json::from_slice(&layer.bytes).unwrap();
    change(&mut value);
    layer.bytes = serde_json::to_vec(&value).unwrap();
}
