//! Explicit volatile ownership for controlled application tests. There is no
//! catalog, publisher approval, durable publication receipt or node configuration.
use super::capability::{LifecycleAuthorityHandle, LifecycleEligibility, Owner, Row};
use super::{
    LifecycleScope, ReleaseActor, ReleaseActorKind, ReleaseLifecycleReason, ReleaseLifecycleRecord,
    ReleaseLifecycleState, ReleaseUseEligibility,
};
use crate::{content_digest, CapsuleArtifact};
use latent_core::{PlatformError, PublicationId, TenantId};
use latent_manifest::{ManifestValidator, Phase1ManifestValidator};
use sha2::{Digest, Sha256};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};

static NEXT: AtomicU64 = AtomicU64::new(1);

/// A single immutable component under a distinct, process-local test owner.
/// Its sealed eligibility can never match a directory catalog's owner, and
/// contains no signing proof. Dropping this value retires all its capabilities.
pub struct DevelopmentTestArtifact {
    artifact: CapsuleArtifact,
    owner: Arc<Owner>,
    eligibility: ReleaseUseEligibility,
}

impl DevelopmentTestArtifact {
    pub fn new(artifact: CapsuleArtifact, tenant: TenantId) -> Result<Self, PlatformError> {
        if artifact
            .manifest
            .metadata
            .tenant
            .as_ref()
            .is_some_and(|value| value != &tenant)
        {
            return Err(super::invalid());
        }
        let scope = LifecycleScope::Tenant(tenant);
        scope.validate()?;
        if artifact.component_bytes.len() > 16 * 1024 * 1024
            || artifact.component_bytes.get(..8) != Some(b"\0asm\x0d\0\x01\0")
            || artifact.descriptor.release_digest != content_digest(&artifact.component_bytes)
            || artifact.manifest.component_digest != artifact.descriptor.release_digest
            || artifact.descriptor.size_bytes != artifact.component_bytes.len() as u64
        {
            return Err(super::invalid());
        }
        Phase1ManifestValidator
            .validate_capsule(&artifact.manifest)
            .map_err(|_| super::invalid())?;
        let sequence = NEXT
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                value.checked_add(1)
            })
            .map_err(|_| super::exhausted())?;
        let mut identity = Sha256::new();
        identity.update(b"latent-controlled-development-owner-v1\0");
        identity.update(sequence.to_le_bytes());
        identity.update(artifact.descriptor.release_digest.0.as_bytes());
        let publication: PublicationId = format!("publication:sha256:{:x}", identity.finalize())
            .parse()
            .map_err(|_| super::invalid())?;
        let record = ReleaseLifecycleRecord {
            scope,
            release: artifact.descriptor.release_digest.clone(),
            package: None,
            state: ReleaseLifecycleState::Admitted,
            generation: 1,
            actor: ReleaseActor {
                subject: "controlled-development-test".into(),
                kind: ReleaseActorKind::Host,
            },
            reason: ReleaseLifecycleReason::Admitted,
            operation_id: "volatile-test-input".into(),
            policy: None,
            observed_at_unix_millis: None,
            evidence_revision_digest: None,
        };
        let owner = Owner::new(None);
        let eligibility = ReleaseUseEligibility::new(
            LifecycleEligibility {
                owner: owner.clone(),
                row: Row::new(&record, publication),
                generation: 1,
                projection: None,
            },
            None,
        )?;
        Ok(Self {
            artifact,
            owner,
            eligibility,
        })
    }

    #[must_use]
    pub fn artifact(&self) -> &CapsuleArtifact {
        &self.artifact
    }

    #[must_use]
    pub fn authority(&self) -> LifecycleAuthorityHandle {
        LifecycleAuthorityHandle {
            owner: self.owner.clone(),
        }
    }

    #[must_use]
    pub fn eligibility(&self) -> &ReleaseUseEligibility {
        &self.eligibility
    }
}

impl Drop for DevelopmentTestArtifact {
    fn drop(&mut self) {
        self.owner.retire();
    }
}
