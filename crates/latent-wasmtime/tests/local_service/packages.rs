use super::component;
use latent_artifacts::package::{
    artifact_blob_digest, encode_wit_lock, LayerRole, WitLock, WitLockedPackage,
};
use latent_packaging::{PackageBundle, PackageInput};
use serde_json::{json, Value};
#[path = "../../../latent-packaging/tests/fixtures/mod.rs"]
mod fixture;
#[path = "../generic_backend/support.rs"]
#[allow(dead_code)]
mod runtime_fixture;
#[path = "../../../latent-packaging/tests/sbom_association/support.rs"]
#[allow(dead_code)]
mod sbom;

pub const ACTIVATION: &str = "latent:runtime/activation@0.1.0";

pub fn budget() -> latent_core::ResourceBudget {
    latent_core::ResourceBudget {
        cpu_fuel: runtime_fixture::guest_runtime::fuel(100_000_000),
        memory_bytes: runtime_fixture::guest_runtime::service_memory(4 * 1024 * 1024),
        wall_time_limit_millis: Some(runtime_fixture::guest_runtime::service_wall_time(5000)),
        child_calls: 16,
        outbound_requests: 0,
        state_read_bytes: 0,
        state_write_bytes: 0,
        blob_read_bytes: 0,
        blob_write_bytes: 0,
        log_bytes: 0,
        effect_count: 0,
    }
}
pub fn budget_json() -> Value {
    let budget = budget();
    json!({"cpuFuel":budget.cpu_fuel,"memoryBytes":budget.memory_bytes,"wallTimeLimitMillis":budget.wall_time_limit_millis,"childCalls":16,
        "outboundRequests":0,"stateReadBytes":0,"stateWriteBytes":0,"blobReadBytes":0,"blobWriteBytes":0,"logBytes":0,"effectCount":0})
}
pub fn caller(tenant: Option<&str>) -> PackageBundle {
    build(
        "caller",
        component::caller(tenant),
        component::CALLER_WIT,
        component::CALLER,
        vec![function(
            "run",
            true,
            vec![json!({"name":"which","value_type":"U32","documentation":null})],
            json!("U32"),
        )],
        &[latent_capabilities::broker::SERVICE_INVOCATION_CAPABILITY],
    )
}
pub fn callee(answer: i32) -> PackageBundle {
    build(
        "local",
        component::callee(answer),
        component::CALLEE_WIT,
        component::CALLEE,
        vec![
            function("answer", false, vec![], json!("U32")),
            function(
                "fail",
                false,
                vec![],
                json!({"Result":{"ok":"U32","error":"String"}}),
            ),
            function("spin", false, vec![], json!("U32")),
        ],
        &[],
    )
}

pub fn activation_runtime(bytes: Vec<u8>) -> PackageBundle {
    build(
        "caller", bytes,
        "package tests:caller@1.0.0; interface api { run: async func(which: u32) -> u32; } world service { import latent:runtime/activation@0.1.0; export api; }",
        component::CALLER,
        vec![function("run", true,
            vec![json!({"name":"which","value_type":"U32","documentation":null})], json!("U32"))],
        &[ACTIVATION],
    )
}
pub fn outbound_streams(bytes: Vec<u8>) -> PackageBundle {
    build(
        "caller", bytes,
        "package tests:caller@1.0.0; interface api { run: async func(which: u32) -> u32; } world service { import latent:network/streams@0.1.0; export api; }",
        component::CALLER,
        vec![function("run", true,
            vec![json!({"name":"which","value_type":"U32","documentation":null})], json!("U32"))],
        &[latent_capabilities::broker::network::STREAM_CAPABILITY],
    )
}
pub fn java_activation_runtime(bytes: Vec<u8>, source: &str) -> PackageBundle {
    build(
        "caller",
        bytes,
        source,
        component::CALLER,
        vec![function(
            "run",
            true,
            vec![json!({"name":"which","value_type":"U32","documentation":null})],
            json!("U32"),
        )],
        &[
            ACTIVATION,
            "latent:clock/monotonic@0.1.0",
            "latent:clock/wall@0.1.0",
        ],
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
    imports: &[&str],
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
    manifest["metadata"]["name"] = json!(if name == "caller" { "caller" } else { "callee" });
    manifest["component"]["world"] = json!(world);
    manifest["exports"] = json!([contract]);
    manifest["imports"] = json!(imports
        .iter()
        .map(|contract| json!({"contract":contract,"optional":false}))
        .collect::<Vec<_>>());
    manifest["execution"]["limits"] = budget_json();
    if imports.contains(&latent_capabilities::broker::network::STREAM_CAPABILITY) {
        manifest["execution"]["limits"]["outboundRequests"] = json!(8);
    }
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
    let mut dependencies = vec![];
    for import in imports {
        let spec = latent_core::PHASE3_HOST_ABI_CURRENT
            .interface(import)
            .unwrap();
        let wit = spec.wit;
        let (package, version) = import.rsplit_once('@').unwrap();
        let package = package.split('/').next().unwrap();
        let id = format!("{package}@{version}");
        if dependencies.contains(&id) {
            continue;
        }
        let path = format!("wit/{}.wit", package.replace(':', "-"));
        locked.push(WitLockedPackage {
            id: id.clone(),
            source_path: path.clone(),
            digest: artifact_blob_digest(wit.as_bytes()),
            dependencies: vec![],
        });
        layers.push(fixture::layer(
            &path,
            LayerRole::Asset,
            "text/plain",
            wit.as_bytes().to_vec(),
        ));
        dependencies.push(id);
    }
    dependencies.sort();
    locked.push(WitLockedPackage {
        id: format!("{package}@1.0.0"),
        source_path: "wit/service.wit".into(),
        digest: artifact_blob_digest(source.as_bytes()),
        dependencies,
    });
    layers.push(fixture::layer(
        "wit/service.wit",
        LayerRole::Asset,
        "text/plain",
        source.as_bytes().to_vec(),
    ));
    locked.sort_by(|left, right| left.id.cmp(&right.id));
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
    let input = PackageInput {
        kind: latent_artifacts::package::PackageKind::Capsule,
        name: name.into(),
        version: "1.0.0".into(),
        entrypoint: "component.wasm".into(),
        annotations: std::collections::BTreeMap::default(),
        layers,
    };
    let inventory = sbom::inventory(&input);
    latent_packaging::build_package_with_sbom(input, inventory, Default::default()).unwrap()
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
pub fn release(bundle: &PackageBundle) -> latent_core::ReleaseDigest {
    latent_core::ReleaseDigest(bundle.surface().unwrap().component_digest().as_str().into())
}
