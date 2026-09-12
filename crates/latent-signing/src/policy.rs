mod codec;
mod model;
mod revocations;
mod state;
#[cfg(test)]
mod tests;

pub use model::{PublisherKeyConfig, PublisherPolicyConfig, RevocationSnapshotConfig};
pub use revocations::RevocationSnapshot;
pub use state::{PublisherTrust, TrustStateId};

use crate::{
    crypto::validate_public_key, format::validate_publisher_id, SignatureFailure, SignatureLimits,
    SignatureResult, MAX_PROOF_AGE_SECONDS, MAX_SIGNATURE_LIFETIME_SECONDS,
};
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::package::artifact_blob_digest;
use latent_core::{ArtifactBlobDigest, PublisherId};
use std::collections::BTreeMap;

#[derive(Debug)]
pub(crate) struct TrustedKey {
    pub(crate) public_key: [u8; 32],
    pub(crate) publisher: PublisherId,
    pub(crate) valid_from: u64,
    pub(crate) valid_until: u64,
}

/// Operator-approved package-publisher anchors, never authority supplied by a guest.
#[derive(Debug)]
pub struct PublisherPolicy {
    pub(crate) config: PublisherPolicyConfig,
    pub(crate) keys: BTreeMap<ArtifactBlobDigest, TrustedKey>,
    canonical: Box<[u8]>,
    digest: ArtifactBlobDigest,
}

impl PublisherPolicy {
    pub fn from_json(bytes: &[u8], limits: SignatureLimits) -> SignatureResult<Self> {
        limits.validate()?;
        Self::new(
            codec::decode(
                bytes,
                limits.max_policy_bytes,
                SignatureFailure::InvalidPolicy,
            )?,
            limits,
        )
    }

    pub fn new(
        mut config: PublisherPolicyConfig,
        limits: SignatureLimits,
    ) -> SignatureResult<Self> {
        limits.validate()?;
        if config.keys.len() > limits.max_keys {
            return Err(SignatureFailure::ResourceLimit.into());
        }
        if config.format_version != 1
            || config.generation == 0
            || !interval(config.valid_from, config.valid_until)
            || config.max_signature_lifetime_seconds == 0
            || config.max_signature_lifetime_seconds > MAX_SIGNATURE_LIFETIME_SECONDS
            || config.max_proof_age_seconds == 0
            || config.max_proof_age_seconds > MAX_PROOF_AGE_SECONDS
        {
            return Err(SignatureFailure::InvalidPolicy.into());
        }
        validate_publisher_id(&config.scope).map_err(|_| SignatureFailure::InvalidPolicy)?;
        let mut keys = BTreeMap::new();
        let mut ordered = BTreeMap::new();
        for item in std::mem::take(&mut config.keys) {
            let (fingerprint, key) = approved_key(&item)?;
            if keys.insert(fingerprint.clone(), key).is_some() {
                return Err(SignatureFailure::InvalidPolicy.into());
            }
            ordered.insert(fingerprint, item);
        }
        config.keys = ordered.into_values().collect();
        let canonical = codec::encode(&config, limits.max_policy_bytes)?.into_boxed_slice();
        // Typed callers can supply tiny strings/vectors with enormous spare
        // capacity. Retain fresh data decoded from our bounded canonical output,
        // rather than keeping those caller-owned allocations in the verifier.
        drop(config);
        let config: PublisherPolicyConfig =
            serde_json::from_slice(&canonical).map_err(|_| SignatureFailure::Internal)?;
        let digest = artifact_blob_digest(&canonical);
        Ok(Self {
            config,
            keys,
            canonical,
            digest,
        })
    }

    #[must_use]
    pub fn digest(&self) -> &ArtifactBlobDigest {
        &self.digest
    }

    #[must_use]
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.canonical
    }

    pub(crate) fn fits(&self, limits: SignatureLimits) -> SignatureResult<()> {
        if self.canonical.len() > limits.max_policy_bytes || self.keys.len() > limits.max_keys {
            return Err(SignatureFailure::ResourceLimit.into());
        }
        Ok(())
    }
}

fn approved_key(config: &PublisherKeyConfig) -> SignatureResult<(ArtifactBlobDigest, TrustedKey)> {
    validate_publisher_id(&config.publisher_id).map_err(|_| SignatureFailure::InvalidPolicy)?;
    if !interval(config.valid_from, config.valid_until) || config.public_key.len() != 44 {
        return Err(SignatureFailure::InvalidPolicy.into());
    }
    let decoded = STANDARD
        .decode(&config.public_key)
        .map_err(|_| SignatureFailure::InvalidKey)?;
    let public_key: [u8; 32] = decoded
        .try_into()
        .map_err(|_| SignatureFailure::InvalidKey)?;
    if STANDARD.encode(public_key) != config.public_key {
        return Err(SignatureFailure::InvalidKey.into());
    }
    validate_public_key(&public_key)?;
    Ok((
        artifact_blob_digest(&public_key),
        TrustedKey {
            public_key,
            publisher: PublisherId(config.publisher_id.clone()),
            valid_from: config.valid_from,
            valid_until: config.valid_until,
        },
    ))
}

pub(crate) const fn interval(from: u64, until: u64) -> bool {
    from < until
}
pub(crate) const fn contains(from: u64, until: u64, now: u64) -> bool {
    from <= now && now < until
}
