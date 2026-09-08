mod capabilities;
mod generic;

use super::{platform, Result};
use latent_artifacts::{
    content_digest, decode_contract_metadata, encode_contract_metadata, ArtifactDescriptor,
    CapsuleArtifact, ContractMetadataLimits,
};
use latent_core::{ArtifactReference, Metadata};
use latent_manifest::{DeploymentManifest, JsonManifestCodec, ManifestCodec};
use latent_wire::invocation::proto;
use serde_json::{json, Value};
use std::{
    io::Read,
    path::{Path, PathBuf},
};

pub const MEDIA: &str = "application/vnd.latent.wit-values.v1+json";
const IMPORTS: [&str; 4] = [
    "latent:context/context@0.1.0",
    "latent:log/log@0.1.0",
    "latent:clock/monotonic@0.1.0",
    "latent:clock/wall@0.1.0",
];

pub struct Fixture {
    pub artifact: CapsuleArtifact,
    pub deployment: DeploymentManifest,
    pub tenant: String,
    pub service: String,
    pub contract: String,
    pub release_digest: String,
    pub target: proto::InvocationTarget,
}

pub struct Fixtures {
    pub echo: Fixture,
    pub generic: Fixture,
    pub capabilities: Fixture,
}

impl Fixtures {
    pub fn load() -> Result<Self> {
        Ok(Self {
            echo: Fixture::echo()?,
            generic: Fixture::generic()?,
            capabilities: Fixture::capabilities()?,
        })
    }
}

impl Fixture {
    pub fn echo() -> Result<Self> {
        let path = required("LSF_ECHO_COMPONENT")?;
        let directory = path.parent().ok_or("missing fixture directory")?;
        let manifest =
            serde_json::from_slice(&read(&directory.join("capsule.json"), 1024 * 1024)?)?;
        build(
            "examples",
            "measurement-echo",
            "examples:echo/api@0.1.0",
            read(&path, 16 * 1024 * 1024)?,
            manifest,
            &read(&directory.join("contracts.json"), 1024 * 1024)?,
        )
    }

    fn generic() -> Result<Self> {
        let mut manifest = template()?;
        manifest["component"]["world"] = json!("tests:generic/service@0.1.0");
        manifest["exports"] = json!([
            "tests:generic/values@0.1.0",
            "tests:generic/alternate@0.1.0"
        ]);
        manifest["imports"] = json!([]);
        build(
            "tests",
            "measurement-generic",
            "tests:generic/values@0.1.0",
            read(&required("LSF_GENERIC_COMPONENT")?, 16 * 1024 * 1024)?,
            manifest,
            &generic::contracts(),
        )
    }

    fn capabilities() -> Result<Self> {
        let mut manifest = template()?;
        manifest["component"]["world"] = json!("tests:capabilities/service@0.1.0");
        manifest["exports"] = json!(["tests:capabilities/api@0.1.0"]);
        manifest["imports"] = json!(IMPORTS
            .iter()
            .map(|name| json!({"contract":name,"optional":false}))
            .collect::<Vec<_>>());
        build(
            "tests",
            "measurement-capabilities",
            "tests:capabilities/api@0.1.0",
            read(&required("LSF_CAPABILITIES_COMPONENT")?, 16 * 1024 * 1024)?,
            manifest,
            &capabilities::capabilities(),
        )
    }

    pub fn request(&self, function: &str, id: &str, payload: &Value) -> proto::InvokeRequest {
        let mut target = self.target.clone();
        function.clone_into(&mut target.function);
        proto::InvokeRequest {
            activation_id: Some(id.to_owned()),
            target: Some(target),
            media_type: MEDIA.to_owned(),
            payload: serde_json::to_vec(payload).expect("fixed small measurement payload"),
            budget: Some(proto::ResourceBudget {
                cpu_fuel: 100_000_000,
                memory_bytes: 67_108_864,
                wall_time_limit_millis: Some(1000),
                log_bytes: 16384,
                ..proto::ResourceBudget::default()
            }),
            ..proto::InvokeRequest::default()
        }
    }
}

fn build(
    tenant: &str,
    service: &str,
    contract: &str,
    bytes: Vec<u8>,
    mut manifest: Value,
    contracts: &[u8],
) -> Result<Fixture> {
    let digest = content_digest(&bytes);
    manifest["metadata"]["tenant"] = json!(tenant);
    manifest["metadata"]["name"] = json!(service);
    manifest["component"]["digest"] = json!(digest.0);
    manifest["execution"]["limits"]["cpuFuel"] = json!(10_000_000_000_u64);
    manifest["execution"]["limits"]["memoryBytes"] = json!(67_108_864);
    manifest["execution"]["threading"] = json!("single-threaded");
    manifest["execution"]["snapshotEligible"] = json!(false);
    manifest["execution"]["fusionEligible"] = json!(false);
    let mut deployment: Value = serde_json::from_slice(include_bytes!(
        "../../../../../examples/echo-contract/deployment.json"
    ))?;
    deployment["metadata"]["name"] = json!(service);
    deployment["metadata"]["tenant"] = json!(tenant);
    deployment["spec"]["service"] = json!(service);
    deployment["spec"]["release"] = json!(digest.0);
    deployment["spec"]["resources"] = manifest["execution"]["limits"].clone();
    deployment["spec"]["grants"] = json!(manifest["imports"]
        .as_array()
        .ok_or("fixture imports")?
        .iter()
        .map(|v| json!({"capability":v["contract"],"policy":"measurement/activation-scoped"}))
        .collect::<Vec<_>>());
    let codec = JsonManifestCodec::default();
    let artifact = CapsuleArtifact {
        descriptor: ArtifactDescriptor {
            reference: ArtifactReference(format!("local://measurement/{service}")),
            release_digest: digest.clone(),
            media_type: "application/vnd.wasm.component.v1+wasm".to_owned(),
            size_bytes: u64::try_from(bytes.len())?,
            publisher: None,
            layers: Vec::new(),
            annotations: Metadata::new(),
        },
        manifest: codec
            .decode_capsule(&serde_json::to_vec(&manifest)?)
            .map_err(|_| "invalid measurement capsule manifest")?,
        contracts: decode_contract_metadata(contracts, ContractMetadataLimits::default())
            .map_err(platform)?,
        component_bytes: bytes,
    };
    Ok(Fixture {
        artifact,
        deployment: codec
            .decode_deployment(&serde_json::to_vec(&deployment)?)
            .map_err(|_| "invalid measurement deployment manifest")?,
        tenant: tenant.to_owned(),
        service: service.to_owned(),
        contract: contract.to_owned(),
        release_digest: digest.0,
        target: proto::InvocationTarget {
            tenant: tenant.to_owned(),
            service: service.to_owned(),
            contract: contract.to_owned(),
            function: String::new(),
            route: None,
        },
    })
}

fn template() -> Result<Value> {
    Ok(serde_json::from_slice(include_bytes!(
        "../../../../../examples/echo-contract/capsule.json"
    ))?)
}
fn required(name: &str) -> Result<PathBuf> {
    let path = PathBuf::from(std::env::var_os(name).ok_or("missing required fixture")?);
    if !path.is_absolute() {
        return Err("fixture path must be absolute".into());
    }
    Ok(path)
}
fn read(path: &Path, maximum: usize) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    std::fs::File::open(path)?
        .take(u64::try_from(maximum + 1)?)
        .read_to_end(&mut bytes)?;
    if bytes.is_empty() || bytes.len() > maximum {
        return Err("fixture byte bound".into());
    }
    Ok(bytes)
}

fn normalize_contracts(mut value: Value) -> Vec<u8> {
    for contract in value["contracts"].as_array_mut().expect("contract table") {
        for interface in contract["interfaces"]
            .as_array_mut()
            .expect("interface table")
        {
            assign_digest(interface);
        }
        assign_digest(contract);
    }
    let limits = ContractMetadataLimits::default();
    let decoded = decode_contract_metadata(
        &serde_json::to_vec(&value).expect("descriptor JSON"),
        limits,
    )
    .expect("typed descriptor table");
    encode_contract_metadata(&decoded, limits).expect("canonical descriptor table")
}
fn assign_digest(value: &mut Value) {
    let mut identity = value.clone();
    identity
        .as_object_mut()
        .expect("descriptor")
        .remove("digest");
    value["digest"] =
        json!(content_digest(&serde_json::to_vec(&identity).expect("descriptor identity")).0);
}
