//! Inverse of the supported projection, used only for new authoring inputs.
use latent_artifacts::{
    decode_contract_metadata, encode_contract_metadata, ContractMetadataLimits,
};
use latent_contracts::{
    ContractDescriptor, FieldDescriptor, FunctionDescriptor, InterfaceDescriptor, ValueType,
};
use latent_core::{ContractId, FunctionId, InterfaceId, PlatformError};
use wit_parser::{FunctionKind, Resolve, Type, TypeDefKind, WorldId, WorldItem};

use super::{digest, exhausted, incompatible, interface_name, invalid, validate, SemanticLimits};

pub(in crate::semantics) fn generate(
    resolve: &Resolve,
    world: WorldId,
    limits: SemanticLimits,
) -> Result<Vec<ContractDescriptor>, PlatformError> {
    let placeholder = format!("sha256:{}", "0".repeat(64));
    let mut contracts = Vec::new();
    let mut budget = Projection {
        remaining: limits.max_type_nodes,
        limits,
    };
    for item in resolve.worlds[world].exports.values() {
        let WorldItem::Interface { id, .. } = item else {
            return Err(incompatible("unsupported-contract-world-export"));
        };
        let name = interface_name(resolve, *id, limits)?;
        let interface = &resolve.interfaces[*id];
        let package = &resolve.packages[interface
            .package
            .ok_or_else(|| incompatible("unqualified-contract-interface"))?]
        .name;
        let version = package
            .version
            .as_ref()
            .ok_or_else(|| incompatible("unversioned-contract-interface"))?;
        let mut functions = Vec::new();
        for function in interface.functions.values() {
            if !matches!(
                function.kind,
                FunctionKind::Freestanding | FunctionKind::AsyncFreestanding
            ) {
                return Err(incompatible("unsupported-contract-function-kind"));
            }
            let mut parameters = Vec::new();
            for param in &function.params {
                parameters.push(FieldDescriptor {
                    name: param.name.clone(),
                    value_type: budget.value(resolve, param.ty, 1)?,
                    documentation: None,
                });
            }
            let mut results = Vec::new();
            if let Some(result) = function.result {
                results.push(FieldDescriptor {
                    name: "result".to_owned(),
                    value_type: budget.value(resolve, result, 1)?,
                    documentation: None,
                });
            }
            functions.push(FunctionDescriptor {
                id: FunctionId(function.name.clone()),
                name: function.name.clone(),
                asynchronous: function.kind == FunctionKind::AsyncFreestanding,
                parameters,
                results,
                documentation: function.docs.contents.clone(),
                attributes: Default::default(),
            });
        }
        let mut dependencies = resolve
            .interface_direct_deps(*id)
            .map(|dependency| interface_name(resolve, dependency, limits).map(ContractId))
            .collect::<Result<Vec<_>, _>>()?;
        dependencies.sort_by(|a, b| a.0.cmp(&b.0));
        dependencies.dedup();
        contracts.push(ContractDescriptor {
            id: ContractId(name.clone()),
            package_name: format!("{}:{}", package.namespace, package.name),
            semantic_version: version.to_string(),
            interfaces: vec![InterfaceDescriptor {
                id: InterfaceId(name),
                functions,
                documentation: interface.docs.contents.clone(),
                digest: placeholder.clone(),
            }],
            dependencies,
            digest: placeholder.clone(),
        });
    }
    contracts.sort_by(|a, b| a.id.0.cmp(&b.id.0));
    let encoded = encode_contract_metadata(&contracts, ContractMetadataLimits::default())?;
    if encoded.len() > limits.max_summary_bytes {
        return Err(exhausted("authoring-contract-byte-limit"));
    }
    let mut document: serde_json::Value = serde_json::from_slice(&encoded)
        .map_err(|_| invalid("invalid-contract-digest-document"))?;
    for contract in document["contracts"]
        .as_array_mut()
        .ok_or_else(|| invalid("invalid-contract-digest-document"))?
    {
        for interface in contract["interfaces"]
            .as_array_mut()
            .ok_or_else(|| invalid("invalid-contract-digest-document"))?
        {
            interface["digest"] = digest::calculate(interface, limits.max_summary_bytes)?.into();
        }
        contract["digest"] = digest::calculate(contract, limits.max_summary_bytes)?.into();
    }
    let output =
        serde_json::to_vec(&document).map_err(|_| invalid("invalid-contract-digest-document"))?;
    let contracts = decode_contract_metadata(&output, ContractMetadataLimits::default())?;
    validate(resolve, world, &contracts, limits)?;
    Ok(contracts)
}

struct Projection {
    remaining: usize,
    limits: SemanticLimits,
}

impl Projection {
    fn value(
        &mut self,
        resolve: &Resolve,
        value: Type,
        depth: usize,
    ) -> Result<ValueType, PlatformError> {
        if depth > self.limits.max_type_depth {
            return Err(exhausted("contract-type-depth-limit"));
        }
        self.remaining = self
            .remaining
            .checked_sub(1)
            .ok_or_else(|| exhausted("contract-type-node-limit"))?;
        Ok(match value {
            Type::Bool => ValueType::Bool,
            Type::U8 => ValueType::U8,
            Type::U16 => ValueType::U16,
            Type::U32 => ValueType::U32,
            Type::U64 => ValueType::U64,
            Type::S8 => ValueType::S8,
            Type::S16 => ValueType::S16,
            Type::S32 => ValueType::S32,
            Type::S64 => ValueType::S64,
            Type::F32 => ValueType::F32,
            Type::F64 => ValueType::F64,
            Type::Char => ValueType::Char,
            Type::String => ValueType::String,
            Type::Id(id) => {
                let definition = &resolve.types[id];
                match &definition.kind {
                    TypeDefKind::Type(inner) => self.value(resolve, *inner, depth + 1)?,
                    TypeDefKind::Record(_) => ValueType::Record(
                        definition
                            .name
                            .clone()
                            .ok_or_else(|| incompatible("unnamed-contract-type"))?,
                    ),
                    TypeDefKind::Variant(_) | TypeDefKind::Enum(_) => ValueType::Variant(
                        definition
                            .name
                            .clone()
                            .ok_or_else(|| incompatible("unnamed-contract-type"))?,
                    ),
                    TypeDefKind::List(inner) => {
                        ValueType::List(Box::new(self.value(resolve, *inner, depth + 1)?))
                    }
                    TypeDefKind::Option(inner) => {
                        ValueType::Option(Box::new(self.value(resolve, *inner, depth + 1)?))
                    }
                    TypeDefKind::Result(result) => ValueType::Result {
                        ok: result
                            .ok
                            .map(|ty| self.value(resolve, ty, depth + 1).map(Box::new))
                            .transpose()?,
                        error: result
                            .err
                            .map(|ty| self.value(resolve, ty, depth + 1).map(Box::new))
                            .transpose()?,
                    },
                    TypeDefKind::Tuple(tuple) => ValueType::Tuple(
                        tuple
                            .types
                            .iter()
                            .map(|ty| self.value(resolve, *ty, depth + 1))
                            .collect::<Result<_, _>>()?,
                    ),
                    _ => return Err(incompatible("unsupported-contract-value-type")),
                }
            }
            Type::ErrorContext => return Err(incompatible("unsupported-contract-value-type")),
        })
    }
}
