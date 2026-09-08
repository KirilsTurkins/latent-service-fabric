#[path = "package/generic.rs"]
mod generic;

use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};

use latent_artifacts::{
    content_digest, decode_contract_metadata, encode_contract_metadata, ContractMetadataLimits,
};
use serde_json::{json, Value};

use super::Harness;

pub const MEDIA: &str = "application/vnd.latent.wit-values.v1+json";

pub struct Package {
    pub directory: tempfile::TempDir,
    pub manifest: PathBuf,
    pub component: PathBuf,
    pub contracts: PathBuf,
    pub digest: String,
    pub service: &'static str,
    pub contract: &'static str,
    pub tenant: &'static str,
}

impl Package {
    pub fn echo() -> Self {
        let component_path = PathBuf::from(
            std::env::var_os("LSF_ECHO_COMPONENT")
                .expect("contract gate must supply the built echo package"),
        );
        let directory = component_path.parent().expect("echo package directory");
        let component = bounded_file(&component_path, 16 * 1024 * 1024);
        let manifest: Value =
            serde_json::from_slice(&bounded_file(&directory.join("capsule.json"), 1024 * 1024))
                .expect("generated echo manifest");
        assert_eq!(
            manifest["component"]["digest"],
            content_digest(&component).0
        );
        let contracts = bounded_file(&directory.join("contracts.json"), 1024 * 1024);
        decode_contract_metadata(&contracts, ContractMetadataLimits::default())
            .expect("generated typed echo metadata");
        Self::create(
            component,
            manifest,
            contracts,
            "examples/echo",
            "examples:echo/api@0.1.0",
            "examples",
        )
    }

    pub fn generic() -> Self {
        generic::package(fixture("LSF_GENERIC_COMPONENT"))
    }

    pub fn dormant_adversarial() -> Self {
        let directory = PathBuf::from(
            std::env::var_os("LSF_GENERIC_FIXTURES")
                .expect("contract gate must supply generated adversarial fixtures"),
        );
        let bytes = bounded_file(&directory.join("bad-post-return.wasm"), 64 * 1024);
        generic::adversarial(bytes)
    }

    fn create(
        component: Vec<u8>,
        mut manifest: Value,
        contracts: Vec<u8>,
        service: &'static str,
        contract: &'static str,
        tenant: &'static str,
    ) -> Self {
        let directory = tempfile::tempdir().expect("client-only publication package");
        let digest = content_digest(&component).0;
        manifest["component"]["digest"] = json!(digest);
        let component_path = directory.path().join("component.wasm");
        let manifest_path = directory.path().join("capsule.json");
        let contracts_path = directory.path().join("contracts.json");
        fs::write(&component_path, component).expect("component input");
        write_json(&manifest_path, &manifest);
        fs::write(&contracts_path, contracts).expect("typed contract input");
        Self {
            directory,
            manifest: manifest_path,
            component: component_path,
            contracts: contracts_path,
            digest,
            service,
            contract,
            tenant,
        }
    }

    pub fn publish(&self, harness: &Harness, profile: &str) -> Value {
        harness.call(
            profile,
            &[
                "release",
                "publish",
                "--manifest",
                path(&self.manifest),
                "--component",
                path(&self.component),
                "--contracts",
                path(&self.contracts),
            ],
            0,
            "success",
        )
    }

    pub fn deployment(&self, id: &str) -> PathBuf {
        let mut manifest: Value = serde_json::from_slice(include_bytes!(
            "../../../../../examples/echo-contract/deployment.json"
        ))
        .expect("deployment template");
        manifest["metadata"]["name"] = json!(id);
        manifest["metadata"]["tenant"] = json!(self.tenant);
        manifest["spec"]["service"] = json!(self.service);
        manifest["spec"]["release"] = json!(self.digest);
        if self.tenant == "tests" {
            manifest["spec"]["grants"] = json!([]);
            manifest["spec"]["resources"]["cpuFuel"] = json!(10_000_000_000_u64);
            manifest["spec"]["resources"]["memoryBytes"] = json!(67_108_864);
        }
        let path = self.directory.path().join(format!("{id}.json"));
        write_json(&path, &manifest);
        path
    }

    pub fn payload(&self, name: &str, value: &Value) -> PathBuf {
        let path = self.directory.path().join(name);
        write_json(&path, value);
        path
    }
}

pub fn path(path: &Path) -> &str {
    path.to_str().expect("UTF-8 test path")
}

fn fixture(name: &str) -> Vec<u8> {
    let path =
        std::env::var_os(name).expect("contract gate must supply the prebuilt component fixture");
    bounded_file(Path::new(&path), 16 * 1024 * 1024)
}

fn bounded_file(path: &Path, maximum: usize) -> Vec<u8> {
    let mut bytes = Vec::new();
    fs::File::open(path)
        .expect("generated fixture")
        .take(u64::try_from(maximum + 1).expect("fixture bound"))
        .read_to_end(&mut bytes)
        .expect("bounded component fixture");
    assert!(!bytes.is_empty() && bytes.len() <= maximum);
    bytes
}

fn write_json(path: &Path, value: &Value) {
    fs::write(path, serde_json::to_vec(value).expect("test JSON")).expect("client input");
}

fn normalize_contracts(mut value: Value) -> Vec<u8> {
    for contract in value["contracts"].as_array_mut().expect("contracts") {
        for interface in contract["interfaces"].as_array_mut().expect("interfaces") {
            assign_digest(interface);
        }
        assign_digest(contract);
    }
    let limits = ContractMetadataLimits::default();
    let contracts = decode_contract_metadata(
        &serde_json::to_vec(&value).expect("typed metadata JSON"),
        limits,
    )
    .expect("complete typed metadata");
    encode_contract_metadata(&contracts, limits).expect("canonical contract metadata")
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
