//! Versioned upload envelope over the catalog's existing typed contract representation.

mod bounded;
mod structure;
#[cfg(test)]
mod tests;

use std::io::{self, Write};

use latent_contracts::ContractDescriptor;
use latent_core::{PlatformError, PlatformErrorCode};
use latent_manifest::{
    __serde::{Deserialize, Serialize},
    __serde_json as serde_json,
};

use super::{error, metadata::StoredContractDescriptor};

/// Independent bounds for untrusted contract metadata uploads.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ContractMetadataLimits {
    pub max_document_bytes: usize,
    /// JSON depth, including the version envelope and descriptor containers.
    /// At most 112; the persisted codec's separate value-type depth limit is 32.
    pub max_depth: usize,
    /// Counts every JSON value and object key, including empty containers.
    pub max_nodes: usize,
    pub max_string_bytes: usize,
    /// Conservative allocation charge for parser scratch, JSON and typed conversion.
    pub max_retained_bytes: usize,
}

impl Default for ContractMetadataLimits {
    fn default() -> Self {
        Self {
            max_document_bytes: 4 * 1024 * 1024,
            max_depth: 112,
            max_nodes: 65_536,
            max_string_bytes: 256 * 1024,
            max_retained_bytes: 16 * 1024 * 1024,
        }
    }
}

#[derive(Serialize, Deserialize)]
#[serde(crate = "latent_manifest::__serde", deny_unknown_fields)]
struct Document {
    format_version: u32,
    contracts: Vec<StoredContractDescriptor>,
}

/// Decodes format version 1 without exposing persistence DTOs or filesystem locators.
/// Unknown fields, duplicate keys and unsupported versions are rejected.
pub fn decode_contract_metadata(
    bytes: &[u8],
    limits: ContractMetadataLimits,
) -> Result<Vec<ContractDescriptor>, PlatformError> {
    validate_limits(limits)?;
    if bytes.len() > limits.max_document_bytes {
        return Err(exhausted("contract-metadata-byte-limit"));
    }
    let value = bounded::parse(bytes, limits)?;
    structure::validate_json(&value)?;
    let document: Document = serde_json::from_value(value).map_err(|_| invalid())?;
    if document.format_version != 1 {
        return Err(invalid());
    }
    let contracts: Vec<_> = document
        .contracts
        .into_iter()
        .map(ContractDescriptor::from)
        .collect();
    super::metadata_codec::validate_contracts(&contracts)
        .map_err(|_| exhausted("contract-metadata-type-limit"))?;
    Ok(contracts)
}

/// Encodes the same versioned schema. A bounded preflight precedes storage DTO cloning;
/// the writer rejects growth before allocating beyond the document limit.
pub fn encode_contract_metadata(
    contracts: &[ContractDescriptor],
    limits: ContractMetadataLimits,
) -> Result<Vec<u8>, PlatformError> {
    validate_limits(limits)?;
    structure::validate_owned(contracts, limits)?;
    super::metadata_codec::validate_contracts(contracts)
        .map_err(|_| exhausted("contract-metadata-type-limit"))?;
    let document = Document {
        format_version: 1,
        contracts: contracts
            .iter()
            .map(StoredContractDescriptor::from)
            .collect(),
    };
    let mut output = LimitedWriter {
        bytes: Vec::new(),
        maximum: limits.max_document_bytes,
    };
    serde_json::to_writer(&mut output, &document)
        .map_err(|_| exhausted("contract-metadata-byte-limit"))?;
    drop(document);
    // Ensures both helpers accept exactly the same configured structural envelope.
    let decoded = decode_contract_metadata(&output.bytes, limits)?;
    if decoded != contracts {
        return Err(invalid());
    }
    Ok(output.bytes)
}

fn validate_limits(limits: ContractMetadataLimits) -> Result<(), PlatformError> {
    if limits.max_document_bytes == 0
        || limits.max_depth == 0
        || limits.max_depth > 112
        || limits.max_nodes == 0
        || limits.max_string_bytes == 0
        || limits.max_retained_bytes == 0
    {
        return Err(error(
            PlatformErrorCode::InvalidArgument,
            "invalid-contract-metadata-limits",
        ));
    }
    Ok(())
}

struct LimitedWriter {
    bytes: Vec<u8>,
    maximum: usize,
}
impl Write for LimitedWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let next = self
            .bytes
            .len()
            .checked_add(bytes.len())
            .filter(|next| *next <= self.maximum)
            .ok_or_else(|| io::Error::other("bounded contract metadata"))?;
        if next > self.bytes.capacity() {
            // Geometric growth is capped, so both len and retained capacity fit.
            let capacity = next
                .max(self.bytes.capacity().saturating_mul(2))
                .min(self.maximum);
            self.bytes
                .try_reserve_exact(capacity - self.bytes.len())
                .map_err(io::Error::other)?;
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

fn invalid() -> PlatformError {
    error(
        PlatformErrorCode::InvalidArgument,
        "invalid-contract-metadata",
    )
}
fn exhausted(reason: &str) -> PlatformError {
    error(PlatformErrorCode::ResourceExhausted, reason)
}
