use std::fs::File;
use std::io::Read;

use latent_artifacts::{content_digest, decode_contract_metadata, ContractMetadataLimits};
use latent_control_store::VersionedDeployment;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_wire::management::{deployment_to_proto, proto};
use serde_json::{json, Value};

pub const API: &str = "tests:shutdown/api@0.1.0";
pub const SERVICE: &str = "tests/shutdown";
pub const FUEL: u64 = 1_000_000_000;
pub const MEMORY: u64 = 4 * 1024 * 1024;

pub fn upload() -> proto::PublishReleaseRequest {
    let path = std::env::var_os("LSF_SHUTDOWN_COMPONENT")
        .expect("contracts gate supplies the prebuilt tiny shutdown fixture");
    let mut bytes = Vec::new();
    File::open(path)
        .unwrap()
        .take(4097)
        .read_to_end(&mut bytes)
        .unwrap();
    assert!(!bytes.is_empty() && bytes.len() <= 4096);
    let digest = content_digest(&bytes).0;
    let manifest = json!({
        "apiVersion": "latent.dev/v1alpha1", "kind": "Capsule",
        "metadata": {"name": SERVICE, "tenant": "tests"},
        "component": {"digest": digest, "version": "0.1.0",
            "world": "tests:shutdown/service@0.1.0"},
        "exports": [API], "imports": [],
        "execution": {"backend": "wasm-component", "threading": "single-threaded",
            "stateModel": "stateless", "limits": resources(),
            "hostCallDepthMaximum": 1, "componentCallDepthMaximum": 1,
            "snapshotEligible": false, "fusionEligible": false},
        "compatibility": {"minimumFabricVersion": "0.1.0"}
    });
    let manifest = serde_json::to_vec(&manifest).unwrap();
    JsonManifestCodec::default()
        .decode_capsule(&manifest)
        .unwrap();
    proto::PublishReleaseRequest {
        package: None,
        release: None,
        artifact: Some(proto::CapsuleArtifactUpload {
            capsule_manifest_json: manifest,
            component_bytes: bytes,
            component_digest: digest,
            component_media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            contract_metadata_json: metadata(),
        }),
    }
}

pub fn deployment(digest: &str) -> proto::Deployment {
    let document = json!({
        "apiVersion": "latent.dev/v1alpha1", "kind": "Deployment",
        "metadata": {"name": "shutdown-test", "tenant": "tests"},
        "spec": {"service": SERVICE, "release": digest,
            "route": {"weight": 10000}, "grants": [], "resources": resources(),
            "availability": {"minimumCachedCopies": 1, "minimumZones": 1},
            "placement": {"trustClass": "internal", "architectures": [std::env::consts::ARCH]}}
    });
    let manifest = JsonManifestCodec::default()
        .decode_deployment(&serde_json::to_vec(&document).unwrap())
        .unwrap();
    deployment_to_proto(&VersionedDeployment {
        manifest,
        generation: 0,
    })
    .unwrap()
}

fn resources() -> Value {
    json!({"cpuFuel": FUEL, "memoryBytes": MEMORY, "wallTimeLimitMillis": 5000,
        "childCalls": 0, "outboundRequests": 0, "stateReadBytes": 0,
        "stateWriteBytes": 0, "blobReadBytes": 0, "blobWriteBytes": 0,
        "logBytes": 0, "effectCount": 0})
}

fn metadata() -> Vec<u8> {
    let mut interface = json!({"id": API, "functions": [{
        "id": "spin", "name": "spin", "asynchronous": false, "parameters": [],
        "results": [{"name": "result", "value_type": "U32", "documentation": null}],
        "documentation": null, "attributes": {}}], "documentation": null});
    assign_digest(&mut interface);
    let mut contract = json!({"id": API, "package_name": "tests:shutdown",
        "semantic_version": "0.1.0", "interfaces": [interface], "dependencies": []});
    assign_digest(&mut contract);
    let bytes = serde_json::to_vec(&json!({"format_version": 1, "contracts": [contract]})).unwrap();
    decode_contract_metadata(&bytes, ContractMetadataLimits::default()).unwrap();
    bytes
}

fn assign_digest(descriptor: &mut Value) {
    descriptor["digest"] = content_digest(&serde_json::to_vec(descriptor).unwrap())
        .0
        .into();
}
