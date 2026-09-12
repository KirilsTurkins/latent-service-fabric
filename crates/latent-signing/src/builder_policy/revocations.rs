use super::{codec, interval, BuilderRevocationSnapshotConfig};
use crate::{
    format::validate_publisher_id as validate_builder_id, ProvenanceLimits, SignatureFailure,
    SignatureResult,
};
use latent_artifacts::package::artifact_blob_digest;
use latent_core::ArtifactBlobDigest;
use std::collections::BTreeSet;

/// Explicit operator-approved revocation data; even an empty set has an expiry.
#[derive(Debug)]
pub struct BuilderRevocationSnapshot {
    pub(crate) config: BuilderRevocationSnapshotConfig,
    pub(crate) keys: BTreeSet<ArtifactBlobDigest>,
    pub(crate) builders: BTreeSet<String>,
    canonical: Box<[u8]>,
    digest: ArtifactBlobDigest,
}

impl BuilderRevocationSnapshot {
    pub fn from_json(bytes: &[u8], limits: ProvenanceLimits) -> SignatureResult<Self> {
        limits.validate()?;
        Self::new(
            codec::decode(
                bytes,
                limits.max_policy_bytes,
                SignatureFailure::InvalidRevocations,
            )?,
            limits,
        )
    }

    pub fn new(
        mut config: BuilderRevocationSnapshotConfig,
        limits: ProvenanceLimits,
    ) -> SignatureResult<Self> {
        limits.validate()?;
        if config.revoked_keys.len() > limits.max_revoked_keys
            || config.revoked_builders.len() > limits.max_revoked_builders
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
        validate_builder_id(&config.scope).map_err(|_| SignatureFailure::InvalidRevocations)?;
        let mut keys = BTreeSet::new();
        for value in &config.revoked_keys {
            let key = value
                .parse::<ArtifactBlobDigest>()
                .map_err(|_| SignatureFailure::InvalidRevocations)?;
            if !keys.insert(key) {
                return Err(SignatureFailure::InvalidRevocations.into());
            }
        }
        let mut builders = BTreeSet::new();
        for value in &config.revoked_builders {
            validate_builder_id(value).map_err(|_| SignatureFailure::InvalidRevocations)?;
            if !builders.insert(value.clone()) {
                return Err(SignatureFailure::InvalidRevocations.into());
            }
        }
        config.revoked_keys.sort();
        config.revoked_builders.sort();
        let canonical = codec::encode(&config, limits.max_policy_bytes)?.into_boxed_slice();
        // Discard arbitrary spare capacity from typed input. These bytes were
        // just validated and encoded within the configured ownership ceiling.
        drop(config);
        let config = codec::decode(
            &canonical,
            limits.max_policy_bytes,
            SignatureFailure::InvalidRevocations,
        )?;
        let digest = artifact_blob_digest(&canonical);
        Ok(Self {
            config,
            keys,
            builders,
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

    pub(crate) fn fits(&self, limits: ProvenanceLimits) -> SignatureResult<()> {
        if self.canonical.len() > limits.max_policy_bytes
            || self.keys.len() > limits.max_revoked_keys
            || self.builders.len() > limits.max_revoked_builders
        {
            return Err(SignatureFailure::ResourceLimit.into());
        }
        Ok(())
    }
}
