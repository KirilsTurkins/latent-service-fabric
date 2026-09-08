#[path = "fixtures/capabilities.rs"]
mod capabilities;
#[path = "fixtures/generic.rs"]
mod generic;

use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};

use latent_artifacts::{
    content_digest, decode_contract_metadata, encode_contract_metadata, ContractMetadataLimits,
};
use serde_json::{json, Value};

pub const MEDIA: &str = "application/vnd.latent.wit-values.v1+json";
pub const SHARED: &str = "shared";
pub const IMPORTS: [&str; 4] = [
    "latent:context/context@0.1.0",
    "latent:log/log@0.1.0",
    "latent:clock/monotonic@0.1.0",
    "latent:clock/wall@0.1.0",
];

pub struct Package {
    directory: tempfile::TempDir,
    pub manifest: PathBuf,
    pub component: PathBuf,
    pub contracts: PathBuf,
    pub digest: String,
    pub service: String,
    pub contract: String,
    pub tenant: String,
}

pub struct Fixtures {
    pub generic: Package,
    pub echo: Package,
    pub capabilities: Package,
    pub dormant: Package,
}

impl Fixtures {
    pub fn load() -> Self {
        let generic_bytes = fixture("LSF_GENERIC_COMPONENT");
        let generic = generic::package(variant(&generic_bytes, "generic"), SHARED);
        let dormant = generic::package(variant(&generic_bytes, "dormant"), "dormant");
        let echo = Package::echo();
        let capabilities = capabilities::package(fixture("LSF_CAPABILITIES_COMPONENT"));
        assert_ne!(generic.digest, dormant.digest);
        assert_ne!(generic.digest, echo.digest);
        Self {
            generic,
            echo,
            capabilities,
            dormant,
        }
    }

    pub fn packages(&self) -> [&Package; 4] {
        [&self.generic, &self.echo, &self.capabilities, &self.dormant]
    }
}

impl Package {
    fn echo() -> Self {
        let component_path = required_path("LSF_ECHO_COMPONENT");
        let directory = component_path.parent().expect("echo package directory");
        let component = bounded_file(&component_path, 16 * 1024 * 1024);
        let mut manifest: Value =
            serde_json::from_slice(&bounded_file(&directory.join("capsule.json"), 1024 * 1024))
                .expect("generated echo manifest");
        assert_eq!(
            manifest["component"]["digest"],
            content_digest(&component).0
        );
        manifest["metadata"]["name"] = json!(SHARED);
        manifest["execution"]["limits"]["cpuFuel"] = json!(10_000_000_000_u64);
        manifest["execution"]["limits"]["memoryBytes"] = json!(67_108_864);
        let contracts = bounded_file(&directory.join("contracts.json"), 1024 * 1024);
        decode_contract_metadata(&contracts, ContractMetadataLimits::default())
            .expect("complete generated echo metadata");
        Self::create(
            variant(&component, "echo"),
            manifest,
            contracts,
            SHARED,
            "examples:echo/api@0.1.0",
            "examples",
        )
    }

    fn create(
        component: Vec<u8>,
        mut manifest: Value,
        contracts: Vec<u8>,
        service: &str,
        contract: &str,
        tenant: &str,
    ) -> Self {
        let directory = tempfile::tempdir().expect("client-only fixture package");
        let digest = content_digest(&component).0;
        manifest["component"]["digest"] = json!(digest);
        let component_path = directory.path().join("component.wasm");
        let manifest_path = directory.path().join("capsule.json");
        let contracts_path = directory.path().join("contracts.json");
        fs::write(&component_path, component).expect("component input");
        write_json(&manifest_path, &manifest);
        fs::write(&contracts_path, contracts).expect("typed metadata input");
        Self {
            directory,
            manifest: manifest_path,
            component: component_path,
            contracts: contracts_path,
            digest,
            service: service.to_owned(),
            contract: contract.to_owned(),
            tenant: tenant.to_owned(),
        }
    }

    pub fn profile(&self) -> &str {
        if self.tenant == "tests" {
            "tests"
        } else {
            "examples"
        }
    }

    pub fn deployment(&self, id: &str) -> PathBuf {
        let mut deployment: Value = serde_json::from_slice(include_bytes!(
            "../../../../examples/echo-contract/deployment.json"
        ))
        .expect("deployment template");
        let capsule: Value = serde_json::from_slice(&bounded_file(&self.manifest, 1024 * 1024))
            .expect("capsule fixture");
        deployment["metadata"]["name"] = json!(id);
        deployment["metadata"]["tenant"] = json!(self.tenant);
        deployment["spec"]["service"] = json!(self.service);
        deployment["spec"]["release"] = json!(self.digest);
        deployment["spec"]["resources"] = capsule["execution"]["limits"].clone();
        deployment["spec"]["grants"] = json!(capsule["imports"]
            .as_array()
            .expect("imports")
            .iter()
            .map(|import| json!({"capability": import["contract"],
                "policy":"conformance/activation-scoped"}))
            .collect::<Vec<_>>());
        let path = self.directory.path().join(format!("{id}.json"));
        write_json(&path, &deployment);
        path
    }

    pub fn input(&self, name: &str, value: &Value) -> PathBuf {
        let path = self.directory.path().join(name);
        write_json(&path, value);
        path
    }
}

pub fn path(path: &Path) -> &str {
    path.to_str().expect("UTF-8 fixture path")
}

pub fn required_path(name: &str) -> PathBuf {
    let path = PathBuf::from(std::env::var_os(name).expect("required conformance input missing"));
    assert!(
        path.is_absolute() && path.is_file(),
        "required absolute input path"
    );
    path
}

pub fn bounded_file(path: &Path, maximum: usize) -> Vec<u8> {
    let mut bytes = Vec::new();
    fs::File::open(path)
        .expect("required fixture")
        .take(u64::try_from(maximum + 1).expect("fixture bound"))
        .read_to_end(&mut bytes)
        .expect("bounded fixture read");
    assert!(
        !bytes.is_empty() && bytes.len() <= maximum,
        "fixture size ceiling"
    );
    bytes
}

fn fixture(name: &str) -> Vec<u8> {
    bounded_file(&required_path(name), 16 * 1024 * 1024)
}

fn variant(bytes: &[u8], marker: &str) -> Vec<u8> {
    // A component custom section changes immutable byte identity without changing
    // the executable component, imports, exports, or the tenant namespace.
    let name = b"latent.phase1.conformance";
    let length = 1 + name.len() + marker.len();
    assert!(length < 128);
    let mut output = bytes.to_vec();
    output.extend_from_slice(&[
        0,
        u8::try_from(length).expect("tiny custom section"),
        u8::try_from(name.len()).expect("short section name"),
    ]);
    output.extend_from_slice(name);
    output.extend_from_slice(marker.as_bytes());
    output
}

fn write_json(path: &Path, value: &Value) {
    fs::write(path, serde_json::to_vec(value).expect("fixture JSON")).expect("fixture file");
}

fn normalize_contracts(mut value: Value) -> Vec<u8> {
    for contract in value["contracts"].as_array_mut().expect("contracts") {
        for interface in contract["interfaces"].as_array_mut().expect("interfaces") {
            assign_digest(interface);
        }
        assign_digest(contract);
    }
    let limits = ContractMetadataLimits::default();
    let decoded = decode_contract_metadata(
        &serde_json::to_vec(&value).expect("descriptor JSON"),
        limits,
    )
    .expect("complete typed descriptor table");
    encode_contract_metadata(&decoded, limits).expect("canonical typed metadata")
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
