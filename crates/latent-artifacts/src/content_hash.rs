use std::fmt::Write as _;

use latent_core::ReleaseDigest;
use sha2::{Digest, Sha256};

pub(super) fn release_digest(bytes: &[u8]) -> ReleaseDigest {
    format_digest(Sha256::digest(bytes).into())
}

pub(crate) fn format_digest(hash: [u8; 32]) -> ReleaseDigest {
    let mut value = String::with_capacity(71);
    value.push_str("sha256:");
    for byte in hash {
        write!(&mut value, "{byte:02x}").expect("writing to String cannot fail");
    }
    ReleaseDigest(value)
}

#[cfg(test)]
mod tests;
