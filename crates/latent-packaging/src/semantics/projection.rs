//! Strict projection onto the existing Phase 1 contract descriptor vocabulary.
//!
//! Full named type shapes are checked by the WIT/component graph comparison.
//! This module preserves supplied documentation, attributes and wire type choices;
//! their existing digests are checked, never repaired or used as semantic proof.

mod digest;
#[cfg(test)]
mod tests;
mod types;

use std::collections::{BTreeMap, BTreeSet};

use latent_artifacts::{encode_contract_metadata, ContractMetadataLimits};
use latent_contracts::{ContractDescriptor, FunctionDescriptor};
use latent_core::PlatformError;
use wit_parser::{Function, FunctionKind, Resolve, WorldId, WorldItem};

use super::{exhausted, incompatible, invalid, SemanticLimits};

pub(super) fn validate(
    resolve: &Resolve,
    world: WorldId,
    contracts: &[ContractDescriptor],
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    limits.validate()?;
    // This preflight bounds all strings/containers and rejects excessive owned
    // type depth before recursive DTO conversion or any digest scratch allocation.
    let defaults = ContractMetadataLimits::default();
    let bytes = encode_contract_metadata(
        contracts,
        ContractMetadataLimits {
            max_document_bytes: limits.max_summary_bytes.min(defaults.max_document_bytes),
            max_nodes: limits.max_type_nodes.min(defaults.max_nodes),
            max_retained_bytes: limits
                .max_summary_bytes
                .saturating_mul(16)
                .min(defaults.max_retained_bytes),
            ..defaults
        },
    )?;
    digest::validate(&bytes)?;
    drop(bytes);

    let exports = &resolve.worlds[world].exports;
    if contracts.len() > limits.max_exports || exports.len() > limits.max_exports {
        return Err(exhausted("contract-export-limit"));
    }
    let mut expected = BTreeMap::new();
    for item in exports.values() {
        let WorldItem::Interface { id, .. } = item else {
            return Err(incompatible("unsupported-contract-world-export"));
        };
        let name = interface_name(resolve, *id, limits)?;
        if expected.insert(name, *id).is_some() {
            return Err(invalid("duplicate-contract-world-export"));
        }
    }
    if contracts.len() != expected.len() {
        return Err(incompatible("contract-export-set-mismatch"));
    }
    let mut seen = BTreeSet::new();
    let mut functions = 0;
    let mut types = types::Budget::new(limits);
    for contract in contracts {
        super::limits::name(&contract.id.0, limits)?;
        if !seen.insert(contract.id.0.as_str()) {
            return Err(invalid("duplicate-contract-metadata"));
        }
        let id = expected
            .get(&contract.id.0)
            .ok_or_else(|| incompatible("contract-export-set-mismatch"))?;
        let interface = &resolve.interfaces[*id];
        let package = &resolve.packages[interface
            .package
            .ok_or_else(|| incompatible("unqualified-contract-interface"))?]
        .name;
        let version = package
            .version
            .as_ref()
            .ok_or_else(|| incompatible("unversioned-contract-interface"))?;
        if contract.package_name != format!("{}:{}", package.namespace, package.name)
            || contract.semantic_version != version.to_string()
            || contract.interfaces.len() != 1
            || contract.interfaces[0].id.0 != contract.id.0
        {
            return Err(incompatible("contract-interface-identity-mismatch"));
        }
        if interface.types.len() > limits.max_type_members
            || contract.dependencies.len() > limits.max_type_members
        {
            return Err(exhausted("contract-dependency-limit"));
        }
        let expected_dependencies = resolve
            .interface_direct_deps(*id)
            .map(|dependency| interface_name(resolve, dependency, limits))
            .collect::<Result<BTreeSet<_>, _>>()?;
        if !contract
            .dependencies
            .iter()
            .map(|value| value.0.as_str())
            .eq(expected_dependencies.iter().map(String::as_str))
        {
            return Err(incompatible("contract-dependency-mismatch"));
        }
        let described = &contract.interfaces[0];
        super::limits::add(
            &mut functions,
            interface.functions.len(),
            limits.max_functions,
        )?;
        if described.functions.len() != interface.functions.len() {
            return Err(incompatible("contract-function-set-mismatch"));
        }
        let mut names = BTreeSet::new();
        for function in &described.functions {
            super::limits::name(&function.name, limits)?;
            if function.id.0 != function.name || !names.insert(function.name.as_str()) {
                return Err(invalid("invalid-contract-function-identity"));
            }
            let actual = interface
                .functions
                .get(&function.name)
                .ok_or_else(|| incompatible("contract-function-set-mismatch"))?;
            validate_function(resolve, function, actual, &mut types, limits)?;
        }
    }
    Ok(())
}

fn interface_name(
    resolve: &Resolve,
    id: wit_parser::InterfaceId,
    limits: SemanticLimits,
) -> Result<String, PlatformError> {
    let interface = &resolve.interfaces[id];
    let package = &resolve.packages[interface
        .package
        .ok_or_else(|| incompatible("unqualified-contract-interface"))?]
    .name;
    let name = interface
        .name
        .as_deref()
        .ok_or_else(|| incompatible("unqualified-contract-interface"))?;
    super::limits::name(name, limits)?;
    super::limits::name(&package.namespace, limits)?;
    super::limits::name(&package.name, limits)?;
    let name = package.interface_id(name);
    super::limits::name(&name, limits)?;
    if package.version.is_none() {
        return Err(incompatible("unversioned-contract-interface"));
    }
    Ok(name)
}

fn validate_function(
    resolve: &Resolve,
    described: &FunctionDescriptor,
    actual: &Function,
    types: &mut types::Budget,
    limits: SemanticLimits,
) -> Result<(), PlatformError> {
    if actual.kind != FunctionKind::Freestanding || described.asynchronous {
        return Err(incompatible("unsupported-contract-function-kind"));
    }
    if actual.name != described.name
        || described.parameters.len() != actual.params.len()
        || described.results.len() != usize::from(actual.result.is_some())
    {
        return Err(incompatible("contract-function-signature-mismatch"));
    }
    if actual.params.len() > limits.max_parameters {
        return Err(exhausted("contract-parameter-limit"));
    }
    for (field, parameter) in described.parameters.iter().zip(&actual.params) {
        super::limits::name(&field.name, limits)?;
        if field.name != parameter.name {
            return Err(incompatible("contract-parameter-name-mismatch"));
        }
        types.compare(resolve, &field.value_type, parameter.ty, 1)?;
    }
    if let Some(result) = actual.result {
        let field = &described.results[0];
        if field.name != "result" {
            return Err(incompatible("contract-result-name-mismatch"));
        }
        types.compare(resolve, &field.value_type, result, 1)?;
    }
    Ok(())
}
