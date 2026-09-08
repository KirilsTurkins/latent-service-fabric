use std::io::Read;
use std::path::Path;

use latent_control_store::VersionedDeployment;
use latent_manifest::{JsonManifestCodec, ManifestCodec};
use latent_wire::management::{deployment_to_proto, proto};

pub fn read(path: &Path, maximum: u64) -> Vec<u8> {
    let mut bytes = Vec::new();
    std::fs::File::open(path)
        .expect("required prebuilt fixture")
        .take(maximum + 1)
        .read_to_end(&mut bytes)
        .expect("bounded fixture read");
    assert!(!bytes.is_empty() && bytes.len() as u64 <= maximum);
    bytes
}

pub fn package() -> (
    proto::PublishReleaseRequest,
    proto::Deployment,
    serde_json::Value,
) {
    let component = std::path::PathBuf::from(
        std::env::var_os("LSF_ECHO_COMPONENT").expect("required echo component"),
    );
    let directory = component
        .parent()
        .expect("generated echo package directory");
    let bytes = read(&component, 16 * 1024 * 1024);
    let digest = latent_artifacts::content_digest(&bytes);
    let manifest = read(&directory.join("capsule.json"), 64 * 1024);
    let codec = JsonManifestCodec::default();
    assert_eq!(
        codec.decode_capsule(&manifest).unwrap().component_digest,
        digest
    );
    let mut deployment = codec
        .decode_deployment(&read(&directory.join("deployment.json"), 64 * 1024))
        .expect("generated deployment");
    deployment.release = digest.clone();
    let inputs = ["echo-capsule.wasm", "capsule.json", "contracts.json", "deployment.json"]
        .into_iter().map(|name| {
            let input = read(&directory.join(name), 16 * 1024 * 1024);
            serde_json::json!({"name":name,"sha256":latent_artifacts::content_digest(&input).0,"bytes":input.len().to_string()})
        }).collect::<Vec<_>>();
    (
        proto::PublishReleaseRequest {
            release: None,
            artifact: Some(proto::CapsuleArtifactUpload {
                capsule_manifest_json: manifest,
                component_bytes: bytes,
                component_digest: digest.0,
                component_media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
                contract_metadata_json: read(&directory.join("contracts.json"), 64 * 1024),
            }),
        },
        deployment_to_proto(&VersionedDeployment {
            manifest: deployment,
            generation: 0,
        })
        .expect("deployment wire conversion"),
        serde_json::json!(inputs),
    )
}

pub const TOKEN: &str = "parity-00000000000000000000000000000";

pub fn configuration(directory: &Path) -> (crate::config::NodeConfig, serde_json::Value) {
    let path = directory.join("node.json");
    let value = serde_json::json!({
        "formatVersion":1,"dataDirectory":directory.join("data"),
        "nodeId":"phase1-adapter-parity","bind":"127.0.0.1:0",
        "workers":{"runtime":1,"control":1},
        "cells":[{"class":"standard","capacity":2,"queueCapacity":2,
            "maximumMemoryBytes":64*1024*1024}],
        "execution":{"maximumCpuFuel":100_000_000,"maximumWallTimeMillis":5000,
            "maximumLogBytes":16384},
        "shutdownGraceMillis":500,
        "credentials":[{"token":TOKEN,"subject":"parity","tenant":"examples","role":"operator"}]
    });
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    let mut public = value;
    public.as_object_mut().unwrap().remove("credentials");
    public["dataDirectory"] = "data".into();
    (crate::config::NodeConfig::load(&path).unwrap(), public)
}

pub fn request<T>(message: T) -> tonic::Request<T> {
    let mut request = tonic::Request::new(message);
    request
        .metadata_mut()
        .insert("authorization", format!("Bearer {TOKEN}").parse().unwrap());
    request.set_timeout(std::time::Duration::from_secs(5));
    request
}
