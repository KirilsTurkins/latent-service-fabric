use crate::{SignatureFailure, SignatureResult};
use latent_artifacts::package::{validate_package_json, PackageLimits};
use latent_core::PlatformErrorCode;
use serde::{de::DeserializeOwned, Serialize};
use std::io::{self, Write};

pub(super) fn decode<T: DeserializeOwned>(
    bytes: &[u8],
    maximum: usize,
    failure: SignatureFailure,
) -> SignatureResult<T> {
    validate_package_json(
        bytes,
        PackageLimits {
            max_document_bytes: maximum,
            ..PackageLimits::default()
        },
    )
    .map_err(|error| match error.code {
        PlatformErrorCode::ResourceExhausted => SignatureFailure::ResourceLimit,
        _ => failure,
    })?;
    serde_json::from_slice(bytes).map_err(|_| failure.into())
}

pub(super) fn encode<T: Serialize>(value: &T, maximum: usize) -> SignatureResult<Vec<u8>> {
    let mut writer = LimitedWriter {
        bytes: Vec::new(),
        maximum,
    };
    serde_json::to_writer(&mut writer, value).map_err(|_| SignatureFailure::ResourceLimit)?;
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
            .filter(|n| *n <= self.maximum)
            .ok_or_else(|| io::Error::other("signature-policy-limit"))?;
        if next > self.bytes.capacity() {
            self.bytes
                .try_reserve_exact(next - self.bytes.len())
                .map_err(io::Error::other)?;
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
