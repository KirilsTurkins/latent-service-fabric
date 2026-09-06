//! The same bounded metadata representation is admitted on write and read.

use latent_contracts::{ContractDescriptor, ValueType};
use latent_core::{PlatformError, PlatformErrorCode};
use latent_manifest::__serde_json as serde_json;

use super::metadata::{StoredArtifactDescriptor, StoredContractDescriptor, StoredMetadata};
use super::{corrupt, error, resource_exhausted};
use crate::{ArtifactDescriptor, CapsuleArtifact};

// Count the root value as depth one. Even Result/Tuple's extra JSON containers
// leave ample headroom below serde_json's retained recursion protection.
pub(super) const MAX_CONTRACT_TYPE_DEPTH: usize = 32;
pub(super) const MAX_CONTRACT_TYPE_NODES: usize = 16_384;

pub(super) fn encode_metadata(
    artifact: &CapsuleArtifact,
    max_bytes: usize,
) -> Result<Vec<u8>, PlatformError> {
    // Check before recursive conversion, cloning, and serialization.
    validate_contracts(&artifact.contracts)?;
    let stored = StoredMetadata {
        descriptor: StoredArtifactDescriptor::from(&artifact.descriptor),
        contracts: artifact
            .contracts
            .iter()
            .map(StoredContractDescriptor::from)
            .collect(),
    };
    let bytes = serde_json::to_vec(&stored).map_err(|_| {
        error(
            PlatformErrorCode::InvalidArgument,
            "catalog metadata cannot be serialized",
        )
    })?;
    // Read back the exact bytes with the production decoder before staging.
    // A writer must never acknowledge a representation its reader rejects.
    let (descriptor, contracts) = decode_metadata(&bytes, max_bytes)?;
    if descriptor != artifact.descriptor || contracts != artifact.contracts {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "catalog metadata does not round-trip through its bounded codec",
        ));
    }
    Ok(bytes)
}

pub(super) fn decode_metadata(
    bytes: &[u8],
    max_bytes: usize,
) -> Result<(ArtifactDescriptor, Vec<ContractDescriptor>), PlatformError> {
    if bytes.len() > max_bytes {
        return Err(resource_exhausted(
            "catalog metadata exceeds configured byte limit",
        ));
    }
    // Do not disable serde_json's recursion limit. It bounds conversion of
    // persisted input even before the domain-level structural checks below.
    let stored: StoredMetadata =
        serde_json::from_slice(bytes).map_err(|_| corrupt("invalid catalog metadata"))?;
    let contracts: Vec<_> = stored
        .contracts
        .into_iter()
        .map(ContractDescriptor::from)
        .collect();
    validate_contracts(&contracts)?;
    Ok((ArtifactDescriptor::from(stored.descriptor), contracts))
}

fn validate_contracts(contracts: &[ContractDescriptor]) -> Result<(), PlatformError> {
    let mut remaining = MAX_CONTRACT_TYPE_NODES;
    for contract in contracts {
        for interface in &contract.interfaces {
            for function in &interface.functions {
                for field in function.parameters.iter().chain(&function.results) {
                    validate_value_type(&field.value_type, 1, &mut remaining)?;
                }
            }
        }
    }
    Ok(())
}

fn validate_value_type(
    value: &ValueType,
    depth: usize,
    remaining: &mut usize,
) -> Result<(), PlatformError> {
    if depth > MAX_CONTRACT_TYPE_DEPTH {
        return Err(resource_exhausted("contract value-type depth exceeds 32"));
    }
    if *remaining == 0 {
        return Err(resource_exhausted(
            "contract value-type node count exceeds 16384",
        ));
    }
    *remaining -= 1;
    match value {
        ValueType::List(inner)
        | ValueType::Option(inner)
        | ValueType::Future(inner)
        | ValueType::Stream(inner) => validate_value_type(inner, depth + 1, remaining)?,
        ValueType::Result { ok, error } => {
            for inner in ok.iter().chain(error.iter()) {
                validate_value_type(inner, depth + 1, remaining)?;
            }
        }
        ValueType::Tuple(values) => {
            for inner in values {
                validate_value_type(inner, depth + 1, remaining)?;
            }
        }
        _ => {}
    }
    Ok(())
}
