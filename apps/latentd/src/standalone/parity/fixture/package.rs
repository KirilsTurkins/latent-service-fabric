use std::path::PathBuf;

use latent_artifacts::content_digest;
use latent_control_store::VersionedDeployment;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_testkit::conformance::ArtifactReference;
use latent_wire::management::{deployment_to_proto, proto};
use serde_json::{json, Value};

use super::{contracts, read, SHARED};

pub struct Package {
    pub upload: proto::PublishReleaseRequest,
    pub deployment: proto::Deployment,
    pub digest: String,
    pub inputs: Vec<Value>,
    pub published: Value,
    pub artifacts: Vec<ArtifactReference>,
}

pub fn echo() -> Package {
    let component = PathBuf::from(std::env::var_os("LSF_ECHO_COMPONENT").expect("echo fixture"));
    let directory = component.parent().unwrap();
    let bytes = read(&component, 16 * 1024 * 1024);
    let mut manifest: Value =
        serde_json::from_slice(&read(&directory.join("capsule.json"), 64 * 1024)).unwrap();
    assert_eq!(manifest["component"]["digest"], content_digest(&bytes).0);
    manifest["metadata"]["name"] = json!(SHARED);
    let deployment: Value =
        serde_json::from_slice(&read(&directory.join("deployment.json"), 64 * 1024)).unwrap();
    let inputs = [
        "echo-capsule.wasm",
        "capsule.json",
        "contracts.json",
        "deployment.json",
    ]
    .into_iter()
    .map(|name| {
        let input = read(&directory.join(name), 16 * 1024 * 1024);
        json!({"name":name,"sha256":content_digest(&input).0,"bytes":input.len().to_string()})
    })
    .collect();
    create(
        "echo",
        bytes,
        manifest,
        read(&directory.join("contracts.json"), 64 * 1024),
        deployment,
        inputs,
    )
}

pub fn capabilities() -> Package {
    let component = PathBuf::from(
        std::env::var_os("LSF_CAPABILITIES_COMPONENT").expect("capabilities fixture"),
    );
    let bytes = read(&component, 16 * 1024 * 1024);
    let mut manifest: Value = serde_json::from_slice(include_bytes!(
        "../../../../../../examples/echo-contract/capsule.json"
    ))
    .unwrap();
    manifest["metadata"]["tenant"] = json!("tests");
    manifest["metadata"]["name"] = json!(SHARED);
    manifest["component"]["world"] = json!("tests:capabilities/service@0.1.0");
    manifest["exports"] = json!(["tests:capabilities/api@0.1.0"]);
    manifest["imports"] = json!(super::IMPORTS
        .iter()
        .map(|name| json!({"contract":name,"optional":false}))
        .collect::<Vec<_>>());
    manifest["execution"]["threading"] = json!("single-threaded");
    manifest["execution"]["snapshotEligible"] = json!(false);
    manifest["execution"]["fusionEligible"] = json!(false);
    manifest["execution"]["limits"]["cpuFuel"] = json!(100_000_000);
    manifest["execution"]["limits"]["memoryBytes"] = json!(67_108_864);
    let mut deployment: Value = serde_json::from_slice(include_bytes!(
        "../../../../../../examples/echo-contract/deployment.json"
    ))
    .unwrap();
    deployment["metadata"]["name"] = json!("capabilities-parity");
    deployment["metadata"]["tenant"] = json!("tests");
    deployment["spec"]["resources"] = manifest["execution"]["limits"].clone();
    deployment["spec"]["grants"] = json!(super::IMPORTS
        .iter()
        .map(|name| json!({"capability":name,"policy":"parity/activation-scoped"}))
        .collect::<Vec<_>>());
    create(
        "capabilities",
        bytes,
        manifest,
        contracts::capabilities(),
        deployment,
        Vec::new(),
    )
}

fn create(
    name: &str,
    bytes: Vec<u8>,
    mut manifest: Value,
    contracts: Vec<u8>,
    mut deployment: Value,
    inputs: Vec<Value>,
) -> Package {
    let digest = content_digest(&bytes).0;
    manifest["component"]["digest"] = json!(digest);
    deployment["spec"]["service"] = json!(SHARED);
    deployment["spec"]["release"] = json!(digest);
    let codec = JsonManifestCodec::default();
    let manifest = codec
        .encode_capsule(
            &codec
                .decode_capsule(&serde_json::to_vec(&manifest).unwrap())
                .unwrap(),
        )
        .unwrap();
    let deployment = codec
        .decode_deployment(&serde_json::to_vec(&deployment).unwrap())
        .unwrap();
    let deployment_bytes = codec.encode_deployment(&deployment).unwrap();
    let manifest_artifact = artifact(name, "manifest", &manifest);
    let contracts_artifact = artifact(name, "contracts", &contracts);
    let deployment_artifact = artifact(name, "deployment", &deployment_bytes);
    let published = json!({"tenant":deployment.metadata.tenant.as_ref().unwrap().0,"service":SHARED,"component_sha256":digest,
        "manifest":manifest_artifact,"contracts":contracts_artifact,"deployment":deployment_artifact});
    Package {
        upload: proto::PublishReleaseRequest {
            package: None,
            release: None,
            artifact: Some(proto::CapsuleArtifactUpload {
                capsule_manifest_json: manifest,
                component_bytes: bytes,
                component_digest: digest.clone(),
                component_media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
                contract_metadata_json: contracts,
            }),
        },
        deployment: deployment_to_proto(&VersionedDeployment {
            manifest: deployment,
            generation: 0,
        })
        .unwrap(),
        digest,
        inputs,
        published,
        artifacts: vec![manifest_artifact, contracts_artifact, deployment_artifact],
    }
}

fn artifact(name: &str, kind: &str, bytes: &[u8]) -> ArtifactReference {
    assert!(!bytes.is_empty() && bytes.len() <= 1024 * 1024);
    let relative = format!("adapter-inputs/{name}-{kind}.json");
    let report =
        PathBuf::from(std::env::var_os("LSF_PHASE1_PARITY_REPORT").expect("parity output"));
    let path = report.parent().unwrap().join(&relative);
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, bytes).unwrap();
    ArtifactReference {
        path: relative,
        sha256: content_digest(bytes).0,
        bytes: u64::try_from(bytes.len()).unwrap(),
    }
}
