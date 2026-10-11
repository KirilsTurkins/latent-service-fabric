//! Actual owned capacities, with conservative B-tree allocation overhead.
use std::mem::{size_of, size_of_val};

use latent_core::Metadata;

use super::SelectedTransactionAsset;
use crate::ValueType;

#[expect(
    clippy::too_many_lines,
    reason = "One complete charge visits every actual owned metadata field"
)]
pub(super) fn bytes(value: &SelectedTransactionAsset) -> usize {
    let mut used = size_of_val(value).saturating_add(128);
    let descriptor = value.metadata.descriptor();
    used = used
        .saturating_add(descriptor.reference.0.capacity())
        .saturating_add(descriptor.release_digest.0.capacity())
        .saturating_add(descriptor.media_type.capacity())
        .saturating_add(value.metadata.verified_digest().0.capacity())
        .saturating_add(
            descriptor
                .publisher
                .as_ref()
                .map_or(0, |id| id.0.capacity()),
        )
        .saturating_add(vector(&descriptor.layers))
        .saturating_add(map(&descriptor.annotations));
    for layer in &descriptor.layers {
        used = used
            .saturating_add(layer.media_type.capacity())
            .saturating_add(layer.digest.capacity())
            .saturating_add(map(&layer.annotations));
    }
    let manifest = value.metadata.manifest();
    used = used
        .saturating_add(manifest.api_version.capacity())
        .saturating_add(manifest.metadata.name.capacity())
        .saturating_add(
            manifest
                .metadata
                .tenant
                .as_ref()
                .map_or(0, |id| id.0.capacity()),
        )
        .saturating_add(optional(manifest.metadata.namespace.as_ref()))
        .saturating_add(map(&manifest.metadata.labels))
        .saturating_add(map(&manifest.metadata.annotations))
        .saturating_add(manifest.semantic_version.capacity())
        .saturating_add(manifest.component_digest.0.capacity())
        .saturating_add(manifest.world.0.capacity())
        .saturating_add(manifest.minimum_fabric_version.capacity())
        .saturating_add(manifest.runtime_requirements.retained_bytes())
        .saturating_add(vector(&manifest.exports))
        .saturating_add(vector(&manifest.imports));
    for export in &manifest.exports {
        used = used.saturating_add(export.contract.0.capacity());
    }
    for import in &manifest.imports {
        used = used.saturating_add(import.contract.0.capacity());
    }
    used = used.saturating_add(
        value
            .metadata
            .contracts_capacity()
            .saturating_mul(size_of::<crate::ContractDescriptor>()),
    );
    for contract in value.metadata.contracts() {
        used = used
            .saturating_add(contract.id.0.capacity())
            .saturating_add(contract.package_name.capacity())
            .saturating_add(contract.semantic_version.capacity())
            .saturating_add(contract.digest.capacity())
            .saturating_add(vector(&contract.interfaces))
            .saturating_add(vector(&contract.dependencies));
        for dependency in &contract.dependencies {
            used = used.saturating_add(dependency.0.capacity());
        }
        for interface in &contract.interfaces {
            used = used
                .saturating_add(interface.id.0.capacity())
                .saturating_add(interface.digest.capacity())
                .saturating_add(optional(interface.documentation.as_ref()))
                .saturating_add(vector(&interface.functions));
            for function in &interface.functions {
                used = used
                    .saturating_add(function.id.0.capacity())
                    .saturating_add(function.name.capacity())
                    .saturating_add(optional(function.documentation.as_ref()))
                    .saturating_add(map(&function.attributes))
                    .saturating_add(vector(&function.parameters))
                    .saturating_add(vector(&function.results));
                for field in function.parameters.iter().chain(&function.results) {
                    used = used
                        .saturating_add(field.name.capacity())
                        .saturating_add(optional(field.documentation.as_ref()))
                        .saturating_add(value_type(&field.value_type));
                }
            }
        }
    }
    let declaration = &value.declaration;
    for text in [
        &declaration.api_version,
        &declaration.kind,
        &declaration.capsule,
        &declaration.deployment,
        &declaration.binding,
        &declaration.profile,
        &declaration.host_abi_digest,
        &declaration.namespace,
        &declaration.state_schema,
    ] {
        used = used.saturating_add(text.capacity());
    }
    used = used.saturating_add(vector(&declaration.operations));
    for operation in &declaration.operations {
        used = used
            .saturating_add(operation.operation.capacity())
            .saturating_add(operation.input_format.capacity())
            .saturating_add(operation.result_format.capacity());
    }
    used.saturating_add(value.publication.retained_bytes())
        .saturating_add(71) // ArtifactBlobDigest owns one validated digest string.
}

#[allow(
    clippy::ptr_arg,
    reason = "Charge the actual Vec capacity, including unused collection slots"
)]
fn vector<T>(value: &Vec<T>) -> usize {
    value.capacity().saturating_mul(size_of::<T>())
}
fn optional(value: Option<&String>) -> usize {
    value.map_or(0, String::capacity)
}
fn map(value: &Metadata) -> usize {
    let root = if value.is_empty() { 0 } else { 1024 };
    value.iter().fold(root, |used, (key, entry)| {
        used.saturating_add(256)
            .saturating_add(key.capacity())
            .saturating_add(entry.capacity())
    })
}
fn value_type(value: &ValueType) -> usize {
    match value {
        ValueType::List(inner)
        | ValueType::Option(inner)
        | ValueType::Future(inner)
        | ValueType::Stream(inner) => size_of::<ValueType>().saturating_add(value_type(inner)),
        ValueType::Result { ok, error } => {
            ok.iter().chain(error.iter()).fold(0_usize, |used, inner| {
                used.saturating_add(size_of::<ValueType>())
                    .saturating_add(value_type(inner))
            })
        }
        ValueType::Tuple(values) => values.iter().fold(vector(values), |used, inner| {
            used.saturating_add(value_type(inner))
        }),
        ValueType::Record(name) | ValueType::Variant(name) | ValueType::Resource(name) => {
            name.capacity()
        }
        _ => 0,
    }
}
