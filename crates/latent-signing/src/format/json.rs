use crate::{SignatureError, SignatureFailure, SignatureResult};
use latent_artifacts::package::{validate_package_json, PackageLimits};
use latent_core::{PlatformError, PlatformErrorCode};
use serde::Serialize;
use std::io::{self, Write};

pub(crate) fn map_package_error(
    error: &PlatformError,
    fallback: SignatureFailure,
) -> SignatureError {
    match error.code {
        PlatformErrorCode::ResourceExhausted => SignatureFailure::ResourceLimit,
        PlatformErrorCode::CorruptArtifact => SignatureFailure::IntegrityMismatch,
        _ => fallback,
    }
    .into()
}

/// Duplicate-safe lexical/structural preflight before typed deserialization.
/// These are small signature documents, not the larger policy JSON profile.
pub(crate) fn preflight(bytes: &[u8], maximum: usize) -> SignatureResult<()> {
    if maximum == 0 || maximum > 4096 {
        return Err(SignatureFailure::InvalidLimits.into());
    }
    validate_package_json(
        bytes,
        PackageLimits {
            max_document_bytes: maximum,
            max_depth: 8,
            max_nodes: 256,
            max_layers: 1,
            max_annotations: 32,
            ..PackageLimits::default()
        },
    )
    .map_err(|error| map_package_error(&error, SignatureFailure::MalformedEnvelope))
}

/// Callers validate owned fields before serialization. The writer additionally
/// stops growth at the configured document bound, including JSON escaping.
pub(crate) fn encode_json<T: Serialize>(value: &T, maximum: usize) -> SignatureResult<Vec<u8>> {
    if maximum == 0 || maximum > 4096 {
        return Err(SignatureFailure::InvalidLimits.into());
    }
    let mut writer = LimitedWriter {
        bytes: Vec::new(),
        maximum,
    };
    serde_json::to_writer(&mut writer, value).map_err(|_| SignatureFailure::ResourceLimit)?;
    preflight(&writer.bytes, maximum)?;
    Ok(writer.bytes)
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
            .ok_or_else(|| io::Error::other("signature document bound"))?;
        if next > self.bytes.capacity() {
            self.bytes
                .try_reserve_exact(next - self.bytes.len())
                .map_err(|_| io::Error::other("signature allocation bound"))?;
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
