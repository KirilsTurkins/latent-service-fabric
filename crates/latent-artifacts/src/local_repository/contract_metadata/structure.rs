use latent_contracts::{ContractDescriptor, FieldDescriptor, ValueType};
use latent_core::PlatformError;
use latent_manifest::__serde_json::Value;

use super::{exhausted, invalid, ContractMetadataLimits};

/// Reject public schema extensions without tightening the older persisted DTO decoder.
pub(super) fn validate_json(value: &Value) -> Result<(), PlatformError> {
    fields(value, &["format_version", "contracts"])?;
    if value.get("format_version").and_then(Value::as_u64) != Some(1) {
        return Err(invalid());
    }
    for contract in array(value, "contracts")? {
        fields(
            contract,
            &[
                "id",
                "package_name",
                "semantic_version",
                "interfaces",
                "dependencies",
                "digest",
            ],
        )?;
        for interface in array(contract, "interfaces")? {
            fields(interface, &["id", "functions", "documentation", "digest"])?;
            for function in array(interface, "functions")? {
                fields(
                    function,
                    &[
                        "id",
                        "name",
                        "asynchronous",
                        "parameters",
                        "results",
                        "documentation",
                        "attributes",
                    ],
                )?;
                for field in array(function, "parameters")?
                    .iter()
                    .chain(array(function, "results")?)
                {
                    fields(field, &["name", "value_type", "documentation"])?;
                    value_type(field.get("value_type").ok_or_else(invalid)?)?;
                }
            }
        }
    }
    Ok(())
}

fn fields(value: &Value, allowed: &[&str]) -> Result<(), PlatformError> {
    let object = value.as_object().ok_or_else(invalid)?;
    if object.keys().any(|key| !allowed.contains(&key.as_str())) {
        return Err(invalid());
    }
    Ok(())
}
fn array<'a>(value: &'a Value, field: &str) -> Result<&'a Vec<Value>, PlatformError> {
    value
        .get(field)
        .and_then(Value::as_array)
        .ok_or_else(invalid)
}
fn value_type(value: &Value) -> Result<(), PlatformError> {
    let Some(object) = value.as_object() else {
        return Ok(());
    }; // Scalar enum names are checked by Serde.
    if object.len() != 1 {
        return Err(invalid());
    }
    let (kind, inner) = object.iter().next().ok_or_else(invalid)?;
    match kind.as_str() {
        "List" | "Option" | "Future" | "Stream" => value_type(inner)?,
        "Result" => {
            fields(inner, &["ok", "error"])?;
            for name in ["ok", "error"] {
                if let Some(value) = inner.get(name).filter(|value| !value.is_null()) {
                    value_type(value)?;
                }
            }
        }
        "Tuple" => {
            for value in inner.as_array().ok_or_else(invalid)? {
                value_type(value)?;
            }
        }
        "Record" | "Variant" | "Resource" => {}
        _ => return Err(invalid()),
    }
    Ok(())
}

/// Counts the entire schema before recursive DTO conversion, including empty
/// contracts/interfaces/functions, dependencies, map rows and documentation.
pub(super) fn validate_owned(
    contracts: &[ContractDescriptor],
    limits: ContractMetadataLimits,
) -> Result<(), PlatformError> {
    let mut budget = OwnedBudget {
        limits,
        nodes: 0,
        retained: 0,
    };
    budget.object(&["format_version", "contracts"], 1)?;
    budget.node(2)?; // version
    budget.node(2)?; // contracts array
    for contract in contracts {
        budget.object(
            &[
                "id",
                "package_name",
                "semantic_version",
                "interfaces",
                "dependencies",
                "digest",
            ],
            3,
        )?;
        for value in [
            &contract.id.0,
            &contract.package_name,
            &contract.semantic_version,
            &contract.digest,
        ] {
            budget.string(value, 4)?;
        }
        budget.node(4)?;
        for dependency in &contract.dependencies {
            budget.string(&dependency.0, 5)?;
        }
        budget.node(4)?;
        for interface in &contract.interfaces {
            budget.object(&["id", "functions", "documentation", "digest"], 5)?;
            budget.string(&interface.id.0, 6)?;
            budget.string(&interface.digest, 6)?;
            budget.optional(interface.documentation.as_deref(), 6)?;
            budget.node(6)?;
            for function in &interface.functions {
                budget.object(
                    &[
                        "id",
                        "name",
                        "asynchronous",
                        "parameters",
                        "results",
                        "documentation",
                        "attributes",
                    ],
                    7,
                )?;
                budget.string(&function.id.0, 8)?;
                budget.string(&function.name, 8)?;
                budget.node(8)?;
                budget.optional(function.documentation.as_deref(), 8)?;
                budget.node(8)?;
                for (key, value) in &function.attributes {
                    budget.string(key, 9)?;
                    budget.string(value, 9)?;
                }
                for fields in [&function.parameters, &function.results] {
                    budget.node(8)?;
                    for field in fields {
                        budget.field(field, 9)?;
                    }
                }
            }
        }
    }
    Ok(())
}

struct OwnedBudget {
    limits: ContractMetadataLimits,
    nodes: usize,
    retained: usize,
}
impl OwnedBudget {
    fn charge(&mut self, bytes: usize) -> Result<(), PlatformError> {
        self.retained = self
            .retained
            .checked_add(bytes)
            .filter(|v| *v <= self.limits.max_retained_bytes)
            .ok_or_else(|| exhausted("contract-metadata-retained-limit"))?;
        Ok(())
    }
    fn node(&mut self, depth: usize) -> Result<(), PlatformError> {
        if depth > self.limits.max_depth {
            return Err(exhausted("contract-metadata-depth-limit"));
        }
        self.nodes = self
            .nodes
            .checked_add(1)
            .filter(|v| *v <= self.limits.max_nodes)
            .ok_or_else(|| exhausted("contract-metadata-node-limit"))?;
        self.charge(1024)
    }
    fn string(&mut self, value: &str, depth: usize) -> Result<(), PlatformError> {
        self.node(depth)?;
        if value.len() > self.limits.max_string_bytes {
            return Err(exhausted("contract-metadata-string-limit"));
        }
        // Covers cloned DTO strings and the worst-case escaped output plus the
        // decoder's scratch allowance during the exact read-back check.
        self.charge(
            value
                .len()
                .checked_mul(16)
                .ok_or_else(|| exhausted("contract-metadata-retained-limit"))?,
        )
    }
    fn object(&mut self, keys: &[&str], depth: usize) -> Result<(), PlatformError> {
        self.node(depth)?;
        for key in keys {
            self.string(key, depth + 1)?;
        }
        Ok(())
    }
    fn optional(&mut self, value: Option<&str>, depth: usize) -> Result<(), PlatformError> {
        match value {
            Some(value) => self.string(value, depth),
            None => self.node(depth),
        }
    }
    fn field(&mut self, field: &FieldDescriptor, depth: usize) -> Result<(), PlatformError> {
        self.object(&["name", "value_type", "documentation"], depth)?;
        self.string(&field.name, depth + 1)?;
        self.optional(field.documentation.as_deref(), depth + 1)?;
        self.value_type(&field.value_type, depth + 1)
    }
    fn value_type(&mut self, value: &ValueType, depth: usize) -> Result<(), PlatformError> {
        match value {
            ValueType::List(inner)
            | ValueType::Option(inner)
            | ValueType::Future(inner)
            | ValueType::Stream(inner) => {
                let key = match value {
                    ValueType::List(_) => "List",
                    ValueType::Option(_) => "Option",
                    ValueType::Future(_) => "Future",
                    _ => "Stream",
                };
                self.object(&[key], depth)?;
                self.value_type(inner, depth + 1)
            }
            ValueType::Result { ok, error } => {
                self.object(&["Result"], depth)?;
                self.object(&["ok", "error"], depth + 1)?;
                for value in [ok, error] {
                    if let Some(value) = value {
                        self.value_type(value, depth + 2)?;
                    } else {
                        self.node(depth + 2)?;
                    }
                }
                Ok(())
            }
            ValueType::Tuple(values) => {
                self.object(&["Tuple"], depth)?;
                self.node(depth + 1)?;
                for value in values {
                    self.value_type(value, depth + 2)?;
                }
                Ok(())
            }
            ValueType::Record(name) | ValueType::Variant(name) | ValueType::Resource(name) => {
                let key = match value {
                    ValueType::Record(_) => "Record",
                    ValueType::Variant(_) => "Variant",
                    _ => "Resource",
                };
                self.object(&[key], depth)?;
                self.string(name, depth + 1)
            }
            _ => self.string(
                match value {
                    ValueType::Bool => "Bool",
                    ValueType::U8 => "U8",
                    ValueType::U16 => "U16",
                    ValueType::U32 => "U32",
                    ValueType::U64 => "U64",
                    ValueType::S8 => "S8",
                    ValueType::S16 => "S16",
                    ValueType::S32 => "S32",
                    ValueType::S64 => "S64",
                    ValueType::F32 => "F32",
                    ValueType::F64 => "F64",
                    ValueType::Char => "Char",
                    ValueType::String => "String",
                    ValueType::Bytes => "Bytes",
                    _ => unreachable!(),
                },
                depth,
            ),
        }
    }
}
