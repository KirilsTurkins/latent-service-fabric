//! WIT-derived descriptors; reuse the checked codec and exact digest algorithm.
use latent_artifacts::{
    decode_contract_metadata, encode_contract_metadata, ContractMetadataLimits,
};
use latent_contracts::{
    ContractDescriptor, FieldDescriptor, FunctionDescriptor, InterfaceDescriptor, ValueType,
};
use latent_core::{ContractId, FunctionId, InterfaceId, PlatformError};
use serde_json::Value;
use wit_parser::{FunctionKind, Resolve, Type, TypeDefKind, WorldId, WorldItem};

use super::{digest, exhausted, incompatible, interface_name, invalid, validate, SemanticLimits};

pub(crate) fn generate(
    resolve: &Resolve,
    world: WorldId,
    limits: SemanticLimits,
) -> Result<Vec<ContractDescriptor>, PlatformError> {
    limits.validate()?;
    let exports = &resolve.worlds[world].exports;
    if exports.is_empty() || exports.len() > limits.max_exports {
        return Err(incompatible(
            "authoring-requires-callable-interface-exports",
        ));
    }
    let mut types = Types {
        remaining: limits.max_type_nodes,
        limits,
    };
    let mut contracts = Vec::new();
    let mut function_count = 0;
    for item in exports.values() {
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
        if interface.functions.is_empty() {
            return Err(incompatible(
                "authoring-requires-callable-interface-exports",
            ));
        }
        super::super::limits::add(
            &mut function_count,
            interface.functions.len(),
            limits.max_functions,
        )?;
        types.members(interface.types.len())?;
        for id in interface.types.values() {
            types.project(resolve, Type::Id(*id), 1)?;
        }
        let mut functions = Vec::new();
        for function in interface.functions.values() {
            if !matches!(
                function.kind,
                FunctionKind::Freestanding | FunctionKind::AsyncFreestanding
            ) {
                return Err(incompatible("unsupported-contract-function-kind"));
            }
            if function.params.len() > limits.max_parameters {
                return Err(exhausted("contract-parameter-limit"));
            }
            let mut parameters = Vec::new();
            for parameter in &function.params {
                parameters.push(FieldDescriptor {
                    name: parameter.name.clone(),
                    value_type: types.project(resolve, parameter.ty, 1)?,
                    documentation: None,
                });
            }
            let results = function
                .result
                .map(|result| {
                    Ok::<_, PlatformError>(FieldDescriptor {
                        name: "result".to_owned(),
                        value_type: types.project(resolve, result, 1)?,
                        documentation: None,
                    })
                })
                .transpose()?
                .into_iter()
                .collect();
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
        dependencies.sort_by(|left, right| left.0.cmp(&right.0));
        let placeholder = format!("sha256:{}", "0".repeat(64));
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
            digest: placeholder,
        });
    }
    contracts.sort_by(|left, right| left.id.0.cmp(&right.id.0));
    let codec = ContractMetadataLimits::default();
    let bytes = encode_contract_metadata(&contracts, codec)?;
    let mut document: Value =
        serde_json::from_slice(&bytes).map_err(|_| invalid("invalid-contract-digest-document"))?;
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
    let bytes =
        serde_json::to_vec(&document).map_err(|_| invalid("invalid-contract-digest-document"))?;
    let contracts = decode_contract_metadata(&bytes, codec)?;
    validate(resolve, world, &contracts, limits)?;
    Ok(contracts)
}

struct Types {
    remaining: usize,
    limits: SemanticLimits,
}
impl Types {
    fn project(
        &mut self,
        resolve: &Resolve,
        ty: Type,
        depth: usize,
    ) -> Result<ValueType, PlatformError> {
        if depth > self.limits.max_type_depth {
            return Err(exhausted("contract-type-depth-limit"));
        }
        self.remaining = self
            .remaining
            .checked_sub(1)
            .ok_or_else(|| exhausted("contract-type-node-limit"))?;
        Ok(match ty {
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
            Type::ErrorContext => return Err(incompatible("unsupported-contract-value-type")),
            Type::Id(id) => {
                let definition = &resolve.types[id];
                let named = || {
                    definition
                        .name
                        .clone()
                        .ok_or_else(|| incompatible("unnamed-contract-value-type"))
                };
                match &definition.kind {
                    TypeDefKind::Type(inner) => self.project(resolve, *inner, depth + 1)?,
                    TypeDefKind::List(inner) => {
                        ValueType::List(Box::new(self.project(resolve, *inner, depth + 1)?))
                    }
                    TypeDefKind::Option(inner) => {
                        ValueType::Option(Box::new(self.project(resolve, *inner, depth + 1)?))
                    }
                    TypeDefKind::Tuple(tuple) => {
                        self.members(tuple.types.len())?;
                        ValueType::Tuple(
                            tuple
                                .types
                                .iter()
                                .map(|field| self.project(resolve, *field, depth + 1))
                                .collect::<Result<_, _>>()?,
                        )
                    }
                    TypeDefKind::Result(result) => ValueType::Result {
                        ok: result
                            .ok
                            .map(|inner| self.project(resolve, inner, depth + 1).map(Box::new))
                            .transpose()?,
                        error: result
                            .err
                            .map(|inner| self.project(resolve, inner, depth + 1).map(Box::new))
                            .transpose()?,
                    },
                    TypeDefKind::Record(record) => {
                        self.members(record.fields.len())?;
                        for field in &record.fields {
                            self.project(resolve, field.ty, depth + 1)?;
                        }
                        ValueType::Record(named()?)
                    }
                    TypeDefKind::Variant(variant) => {
                        self.members(variant.cases.len())?;
                        for case in &variant.cases {
                            if let Some(inner) = case.ty {
                                self.project(resolve, inner, depth + 1)?;
                            }
                        }
                        ValueType::Variant(named()?)
                    }
                    TypeDefKind::Enum(enumeration) => {
                        self.members(enumeration.cases.len())?;
                        ValueType::Variant(named()?)
                    }
                    TypeDefKind::Resource
                    | TypeDefKind::Handle(_)
                    | TypeDefKind::Flags(_)
                    | TypeDefKind::Map(_, _)
                    | TypeDefKind::FixedLengthList(_, _)
                    | TypeDefKind::Future(_)
                    | TypeDefKind::Stream(_)
                    | TypeDefKind::Unknown => {
                        return Err(incompatible("unsupported-contract-value-type"));
                    }
                }
            }
        })
    }

    fn members(&self, count: usize) -> Result<(), PlatformError> {
        if count > self.limits.max_type_members {
            return Err(exhausted("contract-type-member-limit"));
        }
        Ok(())
    }
}
