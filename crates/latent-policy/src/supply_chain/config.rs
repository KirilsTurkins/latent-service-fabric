use latent_artifacts::package::artifact_blob_digest;
use latent_core::PlatformError;
use latent_packaging::{SbomPolicy, SbomPolicyConfig};
use latent_signing::{
    BuilderPolicy, BuilderPolicyConfig, BuilderRevocationSnapshot, BuilderRevocationSnapshotConfig,
    BuilderTrust, BuilderVerifier, ProvenanceLimits, PublisherPolicy, PublisherPolicyConfig,
    PublisherTrust, PublisherVerifier, RevocationSnapshot, RevocationSnapshotConfig,
    SignatureLimits,
};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

use super::{denied, invalid};

/// Complete operator-approved snapshot bundle. Construction validates closed,
/// duplicate-free JSON and retains at most 256 KiB of canonical source policy.
/// An empty tenant/publisher set explicitly denies publication for that tenant.
pub struct SupplyChainPolicy {
    pub(super) identity: PolicyIdentity,
    pub(super) sbom: SbomPolicy,
    pub(super) tenants: BTreeMap<String, BTreeSet<String>>,
    publisher: Box<[u8]>,
    publisher_revocations: Box<[u8]>,
    builder: Box<[u8]>,
    builder_revocations: Box<[u8]>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Input {
    format_version: u32,
    generation: u64,
    scope: String,
    valid_from: u64,
    valid_until: u64,
    tenants: Vec<TenantPublishers>,
    publisher: PublisherPolicyConfig,
    publisher_revocations: RevocationSnapshotConfig,
    builder: BuilderPolicyConfig,
    builder_revocations: BuilderRevocationSnapshotConfig,
    sbom: SbomPolicyConfig,
}
#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TenantPublishers {
    tenant: String,
    publishers: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct GenerationIdentity {
    pub generation: u64,
    pub digest: String,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct PolicyIdentity {
    pub generation: u64,
    pub scope: String,
    pub valid_from: u64,
    pub valid_until: u64,
    pub tenants_digest: String,
    pub publisher: GenerationIdentity,
    pub publisher_revocations: GenerationIdentity,
    pub builder: GenerationIdentity,
    pub builder_revocations: GenerationIdentity,
    pub sbom_digest: String,
}

impl SupplyChainPolicy {
    pub fn from_json(bytes: &[u8]) -> Result<Self, PlatformError> {
        super::json::preflight(bytes, 256 * 1024)?;
        let input: Input =
            serde_json::from_slice(bytes).map_err(|_| invalid("admission-policy-profile"))?;
        if input.format_version != 1
            || input.generation == 0
            || !identifier(&input.scope)
            || input.valid_from >= input.valid_until
            || input.tenants.len() > 128
            || input.publisher.scope != input.scope
            || input.builder.scope != input.scope
        {
            return Err(invalid("admission-policy-profile"));
        }
        let mut tenants = BTreeMap::new();
        for entry in input.tenants {
            if !identifier(&entry.tenant) || entry.publishers.len() > 64 {
                return Err(invalid("admission-tenant-policy"));
            }
            let mut publishers = BTreeSet::new();
            for publisher in entry.publishers {
                if !identifier(&publisher) || !publishers.insert(publisher) {
                    return Err(invalid("admission-tenant-policy"));
                }
            }
            if tenants.insert(entry.tenant, publishers).is_some() {
                return Err(invalid("admission-tenant-policy"));
            }
        }
        let publisher_generation = input.publisher.generation;
        let publisher_revocation_generation = input.publisher_revocations.generation;
        let builder_generation = input.builder.generation;
        let builder_revocation_generation = input.builder_revocations.generation;
        let publisher = PublisherPolicy::new(input.publisher, SignatureLimits::default())?;
        let publisher_revocations =
            RevocationSnapshot::new(input.publisher_revocations, SignatureLimits::default())?;
        let builder = BuilderPolicy::new(input.builder, ProvenanceLimits::default())?;
        let builder_revocations =
            BuilderRevocationSnapshot::new(input.builder_revocations, ProvenanceLimits::default())?;
        let sbom = SbomPolicy::new(input.sbom)?;
        let identity = PolicyIdentity {
            generation: input.generation,
            scope: input.scope,
            valid_from: input.valid_from,
            valid_until: input.valid_until,
            tenants_digest: artifact_blob_digest(
                &serde_json::to_vec(&tenants).map_err(|_| invalid("admission-policy-profile"))?,
            )
            .to_string(),
            publisher: GenerationIdentity {
                generation: publisher_generation,
                digest: publisher.digest().to_string(),
            },
            publisher_revocations: GenerationIdentity {
                generation: publisher_revocation_generation,
                digest: publisher_revocations.digest().to_string(),
            },
            builder: GenerationIdentity {
                generation: builder_generation,
                digest: builder.digest().to_string(),
            },
            builder_revocations: GenerationIdentity {
                generation: builder_revocation_generation,
                digest: builder_revocations.digest().to_string(),
            },
            sbom_digest: sbom.digest().to_string(),
        };
        let result = Self {
            identity,
            sbom,
            tenants,
            publisher: publisher.canonical_bytes().into(),
            publisher_revocations: publisher_revocations.canonical_bytes().into(),
            builder: builder.canonical_bytes().into(),
            builder_revocations: builder_revocations.canonical_bytes().into(),
        };
        // Check both exact policy/snapshot associations before retaining this
        // validated bundle. Freshness is checked at authority construction.
        PublisherTrust::new(publisher, publisher_revocations)?;
        BuilderTrust::new(builder, builder_revocations)?;
        Ok(result)
    }
    pub(super) fn fresh(&self, now: u64) -> Result<(), PlatformError> {
        if now < self.identity.valid_from || now >= self.identity.valid_until {
            return Err(denied("admission-policy-expired"));
        }
        Ok(())
    }
    pub(super) fn verifiers(
        &self,
        now: u64,
    ) -> Result<(PublisherVerifier, BuilderVerifier), PlatformError> {
        self.fresh(now)?;
        let signatures = SignatureLimits::default();
        let provenance = ProvenanceLimits::default();
        let publisher = PublisherTrust::new(
            PublisherPolicy::from_json(&self.publisher, signatures)?,
            RevocationSnapshot::from_json(&self.publisher_revocations, signatures)?,
        )?;
        let builder = BuilderTrust::new(
            BuilderPolicy::from_json(&self.builder, provenance)?,
            BuilderRevocationSnapshot::from_json(&self.builder_revocations, provenance)?,
        )?;
        Ok((
            PublisherVerifier::new(publisher, signatures, now)?,
            BuilderVerifier::new(builder, provenance, now)?,
        ))
    }
}

impl PolicyIdentity {
    pub(super) fn validate(&self) -> Result<(), PlatformError> {
        if self.generation == 0 || !identifier(&self.scope) || self.valid_from >= self.valid_until {
            return Err(invalid("admission-policy-identity"));
        }
        for component in [
            &self.publisher,
            &self.publisher_revocations,
            &self.builder,
            &self.builder_revocations,
        ] {
            if component.generation == 0
                || component
                    .digest
                    .parse::<latent_core::ArtifactBlobDigest>()
                    .is_err()
            {
                return Err(invalid("admission-policy-identity"));
            }
        }
        for digest in [&self.tenants_digest, &self.sbom_digest] {
            if digest.parse::<latent_core::ArtifactBlobDigest>().is_err() {
                return Err(invalid("admission-policy-identity"));
            }
        }
        Ok(())
    }
    pub(super) fn digest(&self) -> Result<String, PlatformError> {
        Ok(artifact_blob_digest(
            &serde_json::to_vec(self).map_err(|_| invalid("admission-policy-profile"))?,
        )
        .to_string())
    }
    pub(super) fn replaces(&self, previous: &Self) -> Result<(), PlatformError> {
        if self.scope != previous.scope
            || self.generation < previous.generation
            || (self.generation == previous.generation && self != previous)
        {
            return Err(denied("admission-policy-floor"));
        }
        for (next, old) in [
            (&self.publisher, &previous.publisher),
            (&self.publisher_revocations, &previous.publisher_revocations),
            (&self.builder, &previous.builder),
            (&self.builder_revocations, &previous.builder_revocations),
        ] {
            if next.generation < old.generation
                || (next.generation == old.generation && next.digest != old.digest)
            {
                return Err(denied("admission-policy-floor"));
            }
        }
        Ok(())
    }
}
pub(super) fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"-_.:/@".contains(&byte))
}
