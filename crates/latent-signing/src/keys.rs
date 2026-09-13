//! Host-only private-key generation and bounded `PKCS8v2` importing.

use std::fmt;

use ed25519::pkcs8::{EncodePrivateKey, PrivateKeyInfoRef};
use ed25519_dalek::SigningKey;
use zeroize::Zeroizing;

use crate::{crypto::validate_public_key, SignatureFailure, SignatureResult};

const MAX_PKCS8_BYTES: usize = 4096;

/// Generated host key material, held only in zeroizing memory.
///
/// The caller controls any later persistence. This type does not write files or
/// disclose private bytes through diagnostics.
pub struct GeneratedSigningKey {
    pkcs8: Zeroizing<Vec<u8>>,
    public_key: [u8; 32],
}

impl GeneratedSigningKey {
    /// Return the public identity to configure as an approved publisher key.
    #[must_use]
    pub const fn public_key(&self) -> &[u8; 32] {
        &self.public_key
    }

    /// Transfer the zeroizing `PKCS8v2` buffer to host-controlled provisioning.
    #[must_use]
    pub fn into_pkcs8(self) -> Zeroizing<Vec<u8>> {
        self.pkcs8
    }
}

impl fmt::Debug for GeneratedSigningKey {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("GeneratedSigningKey { private_key: [REDACTED] }")
    }
}

/// Generate an Ed25519 key using the operating system's cryptographic RNG.
///
/// Allocation is bounded, but the operating system may wait for entropy during
/// early boot. Call this host provisioning API outside invocation processing.
/// Secret buffers and the signing key zeroize on drop; this does not promise
/// erasure of every compiler, operating-system, or hardware copy.
///
/// # Errors
/// Returns a bounded failure if entropy acquisition or key encoding fails.
pub fn generate_signing_key() -> SignatureResult<GeneratedSigningKey> {
    let mut seed = Zeroizing::new([0u8; 32]);
    getrandom::fill(&mut seed[..]).map_err(|_| SignatureFailure::Internal)?;
    let signing_key = SigningKey::from_bytes(&seed);
    let public_key = signing_key.verifying_key().to_bytes();
    validate_public_key(&public_key)?;
    // Dalek includes the derived public key; the upstream PKCS8 encoder selects
    // version 2 when that field is present. SecretDocument also zeroizes on drop.
    let document = signing_key
        .to_pkcs8_der()
        .map_err(|_| SignatureFailure::Internal)?;
    if document.as_bytes().len() > MAX_PKCS8_BYTES {
        return Err(SignatureFailure::Internal.into());
    }
    Ok(GeneratedSigningKey {
        pkcs8: Zeroizing::new(document.as_bytes().to_vec()),
        public_key,
    })
}

pub(crate) fn import_key(
    pkcs8: Zeroizing<Vec<u8>>,
    approved_public_key: &[u8; 32],
) -> SignatureResult<SigningKey> {
    if pkcs8.len() > MAX_PKCS8_BYTES {
        return Err(SignatureFailure::ResourceLimit.into());
    }
    validate_public_key(approved_public_key)?;
    let info =
        PrivateKeyInfoRef::try_from(pkcs8.as_slice()).map_err(|_| SignatureFailure::InvalidKey)?;
    // The upstream DER parser validates version/public-key consistency. Requiring
    // this field therefore requires PKCS8v2. Also require byte alignment: the
    // Ed25519 conversion would otherwise treat a non-aligned field as absent.
    let embedded = info
        .public_key
        .as_ref()
        .and_then(ed25519::pkcs8::BitStringRef::as_bytes)
        .filter(|bytes| bytes.len() == 32)
        .ok_or(SignatureFailure::InvalidKey)?;
    if embedded != approved_public_key {
        return Err(SignatureFailure::UnapprovedKey.into());
    }
    let key = SigningKey::try_from(info).map_err(|_| SignatureFailure::InvalidKey)?;
    if key.verifying_key().as_bytes() != approved_public_key {
        return Err(SignatureFailure::UnapprovedKey.into());
    }
    drop(pkcs8);
    Ok(key)
}

#[cfg(test)]
mod tests;
