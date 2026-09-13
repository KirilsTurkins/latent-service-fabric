//! Package signing with an explicitly approved host key.

use std::fmt;

use ed25519_dalek::{Signer, SigningKey};
use latent_artifacts::package::artifact_blob_digest;
use latent_core::{ArtifactBlobDigest, PublisherId};
use zeroize::Zeroizing;

use crate::{
    format::{
        encode_claims, encode_signature, pae, validate_publisher_id, SignatureClaims,
        SIGNATURE_PAYLOAD_TYPE,
    },
    keys::import_key,
    PackageSigningSubject, SignatureEvidence, SignatureLimits, SignatureResult, SignatureValidity,
};

/// A host-owned publisher signer with no private-key export or serialization API.
pub struct LocalSigner {
    key: SigningKey,
    publisher: PublisherId,
    key_hint: ArtifactBlobDigest,
}

impl LocalSigner {
    /// Import bounded `PKCS8v2` key material and match its approved public identity.
    ///
    /// The consumed buffer zeroizes on every return path. Publisher identity is
    /// included in signed claims; only the verifier's configured policy grants it
    /// authority.
    ///
    /// # Errors
    /// Rejects invalid publisher identifiers, malformed or oversized key material,
    /// unsupported key encodings, and mismatched approved public identities.
    pub fn from_pkcs8(
        pkcs8: Zeroizing<Vec<u8>>,
        publisher: PublisherId,
        approved_public_key: [u8; 32],
    ) -> SignatureResult<Self> {
        validate_publisher_id(&publisher.0)?;
        let key = import_key(pkcs8, &approved_public_key)?;
        // A bounded identifier may arrive in a caller-owned string with large
        // spare capacity. Discard it when converting the validated bytes to a box.
        let publisher = PublisherId(publisher.0.into_boxed_str().into_string());
        Ok(Self {
            key,
            publisher,
            key_hint: artifact_blob_digest(&approved_public_key),
        })
    }

    /// Sign the exact package subject and construct its detached OCI evidence.
    ///
    /// This signs one bounded claims buffer through DSSE PAE, then places those
    /// same bytes in the envelope. The caller chooses the validity interval;
    /// current-time and publisher authority checks belong to the verifier.
    ///
    /// # Errors
    /// Rejects invalid validity intervals, configured resource limits, or an
    /// evidence association that cannot be encoded within those limits.
    pub fn sign_package(
        &self,
        subject: &PackageSigningSubject,
        validity: SignatureValidity,
        limits: SignatureLimits,
    ) -> SignatureResult<SignatureEvidence> {
        let claims = SignatureClaims {
            format_version: 1,
            publisher_id: self.publisher.clone(),
            subject: subject.subject().clone(),
            issued_at: validity.issued_at,
            expires_at: validity.expires_at,
        };
        let payload = encode_claims(&claims, limits)?;
        let message = pae(SIGNATURE_PAYLOAD_TYPE, &payload)?;
        let signature = self.key.sign(&message).to_bytes();
        let envelope = encode_signature(&payload, signature, &self.key_hint, limits)?;
        SignatureEvidence::from_envelope(subject, &envelope, limits)
    }
}

impl fmt::Debug for LocalSigner {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("LocalSigner { private_key: [REDACTED] }")
    }
}

#[cfg(test)]
mod tests;
