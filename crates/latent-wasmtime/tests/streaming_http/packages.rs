use super::{component, support as runtime_fixture};
use latent_artifacts::package::{
    artifact_blob_digest, encode_wit_lock, LayerRole, WitLock, WitLockedPackage,
};
use latent_packaging::{PackageBundle, PackageInput};
use serde_json::{json, Value};
#[path = "../../../latent-packaging/tests/fixtures/mod.rs"]
mod fixture;

pub fn budget_json() -> Value {
    json!({"cpuFuel":100_000_000,"memoryBytes":4_194_304,"wallTimeLimitMillis":5000,"childCalls":0,
        "outboundRequests":8,"stateReadBytes":0,"stateWriteBytes":0,"blobReadBytes":0,"blobWriteBytes":0,"logBytes":0,"effectCount":0})
}
pub fn capsule(url: &str) -> PackageBundle {
    build(
        "streaming-http",
        component::bytes(url),
        include_str!("../../../../examples/streaming-http/wit/streaming-probe.wit"),
        component::CONTRACT,
        vec![function(
            "run",
            true,
            vec![json!({"name":"which","value_type":"U32","documentation":null})],
            json!("U32"),
        )],
        true,
    )
}
#[expect(
    clippy::needless_pass_by_value,
    reason = "JSON fixture builder accepts owned nested values"
)]
fn function(name: &str, asynchronous: bool, parameters: Vec<Value>, result: Value) -> Value {
    json!({"id":name,"name":name,"asynchronous":asynchronous,"parameters":parameters,
        "results":[{"name":"result","value_type":result,"documentation":null}],"documentation":null,"attributes":{}})
}
#[expect(
    clippy::too_many_lines,
    clippy::needless_pass_by_value,
    reason = "assemble one checked immutable package with exact metadata and WIT sources"
)]
fn build(
    name: &str,
    bytes: Vec<u8>,
    source: &str,
    contract: &str,
    functions: Vec<Value>,
    caller: bool,
) -> PackageBundle {
    let package = format!("tests:{name}");
    let world = format!("{package}/service@1.0.0");
    let mut interface = json!({"id":contract,"functions":functions,"documentation":null});
    interface["digest"] =
        json!(artifact_blob_digest(&serde_json::to_vec(&interface).unwrap()).as_str());
    let mut descriptor = json!({"id":contract,"package_name":package,"semantic_version":"1.0.0","interfaces":[interface],"dependencies":[]});
    descriptor["digest"] =
        json!(artifact_blob_digest(&serde_json::to_vec(&descriptor).unwrap()).as_str());
    let contracts =
        serde_json::to_vec(&json!({"format_version":1,"contracts":[descriptor]})).unwrap();
    let mut manifest: Value = serde_json::from_slice(&fixture::capsule_manifest(&bytes)).unwrap();
    manifest["metadata"]
        .as_object_mut()
        .unwrap()
        .remove("tenant");
    manifest["metadata"]["name"] = json!(if caller { "caller" } else { "callee" });
    manifest["component"]["world"] = json!(world);
    manifest["exports"] = json!([contract]);
    manifest["imports"] = if caller {
        json!([{"contract":component::CAP,"optional":false}])
    } else {
        json!([])
    };
    manifest["execution"]["limits"] = budget_json();
    manifest["execution"]["threading"] = json!("single-threaded");
    let mut locked = vec![];
    let mut layers = vec![
        fixture::layer(
            "component.wasm",
            LayerRole::Component,
            "application/wasm",
            bytes,
        ),
        fixture::layer(
            "capsule.json",
            LayerRole::CapsuleManifest,
            "application/vnd.latent.capsule.manifest.v1+json",
            serde_json::to_vec(&manifest).unwrap(),
        ),
        fixture::layer(
            "contracts.json",
            LayerRole::Contracts,
            "application/vnd.latent.contracts.v1+json",
            contracts.clone(),
        ),
    ];
    if caller {
        let wit = latent_core::PHASE3_HOST_ABI_V3
            .interface(component::CAP)
            .unwrap()
            .wit;
        locked.push(WitLockedPackage {
            id: "latent:http@0.3.0".into(),
            source_path: "wit/http.wit".into(),
            digest: artifact_blob_digest(wit.as_bytes()),
            dependencies: vec![],
        });
        layers.push(fixture::layer(
            "wit/http.wit",
            LayerRole::Asset,
            "text/plain",
            wit.as_bytes().to_vec(),
        ));
    }
    locked.push(WitLockedPackage {
        id: format!("{package}@1.0.0"),
        source_path: "wit/service.wit".into(),
        digest: artifact_blob_digest(source.as_bytes()),
        dependencies: if caller {
            vec!["latent:http@0.3.0".into()]
        } else {
            vec![]
        },
    });
    layers.push(fixture::layer(
        "wit/service.wit",
        LayerRole::Asset,
        "text/plain",
        source.as_bytes().to_vec(),
    ));
    let lock = WitLock {
        format_version: 1,
        world,
        contracts_digest: artifact_blob_digest(&contracts),
        packages: locked,
    };
    layers.push(fixture::layer(
        "wit-lock.json",
        LayerRole::WitLock,
        "application/vnd.latent.wit-lock.v1+json",
        encode_wit_lock(&lock, latent_artifacts::package::PackageLimits::default()).unwrap(),
    ));
    latent_packaging::build_package(
        PackageInput {
            kind: latent_artifacts::package::PackageKind::Capsule,
            name: name.into(),
            version: "1.0.0".into(),
            entrypoint: "component.wasm".into(),
            annotations: std::collections::BTreeMap::default(),
            layers,
        },
        latent_packaging::PackagingLimits::default(),
    )
    .unwrap()
}
pub fn artifact(bundle: &PackageBundle) -> latent_artifacts::CapsuleArtifact {
    use latent_manifest::{JsonManifestCodec, ManifestCodec};
    let mut artifact =
        runtime_fixture::artifact_bytes(bundle.blob("component.wasm").unwrap().to_vec(), &[]);
    artifact.manifest = JsonManifestCodec::default()
        .decode_capsule(bundle.blob("capsule.json").unwrap())
        .unwrap();
    artifact.contracts = latent_artifacts::decode_contract_metadata(
        bundle.blob("contracts.json").unwrap(),
        latent_artifacts::ContractMetadataLimits::default(),
    )
    .unwrap();
    artifact
}
