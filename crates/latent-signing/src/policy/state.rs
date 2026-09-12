use super::{contains, PublisherPolicy, RevocationSnapshot};
use crate::{SignatureFailure, SignatureLimits, SignatureResult};
use latent_core::ArtifactBlobDigest;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TrustStateId {
    policy_digest: ArtifactBlobDigest,
    revocation_digest: ArtifactBlobDigest,
    policy_generation: u64,
    revocation_generation: u64,
}
impl TrustStateId {
    #[must_use]
    pub fn policy_digest(&self) -> &ArtifactBlobDigest {
        &self.policy_digest
    }
    #[must_use]
    pub fn revocation_digest(&self) -> &ArtifactBlobDigest {
        &self.revocation_digest
    }
    #[must_use]
    pub const fn policy_generation(&self) -> u64 {
        self.policy_generation
    }
    #[must_use]
    pub const fn revocation_generation(&self) -> u64 {
        self.revocation_generation
    }

    #[cfg(test)]
    pub(crate) fn test(
        policy_digest: ArtifactBlobDigest,
        revocation_digest: ArtifactBlobDigest,
        policy_generation: u64,
        revocation_generation: u64,
    ) -> Self {
        Self {
            policy_digest,
            revocation_digest,
            policy_generation,
            revocation_generation,
        }
    }
}

#[derive(Debug)]
pub struct PublisherTrust {
    pub(crate) policy: PublisherPolicy,
    pub(crate) revocations: RevocationSnapshot,
    id: TrustStateId,
}
impl PublisherTrust {
    pub fn new(policy: PublisherPolicy, revocations: RevocationSnapshot) -> SignatureResult<Self> {
        if policy.config.scope != revocations.config.scope
            || policy.digest().as_str() != revocations.config.policy_digest
        {
            return Err(SignatureFailure::InvalidRevocations.into());
        }
        let id = TrustStateId {
            policy_digest: policy.digest().clone(),
            revocation_digest: revocations.digest().clone(),
            policy_generation: policy.config.generation,
            revocation_generation: revocations.config.generation,
        };
        Ok(Self {
            policy,
            revocations,
            id,
        })
    }

    #[must_use]
    pub fn state_id(&self) -> &TrustStateId {
        &self.id
    }

    pub(crate) fn fresh(&self, now: u64) -> SignatureResult<()> {
        if !contains(
            self.policy.config.valid_from,
            self.policy.config.valid_until,
            now,
        ) || !contains(
            self.revocations.config.valid_from,
            self.revocations.config.valid_until,
            now,
        ) {
            return Err(SignatureFailure::TrustExpired.into());
        }
        Ok(())
    }
    pub(crate) fn fits(&self, limits: SignatureLimits) -> SignatureResult<()> {
        self.policy.fits(limits)?;
        self.revocations.fits(limits)
    }
    pub(crate) fn replaces(&self, current: &Self) -> SignatureResult<()> {
        if self.policy.config.scope != current.policy.config.scope {
            return Err(SignatureFailure::TrustConflict.into());
        }
        for (next_generation, next_digest, generation, digest) in [
            (
                self.id.policy_generation,
                &self.id.policy_digest,
                current.id.policy_generation,
                &current.id.policy_digest,
            ),
            (
                self.id.revocation_generation,
                &self.id.revocation_digest,
                current.id.revocation_generation,
                &current.id.revocation_digest,
            ),
        ] {
            if next_generation < generation
                || (next_generation == generation && next_digest != digest)
            {
                return Err(SignatureFailure::TrustConflict.into());
            }
        }
        Ok(())
    }
}
