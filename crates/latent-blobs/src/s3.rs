//! Initial S3 profile: HTTPS, explicit static peers, SigV4, versioned bucket,
//! finite staged objects and a private durable inventory. Immediate effects do
//! not imply an application transaction, rollback or exactly-once delivery.
mod config;
mod inventory;
mod provider;
mod signing;
mod xml;
pub use config::{S3Config, S3Limits};
pub use inventory::{S3Inventory, S3PendingUpload, S3Snapshot};
use latent_capabilities::broker::blob::BlobError;
pub use provider::{S3BlobProvider, S3Recovery, S3RecoveryMode};
use sha2::{Digest, Sha256};

pub const S3_BLOB_PROFILE: &str = "s3-versioned-immutable-blobs-v1";
const PART_BYTES: usize = 5 * 1024 * 1024;
const RECORD_BYTES: usize = 16384;
const XML_BYTES: usize = 32768;
type Result<T> = std::result::Result<T, BlobError>;

fn sha(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn hex(value: &str, size: usize) -> bool {
    value.len() == size
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn text(value: &str, maximum: usize) -> bool {
    !value.is_empty() && value.len() <= maximum && !value.chars().any(char::is_control)
}
fn local(error: crate::local::LocalBlobError) -> BlobError {
    use crate::local::LocalBlobError as E;
    match error {
        E::PermissionDenied => BlobError::PermissionDenied,
        E::Corrupt => BlobError::ChecksumMismatch,
        E::Invalid => BlobError::InvalidRange,
        E::Capacity => BlobError::BudgetExhausted,
        E::NotFound => BlobError::NotFound,
        E::Uncertain => BlobError::Uncertain,
        _ => BlobError::Unavailable,
    }
}
fn http(error: latent_capabilities::broker::http::HttpError) -> BlobError {
    use latent_capabilities::broker::http::HttpError as E;
    match error {
        E::PermissionDenied => BlobError::PermissionDenied,
        E::BudgetExhausted => BlobError::BudgetExhausted,
        E::DeadlineExceeded => BlobError::DeadlineExceeded,
        E::Cancelled => BlobError::Cancelled,
        _ => BlobError::Unavailable,
    }
}

fn hex_bytes(bytes: &[u8]) -> String {
    const DIGITS: &[u8] = b"0123456789abcdef";
    let mut value = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        value.push(char::from(DIGITS[usize::from(byte >> 4)]));
        value.push(char::from(DIGITS[usize::from(byte & 15)]));
    }
    value
}
