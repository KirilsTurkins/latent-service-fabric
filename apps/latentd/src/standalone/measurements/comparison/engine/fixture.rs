use super::super::super::{
    fixtures::{self, Fixture},
    platform,
};
use super::{
    files::{self, Reference},
    Result,
};
use latent_artifacts::{
    content_digest, encode_contract_metadata, ContractDescriptor, ContractMetadataLimits,
    FieldDescriptor, FunctionDescriptor, InterfaceDescriptor, ValueType,
};
use latent_core::{ContractId, DeploymentId, FunctionId, InterfaceId, Metadata};
use serde::Deserialize;
use serde_json::{json, Value};
use std::path::Path;

pub(super) const IDS: [&str; 5] = [
    "echo",
    "optimization",
    "generic",
    "capabilities",
    "engine-memory",
];
pub(super) const DIRTY: &str = "engine-memory-dirty-4194304-a5";
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FixtureComponent {
    id: String,
    component: Reference,
    contracts: Option<Reference>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    schema: String,
    components: Vec<FixtureComponent>,
}

pub(super) fn load(root: &Path, input: &[u8], identity: &Value) -> Result<Vec<Fixture>> {
    let manifest: Manifest = serde_json::from_slice(input)?;
    if manifest.schema != "latent.optimization.engine-fixtures.v1"
        || !manifest
            .components
            .iter()
            .map(|row| row.id.as_str())
            .eq(IDS)
    {
        return Err("engine fixture population".into());
    }
    let identities = identity["fixtures"]
        .as_array()
        .filter(|rows| rows.len() == 5)
        .ok_or("engine identity fixture population")?;
    let mut components = Vec::with_capacity(5);
    for (row, id) in manifest.components.iter().zip(IDS) {
        if row.contracts.is_some() != (id == "optimization") {
            return Err("engine contract fixture presence".into());
        }
        let bytes = files::load(root, &row.component, 16 * 1024 * 1024)?;
        if !identities.iter().any(|v| {
            v["name"] == id
                && v["sha256"] == row.component.sha256
                && v["bytes"] == row.component.bytes
        }) {
            return Err("engine fixture source identity".into());
        }
        let contracts = match id {
            "echo" => include_bytes!(concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/../../examples/echo-contract/contracts.json"
            ))
            .to_vec(),
            "optimization" => files::load(
                root,
                row.contracts.as_ref().ok_or("optimization contracts")?,
                1024 * 1024,
            )?,
            "generic" => fixtures::generic::contracts(),
            "capabilities" => fixtures::capabilities::capabilities(),
            "engine-memory" => memory_contracts()?,
            _ => return Err("engine component id".into()),
        };
        components.push((bytes, contracts));
    }
    // Stable target order: echo A, compute A, generic A/B, capabilities A/B, memory A/B.
    [
        (0, "a"),
        (1, "a"),
        (2, "a"),
        (2, "b"),
        (3, "a"),
        (3, "b"),
        (4, "a"),
        (4, "b"),
    ]
    .into_iter()
    .map(|(index, tenant)| {
        let (bytes, contracts) = &components[index];
        build(
            index,
            tenant,
            if tenant == "b" {
                variant(bytes, IDS[index])?
            } else {
                bytes.clone()
            },
            contracts,
        )
    })
    .collect()
}

fn build(index: usize, marker: &str, bytes: Vec<u8>, contracts: &[u8]) -> Result<Fixture> {
    let mut manifest: Value = serde_json::from_slice(include_bytes!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../examples/echo-contract/capsule.json"
    )))?;
    let (service, world, exports) = match index {
        0 => (
            "engine-echo",
            "examples:echo/service@0.1.0",
            vec!["examples:echo/api@0.1.0"],
        ),
        1 => (
            "engine-compute",
            "optimization:benchmark/service@0.1.0",
            vec!["optimization:benchmark/workloads@0.1.0"],
        ),
        2 => (
            "engine-generic",
            "tests:generic/service@0.1.0",
            vec![
                "tests:generic/values@0.1.0",
                "tests:generic/alternate@0.1.0",
            ],
        ),
        3 => (
            "engine-capabilities",
            "tests:capabilities/service@0.1.0",
            vec!["tests:capabilities/api@0.1.0"],
        ),
        4 => (
            "engine-memory",
            "tests:engine-memory/service@0.1.0",
            vec!["tests:engine-memory/memory@0.1.0"],
        ),
        _ => return Err("engine fixture index".into()),
    };
    manifest["component"]["world"] = json!(world);
    manifest["exports"] = json!(exports);
    if index != 0 {
        let imports: &[&str] = match index {
            3 => &[
                "latent:context/context@0.1.0",
                "latent:log/log@0.1.0",
                "latent:clock/monotonic@0.1.0",
                "latent:clock/wall@0.1.0",
            ],
            4 => &["latent:log/log@0.1.0"],
            _ => &[],
        };
        manifest["imports"] = json!(imports
            .iter()
            .map(|id| json!({"contract":id,"optional":false}))
            .collect::<Vec<_>>());
    }
    manifest["execution"]["limits"]["wallTimeLimitMillis"] = json!(5000);
    let tenant = format!("engine-{marker}");
    let mut fixture = fixtures::build(&tenant, service, exports[0], bytes, manifest, contracts)?;
    fixture
        .artifact
        .manifest
        .execution
        .resource_budget_ceiling
        .wall_time_limit_millis = Some(5000);
    fixture.deployment.resources.wall_time_limit_millis = Some(5000);
    fixture.deployment.id = DeploymentId(format!("{tenant}-{service}"));
    fixture
        .deployment
        .metadata
        .name
        .clone_from(&fixture.deployment.id.0);
    Ok(fixture)
}

fn variant(base: &[u8], family: &str) -> Result<Vec<u8>> {
    fn leb(mut value: usize, bytes: &mut Vec<u8>) -> Result<()> {
        loop {
            let next = u8::try_from(value & 127)?;
            value >>= 7;
            bytes.push(next | if value == 0 { 0 } else { 128 });
            if value == 0 {
                break;
            }
        }
        Ok(())
    }
    let name = b"latent.engine-fixture.tenant-b";
    let mut section = Vec::new();
    leb(name.len(), &mut section)?;
    section.extend_from_slice(name);
    section.extend_from_slice(family.as_bytes());
    section.extend_from_slice(b"/v1");
    let mut bytes = base.to_vec();
    bytes.push(0);
    leb(section.len(), &mut bytes)?;
    bytes.extend(section);
    if bytes.len() > 16 * 1024 * 1024 {
        return Err("engine tenant variant bound".into());
    }
    Ok(bytes)
}

fn memory_contracts() -> Result<Vec<u8>> {
    let id = "tests:engine-memory/memory@0.1.0";
    let field = |name: &str, value_type| FieldDescriptor {
        name: name.into(),
        value_type,
        documentation: None,
    };
    let digest = content_digest(id.as_bytes()).0;
    let descriptor = ContractDescriptor {
        id: ContractId(id.into()),
        package_name: "tests:engine-memory".into(),
        semantic_version: "0.1.0".into(),
        dependencies: Vec::new(),
        digest: digest.clone(),
        interfaces: vec![InterfaceDescriptor {
            id: InterfaceId(id.into()),
            digest,
            documentation: None,
            functions: vec![FunctionDescriptor {
                id: FunctionId("run".into()),
                name: "run".into(),
                asynchronous: false,
                parameters: vec![field("mode", ValueType::Variant("mode".into()))],
                results: vec![field("result", ValueType::U32)],
                documentation: None,
                attributes: Metadata::new(),
            }],
        }],
    };
    let limits = ContractMetadataLimits::default();
    let mut value: Value = serde_json::from_slice(
        &encode_contract_metadata(&[descriptor], limits).map_err(platform)?,
    )?;
    for contract in value["contracts"]
        .as_array_mut()
        .ok_or("engine contract document")?
    {
        for interface in contract["interfaces"]
            .as_array_mut()
            .ok_or("engine interface document")?
        {
            digest_value(interface)?;
        }
        digest_value(contract)?;
    }
    let decoded = latent_artifacts::decode_contract_metadata(&serde_json::to_vec(&value)?, limits)
        .map_err(platform)?;
    encode_contract_metadata(&decoded, limits).map_err(platform)
}
fn digest_value(value: &mut Value) -> Result<()> {
    let mut identity = value.clone();
    identity
        .as_object_mut()
        .ok_or("engine descriptor shape")?
        .remove("digest");
    value["digest"] = json!(content_digest(&serde_json::to_vec(&identity)?).0);
    Ok(())
}
