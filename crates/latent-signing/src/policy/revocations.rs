use super::{codec, interval, RevocationSnapshotConfig};
use crate::{format::validate_publisher_id, SignatureFailure, SignatureLimits, SignatureResult};
use latent_artifacts::package::artifact_blob_digest;
use latent_core::ArtifactBlobDigest;
use std::collections::BTreeSet;

/// Explicit operator-approved revocation data; even an empty set has an expiry.
#[derive(Debug)]
pub struct RevocationSnapshot {
    pub(crate) config: RevocationSnapshotConfig,
    pub(crate) keys: BTreeSet<ArtifactBlobDigest>,
    pub(crate) publishers: BTreeSet<String>,
    canonical: Box<[u8]>,
    digest: ArtifactBlobDigest,
}

impl RevocationSnapshot {
    pub fn from_json(bytes: &[u8], limits: SignatureLimits) -> SignatureResult<Self> {
        limits.validate()?;
        Self::new(
            codec::decode(
                bytes,
                limits.max_revocation_bytes,
                SignatureFailure::InvalidRevocations,
            )?,
            limits,
        )
    }

    pub fn new(
        mut config: RevocationSnapshotConfig,
        limits: SignatureLimits,
    ) -> SignatureResult<Self> {
        limits.validate()?;
        if config.revoked_keys.len() > limits.max_revoked_keys
            || config.revoked_publishers.len() > limits.max_revoked_publishers
        {
            return Err(SignatureFailure::ResourceLimit.into());
        }
        if config.format_version != 1
            || config.generation == 0
            || !interval(config.valid_from, config.valid_until)
            || config.policy_digest.parse::<ArtifactBlobDigest>().is_err()
        {
            return Err(SignatureFailure::InvalidRevocations.into());
        }
        validate_publisher_id(&config.scope).map_err(|_| SignatureFailure::InvalidRevocations)?;
        let mut keys = BTreeSet::new();
        for value in &config.revoked_keys {
            let key = value
                .parse::<ArtifactBlobDigest>()
                .map_err(|_| SignatureFailure::InvalidRevocations)?;
            if !keys.insert(key) {
                return Err(SignatureFailure::InvalidRevocations.into());
            }
        }
        let mut publishers = BTreeSet::new();
        for value in &config.revoked_publishers {
            validate_publisher_id(value).map_err(|_| SignatureFailure::InvalidRevocations)?;
            if !publishers.insert(value.clone()) {
                return Err(SignatureFailure::InvalidRevocations.into());
            }
        }
        config.revoked_keys.sort();
        config.revoked_publishers.sort();
        let canonical = codec::encode(&config, limits.max_revocation_bytes)?.into_boxed_slice();
        // Discard arbitrary spare capacity from typed input. These bytes were
        // just validated and encoded within the configured ownership ceiling.
        drop(config);
        let config: RevocationSnapshotConfig =
            serde_json::from_slice(&canonical).map_err(|_| SignatureFailure::Internal)?;
        let digest = artifact_blob_digest(&canonical);
        Ok(Self {
            config,
            keys,
            publishers,
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
        if self.canonical.len() > limits.max_revocation_bytes
            || self.keys.len() > limits.max_revoked_keys
            || self.publishers.len() > limits.max_revoked_publishers
        {
            return Err(SignatureFailure::ResourceLimit.into());
        }
        Ok(())
    }
}
