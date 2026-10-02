//! Exact original associations. Bounded hashes name retained descriptions; they
//! do not supply policy, provider configuration, consumer delivery or a grant.

use super::{atomic_error, OriginalProfileArtifacts, RecoveryReviewError};
use crate::atomic::{InboxIdentity, SourceIdentity};
use latent_core::transaction_contract::CommandKey;
use latent_effects::authority::DispatchProfile;
use latent_state::{embedded::StoreError, recovery::snapshot::RequiredArtifact};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

#[derive(Default)]
pub(super) struct Artifacts(BTreeMap<String, [u8; 32]>);
impl Artifacts {
    pub(super) fn observe(
        &mut self,
        identity: &str,
        digest: [u8; 32],
    ) -> Result<(), RecoveryReviewError> {
        bounded(identity).map_err(RecoveryReviewError::Review)?;
        if digest == [0; 32] {
            return Err(RecoveryReviewError::Review(StoreError::Invalid));
        }
        if let Some(original) = self.0.get(identity) {
            return if *original == digest {
                Ok(())
            } else {
                Err(RecoveryReviewError::Review(StoreError::Conflict))
            };
        }
        if self.0.len() == latent_state::recovery::snapshot::SNAPSHOT_ARTIFACTS {
            return Err(RecoveryReviewError::Capacity);
        }
        self.0.insert(identity.to_owned(), digest);
        Ok(())
    }
    pub(super) fn digest(&mut self, identity: &str) -> Result<(), RecoveryReviewError> {
        let digest = identity
            .strip_prefix("sha256:")
            .ok_or(RecoveryReviewError::Source(StoreError::Corrupt))?;
        let digest = crate::atomic::Identity::parse_hex(digest)
            .map_err(atomic_error)?
            .bytes();
        self.observe(identity, digest)
    }
    pub(super) fn source(
        &mut self,
        source: &SourceIdentity,
        publication: [u8; 32],
    ) -> Result<(), RecoveryReviewError> {
        source.validate().map_err(atomic_error)?;
        self.observe(&source.publication, publication)?;
        for identity in [
            &source.release_digest,
            &source.component_digest,
            &source.contract_digest,
            &source.state_schema,
        ] {
            self.digest(identity)?;
        }
        Ok(())
    }
    pub(super) fn profile(
        &mut self,
        profile: &DispatchProfile,
        artifacts: OriginalProfileArtifacts,
    ) -> Result<(), RecoveryReviewError> {
        self.observe(&profile.adapter, artifacts.adapter_digest)?;
        self.observe(
            &original_profile_identity(profile).map_err(RecoveryReviewError::Review)?,
            artifacts.definition_digest,
        )
    }
    pub(super) fn finish(self) -> Vec<RequiredArtifact> {
        self.0
            .into_iter()
            .map(|(identity, digest)| RequiredArtifact { identity, digest })
            .collect()
    }
}

/// Closed stable identity of the original immutable provider/profile fields.
/// An installed reviewer must additionally verify the actual retained definition
/// bytes; hashing these labels is not provider qualification or authorization.
pub fn original_profile_identity(profile: &DispatchProfile) -> Result<String, StoreError> {
    if profile.intent_format == 0 {
        return Err(StoreError::Invalid);
    }
    let mut hash = Sha256::new();
    hash.update(b"latent-recovery-dispatch-profile-v1\0");
    for text in [
        &profile.provider,
        &profile.destination,
        &profile.adapter,
        &profile.payload_format,
        &profile.idempotency_profile,
    ] {
        frame(&mut hash, text)?;
    }
    hash.update(profile.intent_format.to_be_bytes());
    Ok(format!("dispatch-profile:{}", hex(hash.finalize().into())))
}

/// Original processing association, independent from each message/payload ID.
/// Changed provider/binding/publication/namespace/caller scope cannot reuse it.
/// The original message identity still resides in the validated command/inbox.
pub fn original_inbox_profile_identity(
    key: &CommandKey,
    source: &SourceIdentity,
    inbox: &InboxIdentity,
) -> Result<String, StoreError> {
    source.validate().map_err(|_| StoreError::Invalid)?;
    inbox.row_key(key).map_err(|_| StoreError::Invalid)?;
    let mut hash = Sha256::new();
    hash.update(b"latent-recovery-inbox-profile-v1\0");
    for text in [
        &key.tenant,
        &key.namespace,
        &key.incarnation,
        &key.recovery_scope,
        &source.publication,
        &inbox.provider,
        &inbox.binding,
    ] {
        frame(&mut hash, text)?;
    }
    Ok(format!("inbox-profile:{}", hex(hash.finalize().into())))
}

fn frame(hash: &mut Sha256, value: &str) -> Result<(), StoreError> {
    bounded(value)?;
    hash.update(
        u16::try_from(value.len())
            .map_err(|_| StoreError::Capacity)?
            .to_be_bytes(),
    );
    hash.update(value.as_bytes());
    Ok(())
}
pub(super) fn bounded(value: &str) -> Result<(), StoreError> {
    if value.is_empty() || value.len() > 256 || value.chars().any(char::is_control) {
        Err(StoreError::Invalid)
    } else {
        Ok(())
    }
}
fn hex(bytes: [u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(64);
    for byte in bytes {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 15)]));
    }
    output
}
