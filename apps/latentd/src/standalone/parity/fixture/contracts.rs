use latent_artifacts::{
    decode_contract_metadata, encode_contract_metadata, ContractDescriptor, ContractMetadataLimits,
    FieldDescriptor, FunctionDescriptor, InterfaceDescriptor, ValueType,
};
use latent_core::{ContractId, FunctionId, InterfaceId, Metadata};
use serde_json::{json, Value};

pub fn capabilities() -> Vec<u8> {
    let record = |name: &str| ValueType::Record(name.to_owned());
    let fields = || ValueType::List(Box::new(record("field")));
    let functions = vec![
        function("snapshot", Vec::new(), record("context-snapshot")),
        function(
            "log-probe",
            vec![
                field("message", ValueType::String),
                field("fields", fields()),
            ],
            record("log-observation"),
        ),
        function(
            "log-twice",
            vec![
                field("message", ValueType::String),
                field("fields", fields()),
            ],
            ValueType::List(Box::new(record("log-observation"))),
        ),
        function(
            "clocks",
            Vec::new(),
            ValueType::List(Box::new(record("clock-reading"))),
        ),
        function("work-observe", Vec::new(), record("work-observation")),
    ];
    let id = "tests:capabilities/api@0.1.0";
    let digest = latent_artifacts::content_digest(id.as_bytes()).0;
    let descriptor = ContractDescriptor {
        id: ContractId(id.to_owned()),
        package_name: "tests:capabilities".to_owned(),
        semantic_version: "0.1.0".to_owned(),
        dependencies: Vec::new(),
        digest: digest.clone(),
        interfaces: vec![InterfaceDescriptor {
            id: InterfaceId(id.to_owned()),
            functions,
            documentation: None,
            digest,
        }],
    };
    let limits = ContractMetadataLimits::default();
    let mut value: Value =
        serde_json::from_slice(&encode_contract_metadata(&[descriptor], limits).unwrap()).unwrap();
    for contract in value["contracts"].as_array_mut().unwrap() {
        for interface in contract["interfaces"].as_array_mut().unwrap() {
            assign_digest(interface);
        }
        assign_digest(contract);
    }
    let decoded = decode_contract_metadata(&serde_json::to_vec(&value).unwrap(), limits).unwrap();
    encode_contract_metadata(&decoded, limits).unwrap()
}

fn function(name: &str, parameters: Vec<FieldDescriptor>, result: ValueType) -> FunctionDescriptor {
    FunctionDescriptor {
        id: FunctionId(name.to_owned()),
        name: name.to_owned(),
        asynchronous: false,
        parameters,
        results: vec![field("result", result)],
        documentation: None,
        attributes: Metadata::new(),
    }
}

fn field(name: &str, value_type: ValueType) -> FieldDescriptor {
    FieldDescriptor {
        name: name.to_owned(),
        value_type,
        documentation: None,
    }
}

fn assign_digest(value: &mut Value) {
    let mut identity = value.clone();
    identity.as_object_mut().unwrap().remove("digest");
    value["digest"] =
        json!(latent_artifacts::content_digest(&serde_json::to_vec(&identity).unwrap()).0);
}
