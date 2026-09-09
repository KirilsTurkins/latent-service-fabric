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
use latent_manifest::{ManifestValidator, Phase1ManifestValidator};
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
        build(index, tenant, bytes, contracts)
    })
    .collect()
}

struct Definition {
    service: &'static str,
    world: &'static str,
    exports: &'static [&'static str],
}

fn definition(index: usize) -> Result<Definition> {
    Ok(match index {
        0 => Definition {
            service: "engine-echo",
            world: "examples:echo/service@0.1.0",
            exports: &["examples:echo/api@0.1.0"],
        },
        1 => Definition {
            service: "engine-compute",
            world: "optimization:benchmark/service@0.1.0",
            exports: &["optimization:benchmark/workloads@0.1.0"],
        },
        2 => Definition {
            service: "engine-generic",
            world: "tests:generic/service@0.1.0",
            exports: &[
                "tests:generic/values@0.1.0",
                "tests:generic/alternate@0.1.0",
            ],
        },
        3 => Definition {
            service: "engine-capabilities",
            world: "tests:capabilities/service@0.1.0",
            exports: &["tests:capabilities/api@0.1.0"],
        },
        4 => Definition {
            service: "engine-memory",
            world: "tests:engine-memory/service@0.1.0",
            exports: &["tests:engine-memory/memory@0.1.0"],
        },
        _ => return Err("engine fixture index".into()),
    })
}

fn build(index: usize, marker: &str, base: &[u8], contracts: &[u8]) -> Result<Fixture> {
    let mut manifest: Value = serde_json::from_slice(include_bytes!(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../examples/echo-contract/capsule.json"
    )))?;
    let Definition {
        service,
        world,
        exports,
    } = definition(index)?;
    let original = world.split_once(':').ok_or("engine world namespace")?.0;
    let tenant = format!("engine-{marker}");
    let mut bytes = super::namespace::retarget(base, original, &tenant, exports)?;
    if marker == "b" {
        bytes = variant(&bytes, IDS[index])?;
    }
    let contracts = scoped_contracts(contracts, original, &tenant)?;
    let exports = exports
        .iter()
        .map(|name| scoped_name(name, original, &tenant))
        .collect::<Result<Vec<_>>>()?;
    manifest["component"]["world"] = json!(scoped_name(world, original, &tenant)?);
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
    let mut fixture = fixtures::build(&tenant, service, &exports[0], bytes, manifest, &contracts)?;
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
    // This validates both full manifests and their association before Node::start.
    Phase1ManifestValidator
        .validate_deployment_against_capsule(&fixture.deployment, &fixture.artifact.manifest)
        .map_err(|violations| format!("engine fixture semantic validation: {violations:?}"))?;
    Ok(fixture)
}

fn scoped_name(name: &str, original: &str, tenant: &str) -> Result<String> {
    let (namespace, suffix) = name
        .split_once(':')
        .ok_or("engine owned namespace missing")?;
    if namespace != original || suffix.is_empty() {
        return Err("engine owned namespace mismatch".into());
    }
    Ok(format!("{tenant}:{suffix}"))
}

fn scoped_contracts(bytes: &[u8], original: &str, tenant: &str) -> Result<Vec<u8>> {
    let limits = ContractMetadataLimits::default();
    let mut decoded =
        latent_artifacts::decode_contract_metadata(bytes, limits).map_err(platform)?;
    for contract in &mut decoded {
        if !contract.dependencies.is_empty() {
            return Err("engine fixture unexpected owned contract dependency".into());
        }
        contract.id.0 = scoped_name(&contract.id.0, original, tenant)?;
        contract.package_name = scoped_name(&contract.package_name, original, tenant)?;
        for interface in &mut contract.interfaces {
            interface.id.0 = scoped_name(&interface.id.0, original, tenant)?;
        }
    }
    let value =
        serde_json::from_slice(&encode_contract_metadata(&decoded, limits).map_err(platform)?)?;
    canonical_digests(value, limits)
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
    let value: Value = serde_json::from_slice(
        &encode_contract_metadata(&[descriptor], limits).map_err(platform)?,
    )?;
    canonical_digests(value, limits)
}

fn canonical_digests(mut value: Value, limits: ContractMetadataLimits) -> Result<Vec<u8>> {
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

#[test]
#[ignore = "explicit engine fixture manifest; validates actual components without an Engine or Invoke"]
fn actual_tenant_fixtures_validate_before_node_start() -> Result<()> {
    let path = files::required("LSF_ENGINE_FIXTURES")?;
    let root = path.parent().ok_or("engine fixture root")?.canonicalize()?;
    let bytes = files::read(&path, 1024 * 1024)?;
    let manifest: Manifest = serde_json::from_slice(&bytes)?;
    let bases = manifest
        .components
        .iter()
        .map(|component| files::load(&root, &component.component, 16 * 1024 * 1024))
        .collect::<Result<Vec<_>>>()?;
    let identity = json!({"fixtures":manifest.components.iter().zip(&bases).map(|(row, base)| {
        json!({"name":row.id,"sha256":content_digest(base).0,"bytes":base.len().to_string()})
    }).collect::<Vec<_>>()});
    let fixtures = load(&root, &bytes, &identity)?;
    assert_eq!(fixtures.len(), 8);
    let mut releases = std::collections::BTreeSet::new();
    for fixture in &fixtures {
        let artifact = &fixture.artifact;
        wasmparser::Validator::new().validate_all(&artifact.component_bytes)?;
        let expected = artifact
            .manifest
            .exports
            .iter()
            .map(|export| export.contract.0.clone())
            .collect::<std::collections::BTreeSet<_>>();
        assert_eq!(outer_exports(&artifact.component_bytes)?, expected);
        assert!(expected.contains(&fixture.target.contract));
        let prefix = format!("{}:", fixture.tenant);
        assert!(artifact.manifest.world.0.starts_with(&prefix));
        assert!(expected.iter().all(|name| name.starts_with(&prefix)));
        assert_eq!(
            artifact
                .contracts
                .iter()
                .map(|contract| contract.id.0.clone())
                .collect::<std::collections::BTreeSet<_>>(),
            expected
        );
        for contract in &artifact.contracts {
            assert!(contract.package_name.starts_with(&prefix));
            assert!(contract
                .interfaces
                .iter()
                .all(|interface| interface.id.0.starts_with(&prefix)));
        }
        assert_eq!(
            artifact.descriptor.release_digest,
            content_digest(&artifact.component_bytes)
        );
        assert!(releases.insert(fixture.release_digest.clone()));
    }
    for (row, original) in manifest.components.iter().zip(bases) {
        assert_eq!(
            files::load(&root, &row.component, 16 * 1024 * 1024)?,
            original
        );
    }
    assert_eq!(files::read(&path, 1024 * 1024)?, bytes);
    // The exact pre-fix mismatch must remain forbidden by production validation.
    let mut wrong_scope = fixtures[0].artifact.manifest.clone();
    wrong_scope.metadata.tenant = Some(latent_core::TenantId("unrelated".into()));
    assert!(Phase1ManifestValidator
        .validate_capsule(&wrong_scope)
        .is_err());
    Ok(())
}

#[cfg(test)]
fn outer_exports(bytes: &[u8]) -> Result<std::collections::BTreeSet<String>> {
    let mut depth = 0_usize;
    let mut names = std::collections::BTreeSet::new();
    for payload in wasmparser::Parser::new(0).parse_all(bytes) {
        match payload? {
            wasmparser::Payload::Version { .. } => depth += 1,
            wasmparser::Payload::End(_) => {
                depth = depth.checked_sub(1).ok_or("engine component depth")?;
            }
            wasmparser::Payload::ComponentExportSection(exports) if depth == 1 => {
                for export in exports {
                    let export = export?;
                    assert_eq!(export.kind, wasmparser::ComponentExternalKind::Instance);
                    assert!(names.insert(export.name.name.to_owned()));
                }
            }
            _ => {}
        }
    }
    assert_eq!(depth, 0);
    Ok(names)
}
