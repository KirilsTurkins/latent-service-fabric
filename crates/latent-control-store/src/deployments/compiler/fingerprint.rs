use latent_artifacts::{content_digest, ContractDescriptor, FieldDescriptor, ValueType};
use latent_core::{PlatformError, PlatformErrorCode};
use latent_manifest::__serde_json as json;

use super::super::observation::{count, Work};
use super::error;

pub(super) fn contract_fingerprint(
    contract: &ContractDescriptor,
    work: &mut Work,
) -> Result<String, PlatformError> {
    let canonical = contract_value(contract);
    count!(work, contract_schema_encodes, 1);
    let bytes = json::to_vec(&canonical)
        .map_err(|_| error(PlatformErrorCode::Internal, "contract-encoding-failed"))?;
    Ok(content_digest(&bytes).0)
}

fn contract_value(contract: &ContractDescriptor) -> json::Value {
    let mut interfaces = contract
        .interfaces
        .iter()
        .map(|interface| {
            let mut functions = interface
                .functions
                .iter()
                .map(|function| {
                    json::json!({
                        "id": function.id.0,
                        "name": function.name,
                        "asynchronous": function.asynchronous,
                        "parameters": function.parameters.iter().map(field_value).collect::<Vec<_>>(),
                        "results": function.results.iter().map(field_value).collect::<Vec<_>>(),
                        "documentation": function.documentation,
                        "attributes": function.attributes,
                    })
                })
                .collect::<Vec<_>>();
            functions.sort_by(|left, right| left["id"].as_str().cmp(&right["id"].as_str()));
            json::json!({
                "id": interface.id.0,
                "digest": interface.digest,
                "documentation": interface.documentation,
                "functions": functions,
            })
        })
        .collect::<Vec<_>>();
    interfaces.sort_by(|left, right| left["id"].as_str().cmp(&right["id"].as_str()));
    let mut dependencies = contract
        .dependencies
        .iter()
        .map(|id| id.0.as_str())
        .collect::<Vec<_>>();
    dependencies.sort_unstable();
    json::json!({
        "id": contract.id.0,
        "package": contract.package_name,
        "version": contract.semantic_version,
        "digest": contract.digest,
        "dependencies": dependencies,
        "interfaces": interfaces,
    })
}

fn field_value(field: &FieldDescriptor) -> json::Value {
    json::json!({
        "name": field.name,
        "type": type_value(&field.value_type),
        "documentation": field.documentation,
    })
}

fn type_value(value: &ValueType) -> json::Value {
    use ValueType::{List, Option, Result, Tuple};
    match value {
        List(inner) => json::json!(["list", type_value(inner)]),
        Option(inner) => json::json!(["option", type_value(inner)]),
        Result { ok, error } => json::json!([
            "result",
            ok.as_deref().map(type_value),
            error.as_deref().map(type_value),
        ]),
        Tuple(values) => json::json!(["tuple", values.iter().map(type_value).collect::<Vec<_>>()]),
        ValueType::Record(name) => json::json!(["record", name]),
        ValueType::Variant(name) => json::json!(["variant", name]),
        ValueType::Resource(name) => json::json!(["resource", name]),
        ValueType::Future(inner) => json::json!(["future", type_value(inner)]),
        ValueType::Stream(inner) => json::json!(["stream", type_value(inner)]),
        ValueType::Bool => json::json!("bool"),
        ValueType::U8 => json::json!("u8"),
        ValueType::U16 => json::json!("u16"),
        ValueType::U32 => json::json!("u32"),
        ValueType::U64 => json::json!("u64"),
        ValueType::S8 => json::json!("s8"),
        ValueType::S16 => json::json!("s16"),
        ValueType::S32 => json::json!("s32"),
        ValueType::S64 => json::json!("s64"),
        ValueType::F32 => json::json!("f32"),
        ValueType::F64 => json::json!("f64"),
        ValueType::Char => json::json!("char"),
        ValueType::String => json::json!("string"),
        ValueType::Bytes => json::json!("bytes"),
    }
}
