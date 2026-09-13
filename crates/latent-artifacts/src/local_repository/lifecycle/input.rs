//! Allocation-free envelope checks before local DTO cloning or request hashing.
//!
//! This is a conservative input budget, not package validation or an index/CAS
//! check. Syntax/model-encoding failures occur before a durable operation exists.

use std::mem::size_of;

use latent_core::{Metadata, PlatformError};

use crate::local_repository::{
    metadata_codec, resource_exhausted, DirectoryArtifactRepositoryConfig,
};
use crate::{
    CapsuleArtifact, ContractDescriptor, ContractMetadataLimits, FieldDescriptor, ValueType,
};

pub(in crate::local_repository) fn check(
    artifact: &CapsuleArtifact,
    config: DirectoryArtifactRepositoryConfig,
) -> Result<(), PlatformError> {
    if artifact.component_bytes.capacity() > config.max_component_bytes {
        return Err(limit());
    }
    let mut budget = Budget::new(config)?;
    budget.charge(size_of::<CapsuleArtifact>())?;
    let before = budget.remaining;
    descriptor(&mut budget, artifact)?;
    if before - budget.remaining
        > config
            .max_descriptor_bytes
            .checked_mul(4)
            .ok_or_else(limit)?
    {
        return Err(limit());
    }
    manifest(&mut budget, artifact)?;
    budget.vector(&artifact.contracts)?;
    for contract in &artifact.contracts {
        budget.contract(contract)?;
    }
    Ok(())
}

fn descriptor(budget: &mut Budget, artifact: &CapsuleArtifact) -> Result<(), PlatformError> {
    let value = &artifact.descriptor;
    for text in [
        &value.reference.0,
        &value.release_digest.0,
        &value.media_type,
    ] {
        budget.string(text)?;
    }
    budget.optional(value.publisher.as_ref().map(|value| &value.0))?;
    budget.map(&value.annotations)?;
    budget.vector(&value.layers)?;
    for layer in &value.layers {
        budget.node()?;
        budget.string(&layer.media_type)?;
        budget.string(&layer.digest)?;
        budget.map(&layer.annotations)?;
    }
    Ok(())
}

fn manifest(budget: &mut Budget, artifact: &CapsuleArtifact) -> Result<(), PlatformError> {
    let value = &artifact.manifest;
    for text in [
        &value.api_version,
        &value.metadata.name,
        &value.semantic_version,
        &value.component_digest.0,
        &value.world.0,
        &value.minimum_fabric_version,
    ] {
        budget.string(text)?;
    }
    budget.optional(value.metadata.tenant.as_ref().map(|value| &value.0))?;
    budget.optional(value.metadata.namespace.as_ref())?;
    budget.map(&value.metadata.labels)?;
    budget.map(&value.metadata.annotations)?;
    budget.vector(&value.exports)?;
    for export in &value.exports {
        budget.string(&export.contract.0)?;
    }
    budget.vector(&value.imports)?;
    for import in &value.imports {
        budget.string(&import.contract.0)?;
    }
    // This closed profile independently checks its tiny vector/string capacity
    // ceilings before parsing versions or retaining any cloned requirements.
    value.runtime_requirements.validate()?;
    budget.charge(value.runtime_requirements.retained_bytes())
}

struct Budget {
    remaining: usize,
    nodes: usize,
    types: usize,
    maximum_string: usize,
}
impl Budget {
    fn new(config: DirectoryArtifactRepositoryConfig) -> Result<Self, PlatformError> {
        let standard = ContractMetadataLimits::default();
        Ok(Self {
            remaining: config
                .max_metadata_bytes
                .checked_mul(4)
                .ok_or_else(limit)?
                .min(standard.max_retained_bytes),
            nodes: standard.max_nodes,
            types: metadata_codec::MAX_CONTRACT_TYPE_NODES,
            // Trusted-local catalog metadata has its own document limit; the
            // independent RPC contract-upload string ceiling does not apply.
            maximum_string: config.max_metadata_bytes,
        })
    }
    fn charge(&mut self, bytes: usize) -> Result<(), PlatformError> {
        self.remaining = self.remaining.checked_sub(bytes).ok_or_else(limit)?;
        Ok(())
    }
    fn node(&mut self) -> Result<(), PlatformError> {
        self.nodes = self.nodes.checked_sub(1).ok_or_else(limit)?;
        // Covers bounded DTO/JSON fixed fields and per-container bookkeeping.
        self.charge(64)
    }
    fn string(&mut self, value: &String) -> Result<(), PlatformError> {
        self.node()?;
        if value.capacity() > self.maximum_string {
            return Err(limit());
        }
        // Bound the supplied owner and complete scan before inspecting bytes.
        // JSON preserves UTF-8, escaping only quotes, backslashes and controls.
        // The fixed node charge already covers surrounding quotes and fields.
        self.charge(
            value
                .capacity()
                .checked_add(value.len())
                .ok_or_else(limit)?,
        )?;
        for byte in value.bytes() {
            let extra = match byte {
                b'"' | b'\\' | b'\x08' | b'\t' | b'\n' | b'\x0c' | b'\r' => 1,
                0..=0x1f => 5,
                _ => continue,
            };
            self.charge(extra)?;
        }
        Ok(())
    }
    fn optional(&mut self, value: Option<&String>) -> Result<(), PlatformError> {
        match value {
            Some(value) => self.string(value),
            None => self.node(),
        }
    }
    fn vector<T>(&mut self, values: &Vec<T>) -> Result<(), PlatformError> {
        self.node()?;
        if values.len() > self.nodes {
            return Err(limit());
        }
        self.charge(
            values
                .capacity()
                .checked_mul(size_of::<T>())
                .ok_or_else(limit)?,
        )
    }
    fn map(&mut self, value: &Metadata) -> Result<(), PlatformError> {
        self.node()?;
        if value.len() > self.nodes / 2 {
            return Err(limit());
        }
        self.charge(value.len().checked_mul(128).ok_or_else(limit)?)?;
        for (key, value) in value {
            self.string(key)?;
            self.string(value)?;
        }
        Ok(())
    }
    fn contract(&mut self, value: &ContractDescriptor) -> Result<(), PlatformError> {
        self.node()?;
        for text in [
            &value.id.0,
            &value.package_name,
            &value.semantic_version,
            &value.digest,
        ] {
            self.string(text)?;
        }
        self.vector(&value.dependencies)?;
        for dependency in &value.dependencies {
            self.string(&dependency.0)?;
        }
        self.vector(&value.interfaces)?;
        for interface in &value.interfaces {
            self.node()?;
            self.string(&interface.id.0)?;
            self.string(&interface.digest)?;
            self.optional(interface.documentation.as_ref())?;
            self.vector(&interface.functions)?;
            for function in &interface.functions {
                self.node()?;
                self.string(&function.id.0)?;
                self.string(&function.name)?;
                self.optional(function.documentation.as_ref())?;
                self.map(&function.attributes)?;
                for fields in [&function.parameters, &function.results] {
                    self.vector(fields)?;
                    for field in fields {
                        self.field(field)?;
                    }
                }
            }
        }
        Ok(())
    }
    fn field(&mut self, value: &FieldDescriptor) -> Result<(), PlatformError> {
        self.node()?;
        self.string(&value.name)?;
        self.optional(value.documentation.as_ref())?;
        self.value_type(&value.value_type, 1)
    }
    fn value_type(&mut self, value: &ValueType, depth: usize) -> Result<(), PlatformError> {
        if depth > metadata_codec::MAX_CONTRACT_TYPE_DEPTH {
            return Err(limit());
        }
        self.types = self.types.checked_sub(1).ok_or_else(limit)?;
        self.node()?;
        match value {
            ValueType::List(inner)
            | ValueType::Option(inner)
            | ValueType::Future(inner)
            | ValueType::Stream(inner) => {
                self.charge(size_of::<ValueType>())?;
                self.value_type(inner, depth + 1)
            }
            ValueType::Result { ok, error } => {
                for value in ok.iter().chain(error.iter()) {
                    self.charge(size_of::<ValueType>())?;
                    self.value_type(value, depth + 1)?;
                }
                Ok(())
            }
            ValueType::Tuple(fields) => {
                self.vector(fields)?;
                for field in fields {
                    self.value_type(field, depth + 1)?;
                }
                Ok(())
            }
            ValueType::Record(name) | ValueType::Variant(name) | ValueType::Resource(name) => {
                self.string(name)
            }
            _ => Ok(()),
        }
    }
}

fn limit() -> PlatformError {
    resource_exhausted("local-publication-input-limit")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn budget() -> Budget {
        Budget {
            remaining: 16 * 1024 * 1024,
            nodes: 65_536,
            types: metadata_codec::MAX_CONTRACT_TYPE_NODES,
            maximum_string: 256 * 1024,
        }
    }

    #[test]
    fn spare_capacity_and_actual_json_escaping_are_bounded_before_clone() {
        let value = String::with_capacity(33);
        let mut bounds = budget();
        bounds.maximum_string = 32;
        assert!(bounds.string(&value).is_err());
        let value = String::from("\0");
        let mut bounds = budget();
        bounds.remaining = 71;
        bounds.string(&value).unwrap();
        assert_eq!(bounds.remaining, 0);
        let mut bounds = budget();
        bounds.remaining = 70;
        assert!(bounds.string(&value).is_err());
        let mut bounds = budget();
        bounds.remaining = 100;
        assert!(bounds
            .vector(&Vec::<ValueType>::with_capacity(100))
            .is_err());
        let mixed = String::from("\0\u{0001}\u{0008}\t\n\u{000c}\r\"\\éA");
        let encoded = serde_json::to_vec(&mixed).unwrap();
        let mut bounds = budget();
        bounds.remaining = 64 + mixed.capacity() + encoded.len() - 2;
        bounds.string(&mixed).unwrap();
        assert_eq!(bounds.remaining, 0);
    }

    #[test]
    fn trusted_local_documentation_uses_catalog_limit_and_actual_escaped_size() {
        const MIB: usize = 1024 * 1024;
        let config = DirectoryArtifactRepositoryConfig {
            max_metadata_bytes: 4 * MIB,
            ..DirectoryArtifactRepositoryConfig::default()
        };
        let mut contract = crate::local_repository::tests::contract_fixture();
        contract.interfaces[0].documentation = Some("d".repeat(3 * MIB));
        let mut bounds = Budget::new(config).unwrap();
        bounds.contract(&contract).unwrap();
        assert!(bounds.remaining > 9 * MIB);

        contract.interfaces[0].documentation = Some("d".repeat(4 * MIB + 1));
        assert!(Budget::new(config).unwrap().contract(&contract).is_err());
        contract.interfaces[0].documentation = Some(String::with_capacity(4 * MIB + 1));
        assert!(Budget::new(config).unwrap().contract(&contract).is_err());

        // Control bytes consume six JSON bytes each, exhausting the existing
        // 16 MiB aggregate even though the owned string fits the document cap.
        contract.interfaces[0].documentation = Some("\0".repeat(3 * MIB));
        assert!(Budget::new(config).unwrap().contract(&contract).is_err());
    }

    #[test]
    fn empty_structural_nodes_and_recursive_type_expansion_have_separate_limits() {
        let mut bounds = budget();
        bounds.nodes = 2;
        bounds.vector(&Vec::<ValueType>::new()).unwrap();
        bounds.vector(&Vec::<ValueType>::new()).unwrap();
        assert!(bounds.vector(&Vec::<ValueType>::new()).is_err());
        let mut ty = ValueType::U8;
        for _ in 1..metadata_codec::MAX_CONTRACT_TYPE_DEPTH {
            ty = ValueType::Option(Box::new(ty));
        }
        budget().value_type(&ty, 1).unwrap();
        assert!(budget()
            .value_type(&ValueType::Option(Box::new(ty)), 1)
            .is_err());
        let mut bounds = budget();
        bounds.types = 2;
        assert!(bounds
            .value_type(&ValueType::Tuple(vec![ValueType::U8, ValueType::Bool]), 1)
            .is_err());
    }
}
