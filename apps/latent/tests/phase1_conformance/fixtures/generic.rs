use latent_artifacts::{
    encode_contract_metadata, ContractDescriptor, ContractMetadataLimits, FieldDescriptor,
    FunctionDescriptor, InterfaceDescriptor, ValueType,
};
use latent_core::{ContractId, FunctionId, InterfaceId, Metadata};
use serde_json::{json, Value};

use super::{normalize_contracts, Package};

pub(super) fn package(bytes: Vec<u8>, service: &str) -> Package {
    Package::create(
        bytes,
        manifest(
            service,
            "tests:generic/service@0.1.0",
            &[
                "tests:generic/values@0.1.0",
                "tests:generic/alternate@0.1.0",
            ],
        ),
        contracts(),
        service,
        "tests:generic/values@0.1.0",
        "tests",
    )
}

pub(super) fn manifest(service: &str, world: &str, exports: &[&str]) -> Value {
    let mut manifest: Value = serde_json::from_slice(include_bytes!(
        "../../../../../examples/echo-contract/capsule.json"
    ))
    .expect("capsule template");
    manifest["metadata"]["name"] = json!(service);
    manifest["metadata"]["tenant"] = json!("tests");
    manifest["component"]["world"] = json!(world);
    manifest["exports"] = json!(exports);
    manifest["imports"] = json!([]);
    manifest["execution"]["threading"] = json!("single-threaded");
    manifest["execution"]["limits"]["cpuFuel"] = json!(10_000_000_000_u64);
    manifest["execution"]["limits"]["memoryBytes"] = json!(67_108_864);
    manifest["execution"]["snapshotEligible"] = json!(false);
    manifest["execution"]["fusionEligible"] = json!(false);
    manifest
}

fn contracts() -> Vec<u8> {
    let mut functions = ["identify", "bump", "trap", "spin", "grow"]
        .into_iter()
        .map(|name| function(name, Vec::new(), Some(ValueType::U32)))
        .collect::<Vec<_>>();
    functions.extend([
        function(
            "combine",
            vec![
                field("left", ValueType::S32),
                field("right", ValueType::S32),
            ],
            Some(ValueType::S32),
        ),
        function(
            "transform",
            vec![field("value", ValueType::Record("composite".to_owned()))],
            Some(ValueType::Record("composite".to_owned())),
        ),
        function(
            "checked",
            vec![field("allowed", ValueType::Bool)],
            Some(ValueType::Result {
                ok: Some(Box::new(ValueType::String)),
                error: Some(Box::new(ValueType::Variant("selection".to_owned()))),
            }),
        ),
        function("nothing", Vec::new(), None),
        function(
            "unit-result",
            vec![field("allowed", ValueType::Bool)],
            Some(ValueType::Result {
                ok: None,
                error: None,
            }),
        ),
    ]);
    let contracts = vec![
        contract("tests:generic", "values", functions),
        contract(
            "tests:generic",
            "alternate",
            vec![function("identify", Vec::new(), Some(ValueType::U32))],
        ),
    ];
    encode_contracts(&contracts)
}

pub(super) fn encode_contracts(contracts: &[ContractDescriptor]) -> Vec<u8> {
    let bytes = encode_contract_metadata(contracts, ContractMetadataLimits::default())
        .expect("complete descriptor table");
    normalize_contracts(serde_json::from_slice(&bytes).expect("typed descriptor JSON"))
}

pub(super) fn contract(
    package: &str,
    name: &str,
    functions: Vec<FunctionDescriptor>,
) -> ContractDescriptor {
    let id = format!("{package}/{name}@0.1.0");
    let digest = latent_artifacts::content_digest(id.as_bytes()).0;
    ContractDescriptor {
        id: ContractId(id.clone()),
        package_name: package.to_owned(),
        semantic_version: "0.1.0".to_owned(),
        dependencies: Vec::new(),
        digest: digest.clone(),
        interfaces: vec![InterfaceDescriptor {
            id: InterfaceId(id),
            functions,
            documentation: None,
            digest,
        }],
    }
}

pub(super) fn function(
    name: &str,
    parameters: Vec<FieldDescriptor>,
    result: Option<ValueType>,
) -> FunctionDescriptor {
    FunctionDescriptor {
        id: FunctionId(name.to_owned()),
        name: name.to_owned(),
        asynchronous: false,
        parameters,
        results: result
            .into_iter()
            .map(|value| field("result", value))
            .collect(),
        documentation: None,
        attributes: Metadata::new(),
    }
}

pub(super) fn field(name: &str, value_type: ValueType) -> FieldDescriptor {
    FieldDescriptor {
        name: name.to_owned(),
        value_type,
        documentation: None,
    }
}
