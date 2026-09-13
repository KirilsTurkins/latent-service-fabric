use super::{
    capability::{Owner, Row},
    *,
};
use crate::{AdmissionAuthority, ReleaseEligibility};
use latent_core::{ArtifactBlobDigest, PackageDigest, PlatformError, ReleaseDigest};
use serde::{Deserialize, Serialize};
use std::{
    cell::Cell,
    collections::BTreeMap,
    path::{Path, PathBuf},
    sync::{Arc, Mutex, RwLock, RwLockReadGuard, RwLockWriteGuard},
};
mod evidence;
mod io;
mod persistence;
mod validation;
pub(crate) use evidence::LifecycleEvidence;

pub(crate) fn validate_audit_receipt(value: &ReleaseOperationReceipt) -> Result<(), PlatformError> {
    validation::receipt(value, LifecycleLimits::default())
}

/// Caller has already verified immutable content and its COMPLETE association.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(crate) struct LifecycleIdentity {
    pub scope: LifecycleScope,
    #[serde(with = "super::codec::release")]
    pub release: ReleaseDigest,
    #[serde(with = "super::codec::optional_package")]
    pub package: Option<PackageDigest>,
    pub completion: [u8; 32],
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct StoredRow {
    identity: LifecycleIdentity,
    record: ReleaseLifecycleRecord,
}
struct Entry {
    stored: StoredRow,
    row: Arc<Row>,
    bytes: usize,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct StoredReceipt {
    sequence: u64,
    receipt: ReleaseOperationReceipt,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Head {
    format_version: u32,
    mode: [u8; 32],
    sequence: u64,
    receipt_digest: Option<[u8; 32]>,
    rows: usize,
    row_bytes: usize,
}
struct State {
    head: Head,
    entries: BTreeMap<ReleaseDigest, Entry>,
    receipts: BTreeMap<usize, StoredReceipt>,
}

pub(crate) struct LifecycleStore {
    root: PathBuf,
    limits: LifecycleLimits,
    owner: Arc<Owner>,
    state: RwLock<State>,
    evidence: Mutex<evidence::EvidenceState>,
}
pub(crate) struct LifecyclePrepared {
    receipt: ReleaseOperationReceipt,
    identity: Option<LifecycleIdentity>,
    head: Head,
    replay: bool,
}
impl LifecyclePrepared {
    pub(crate) fn receipt(&self) -> &ReleaseOperationReceipt {
        &self.receipt
    }
    #[cfg(test)]
    pub(crate) fn is_replay(&self) -> bool {
        self.replay
    }
}
pub(crate) struct LifecycleFence<'a> {
    store: &'a LifecycleStore,
    _guard: RwLockWriteGuard<'a, ()>,
    mutated: Cell<bool>,
}
/// A shared snapshot fence cannot commit a prepared lifecycle transition.
pub(crate) struct LifecycleReadFence<'a> {
    store: &'a LifecycleStore,
    _guard: RwLockReadGuard<'a, ()>,
}

impl LifecycleStore {
    pub(crate) fn open(
        root: &Path,
        limits: LifecycleLimits,
        authority: Option<Arc<dyn AdmissionAuthority>>,
        baseline: &[LifecycleIdentity],
    ) -> Result<Self, PlatformError> {
        limits.validate()?;
        let root = io::root(root)?;
        let state = persistence::open(&root, limits, authority.is_some(), baseline)?;
        let store = Self {
            root,
            limits,
            owner: Owner::new(authority),
            state: RwLock::new(state),
            evidence: Mutex::new(evidence::EvidenceState::default()),
        };
        store.recover_evidence()?;
        Ok(store)
    }
    pub(crate) fn handle(&self) -> LifecycleAuthorityHandle {
        LifecycleAuthorityHandle {
            owner: Arc::clone(&self.owner),
        }
    }
    pub(crate) fn limits(&self) -> LifecycleLimits {
        self.limits
    }
    pub(crate) fn retire(&self) {
        self.owner.retire();
    }
    pub(crate) fn record(
        &self,
        release: &ReleaseDigest,
    ) -> Result<Option<ReleaseLifecycleRecord>, PlatformError> {
        self.owner.check()?;
        let state = self.state.try_read().map_err(lock_error)?;
        Ok(state
            .entries
            .get(release)
            .map(|entry| entry.stored.record.clone()))
    }
    pub(crate) fn identity(
        &self,
        release: &ReleaseDigest,
    ) -> Result<Option<LifecycleIdentity>, PlatformError> {
        self.owner.check()?;
        let state = self.state.try_read().map_err(lock_error)?;
        Ok(state
            .entries
            .get(release)
            .map(|entry| entry.stored.identity.clone()))
    }
    pub(crate) fn operation(
        &self,
        scope: &LifecycleScope,
        id: &str,
    ) -> Result<ReleaseOperationLookup, PlatformError> {
        scope.validate()?;
        model::token(id, 128)?;
        if self.owner.check().is_err() {
            return Ok(ReleaseOperationLookup::Uncertain);
        }
        let state = self.state.try_read().map_err(lock_error)?;
        Ok(state
            .receipts
            .values()
            .find(|entry| entry.receipt.scope == *scope && entry.receipt.operation_id == id)
            .map_or(ReleaseOperationLookup::Unknown, |entry| {
                ReleaseOperationLookup::Found(entry.receipt.clone())
            }))
    }
    #[cfg(test)]
    pub(crate) fn eligibility(
        &self,
        release: &ReleaseDigest,
        admission: Option<ReleaseEligibility>,
    ) -> Result<ReleaseUseEligibility, PlatformError> {
        let _fence = self.owner.read()?;
        self.make_eligibility(release, admission)
    }
    fn make_eligibility(
        &self,
        release: &ReleaseDigest,
        admission: Option<ReleaseEligibility>,
    ) -> Result<ReleaseUseEligibility, PlatformError> {
        self.owner.check()?;
        let state = self.state.try_read().map_err(lock_error)?;
        let entry = state.entries.get(release).ok_or_else(unavailable)?;
        let lifecycle = LifecycleEligibility {
            owner: Arc::clone(&self.owner),
            row: Arc::clone(&entry.row),
            generation: entry.stored.record.generation,
        };
        lifecycle.check_current()?;
        ReleaseUseEligibility::new(lifecycle, admission)
    }
    /// Preparation is read-only; the trusted adapter invokes its rejection-only
    /// response preflight before staging any files or entering the final fence.
    pub(crate) fn prepare(
        &self,
        receipt: ReleaseOperationReceipt,
        identity: Option<LifecycleIdentity>,
    ) -> Result<LifecyclePrepared, PlatformError> {
        self.owner.check()?;
        validation::receipt(&receipt, self.limits)?;
        let state = self.state.try_read().map_err(lock_error)?;
        if let Some(previous) = state.receipts.values().find(|entry| {
            entry.receipt.scope == receipt.scope
                && entry.receipt.operation_id == receipt.operation_id
        }) {
            if previous.receipt.request_digest != receipt.request_digest {
                return Err(conflict());
            }
            return Ok(LifecyclePrepared {
                receipt: previous.receipt.clone(),
                identity: None,
                head: state.head.clone(),
                replay: true,
            });
        }
        validation::transition(
            &state,
            &receipt,
            identity.as_ref(),
            self.owner_mode(),
            self.limits,
        )?;
        Ok(LifecyclePrepared {
            receipt,
            identity,
            head: state.head.clone(),
            replay: false,
        })
    }
    fn owner_mode(&self) -> bool {
        self.handle().required_authority().is_some()
    }
    pub(crate) fn with_current(
        &self,
        action: &mut dyn FnMut(&LifecycleReadFence<'_>) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let fence = LifecycleReadFence {
            store: self,
            _guard: self.owner.read()?,
        };
        action(&fence)
    }
    /// Selected-proof replacement and durable transitions require an exclusive
    /// fence even when they do not both modify the lifecycle journal.
    pub(crate) fn with_exclusive(
        &self,
        action: &mut dyn FnMut(&LifecycleFence<'_>) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let fence = LifecycleFence {
            store: self,
            _guard: self.owner.write()?,
            mutated: Cell::new(false),
        };
        let result = action(&fence);
        if result.is_err() && fence.mutated.get() {
            self.owner.poison();
        }
        result
    }
    pub(crate) fn with_prepared(
        &self,
        prepared: &LifecyclePrepared,
        action: &mut dyn FnMut(&LifecycleFence<'_>) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.with_exclusive(&mut |fence| {
            {
                let state = self.state.try_read().map_err(lock_error)?;
                if state.head != prepared.head {
                    return Err(conflict());
                }
            }
            action(fence)
        })
    }
}
impl Drop for LifecycleStore {
    fn drop(&mut self) {
        self.retire();
    }
}
impl LifecycleReadFence<'_> {
    pub(crate) fn eligibility(
        &self,
        release: &ReleaseDigest,
        admission: Option<ReleaseEligibility>,
    ) -> Result<ReleaseUseEligibility, PlatformError> {
        self.store.make_eligibility(release, admission)
    }
}
impl LifecycleFence<'_> {
    pub(crate) fn check(&self) -> Result<(), PlatformError> {
        self.store.owner.check()
    }
    pub(crate) fn commit(&self, prepared: &LifecyclePrepared) -> Result<(), PlatformError> {
        self.check()?;
        let mut state = self.store.state.try_write().map_err(lock_error)?;
        if state.head != prepared.head {
            return Err(conflict());
        }
        if prepared.replay {
            return Ok(());
        }
        validation::transition(
            &state,
            &prepared.receipt,
            prepared.identity.as_ref(),
            self.store.owner_mode(),
            self.store.limits,
        )?;
        let old_revision = prepared
            .receipt
            .component_digest
            .as_ref()
            .and_then(|release| state.entries.get(release))
            .and_then(|entry| entry.stored.record.evidence_revision_digest.clone());
        let new_revision = if prepared.receipt.disposition == ReleaseOperationDisposition::Committed
        {
            prepared
                .receipt
                .record
                .as_ref()
                .and_then(|record| record.evidence_revision_digest.clone())
        } else {
            old_revision.clone()
        };
        self.store.check_evidence_cutover(
            prepared.receipt.component_digest.as_ref(),
            old_revision.as_ref(),
            new_revision.as_ref(),
        )?;
        self.mutated.set(true);
        let result = persistence::commit(&self.store.root, self.store.limits, &mut state, prepared);
        if result.is_err() {
            self.store.owner.poison();
        }
        result?;
        self.store
            .evidence_cutover(old_revision.as_ref(), new_revision.as_ref())?;
        Ok(())
    }
}

fn digest(bytes: &[u8]) -> [u8; 32] {
    use sha2::{Digest, Sha256};
    Sha256::digest(bytes).into()
}
fn blob(bytes: &[u8]) -> ArtifactBlobDigest {
    crate::content_hash::format_digest(digest(bytes))
        .0
        .parse()
        .expect("formatted SHA-256")
}
fn encode<T: Serialize>(value: &T, maximum: usize) -> Result<Vec<u8>, PlatformError> {
    let bytes = serde_json::to_vec(value).map_err(|_| invalid())?;
    if bytes.len() > maximum {
        return Err(exhausted());
    }
    Ok(bytes)
}
fn decode<T: serde::de::DeserializeOwned + Serialize>(
    bytes: &[u8],
    maximum: usize,
) -> Result<T, PlatformError> {
    if bytes.len() > maximum {
        return Err(exhausted());
    }
    let value = serde_json::from_slice(bytes).map_err(|_| corrupt())?;
    if encode(&value, maximum)? != bytes {
        return Err(corrupt());
    }
    Ok(value)
}

#[cfg(test)]
mod schema_tests;
#[cfg(test)]
mod tests;
