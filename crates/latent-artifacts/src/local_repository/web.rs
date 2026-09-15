//! Componentless web publications inside the exclusively owned artifact catalog.
//! Componentless web publications share the actual catalog owner, admission
//! work slot, writer and content/index budgets. They never enter capsule indexes.
mod evidence;
mod mutation;
mod persistence;
mod reclamation;
mod recovery;
mod selection;
mod storage;

use super::{
    admission, corrupt, error, fs, io_error, lock_error, read_bounded_file, resource_exhausted,
    shared_content, sync_dir, write_synced, Arc, DirectoryArtifactRepository, Path, PathBuf,
    PlatformError, PlatformErrorCode, PublicationState, RwLock, TEMP_DIR,
};
use crate::{
    web::{
        CheckedWebLayout, VerifiedWebAdmission, WebAdmissionBinding, WebAdmissionGrant,
        WebBlobRead, WebEpoch, WebGeneration, WebLifecycleRecord, WebMutationResult,
        WebOperationReceipt, WebPublicationStatus, WebReadBudget, WebReadLimits, WebReadSnapshot,
        WebSelection, WebUseEligibility,
    },
    LifecycleScope, PublicationRef, ReleaseLifecycleState,
};
use latent_core::{ArtifactBlobDigest, PublicationId, TenantId};
use std::collections::{BTreeMap, VecDeque};
#[cfg(test)]
use std::sync::atomic::AtomicBool;

const DIRECTORY: &str = "web";
const PUBLICATIONS: &str = "publications";
const EVIDENCE: &str = "evidence";
const HEAD: &str = "HEAD";

pub(super) struct WebCatalog {
    pub(super) epoch: Arc<WebEpoch>,
    state: RwLock<State>,
    reads: Arc<WebReadBudget>,
    #[cfg(test)]
    pub(super) fail_after_head: AtomicBool,
}
impl WebCatalog {
    pub(super) fn new() -> Result<Self, PlatformError> {
        Ok(Self {
            epoch: Arc::new(WebEpoch::new()),
            state: RwLock::new(State::default()),
            reads: Arc::new(WebReadBudget::new(WebReadLimits::default())?),
            #[cfg(test)]
            fail_after_head: AtomicBool::new(false),
        })
    }
}
#[derive(Default, Clone)]
struct State {
    enabled: bool,
    entries: BTreeMap<PublicationId, Entry>,
    receipts: VecDeque<WebOperationReceipt>,
    // Interrupted revision writes retain a finite charge, without acquiring a
    // fabricated publication identity or being confused with current evidence.
    evidence_bytes: u64,
    evidence_directories: usize,
    head_bytes: usize,
}
#[derive(Clone)]
struct Entry {
    record: WebLifecycleRecord,
    completion: ArtifactBlobDigest,
    layout: Arc<CheckedWebLayout>,
    grant: Option<Arc<dyn WebAdmissionGrant>>,
    generation: Arc<WebGeneration>,
}
impl Entry {
    fn retained_bytes(&self) -> Result<usize, PlatformError> {
        let encoded = persistence::encode_line(
            &self.record,
            crate::LifecycleLimits::default().max_record_bytes,
        )?;
        encoded
            .len()
            .checked_mul(4)
            .and_then(|n| n.checked_add(2048))
            .and_then(|n| n.checked_add(self.layout.retained_bytes()))
            .and_then(|n| {
                n.checked_add(
                    self.grant
                        .as_ref()
                        .map_or(0, |grant| grant.retained_bytes()),
                )
            })
            .ok_or_else(capacity)
    }
}
impl State {
    fn retained_bytes(&self) -> Result<usize, PlatformError> {
        let mut bytes = 4096usize;
        for entry in self.entries.values() {
            bytes = bytes
                .checked_add(entry.retained_bytes()?)
                .ok_or_else(capacity)?;
        }
        for receipt in &self.receipts {
            let size = persistence::encode_line(
                receipt,
                crate::LifecycleLimits::default().max_receipt_bytes,
            )?
            .len();
            bytes = bytes
                .checked_add(
                    size.checked_mul(4)
                        .and_then(|n| n.checked_add(1024))
                        .ok_or_else(capacity)?,
                )
                .ok_or_else(capacity)?;
        }
        Ok(bytes)
    }
    fn entry(&self, reference: &PublicationRef) -> Result<&Entry, PlatformError> {
        reference.scope.validate()?;
        self.entries
            .get(&reference.id)
            .filter(|entry| entry.record.publication == *reference)
            .ok_or_else(|| error(PlatformErrorCode::NotFound, "web-publication-not-found"))
    }
    fn check_receipt(
        &self,
        candidate: &WebOperationReceipt,
    ) -> Result<Option<WebMutationResult>, PlatformError> {
        if let Some(old) = self.receipts.iter().find(|old| {
            old.publication.scope == candidate.publication.scope
                && old.operation_id == candidate.operation_id
        }) {
            if old.request_digest != candidate.request_digest {
                return Err(error(
                    PlatformErrorCode::StateConflict,
                    "web-operation-id-conflict",
                ));
            }
            return Ok(Some(WebMutationResult {
                receipt: old.clone(),
                replay: true,
            }));
        }
        Ok(None)
    }
}
impl DirectoryArtifactRepository {
    fn web_path(&self) -> PathBuf {
        self.root.join(DIRECTORY)
    }
    fn web_publication_path(&self, id: &PublicationId) -> PathBuf {
        self.web_path().join(PUBLICATIONS).join(id.hex())
    }
    fn web_authority(&self) -> Result<&admission::RepositoryAdmission, PlatformError> {
        self.admission.as_ref().ok_or_else(|| {
            error(
                PlatformErrorCode::PermissionDenied,
                "web-requires-enforced-admission",
            )
        })
    }
    fn check_web_grant(
        &self,
        tenant: &TenantId,
        value: &VerifiedWebAdmission,
    ) -> Result<(), PlatformError> {
        let config = self.web_authority()?;
        storage::check_binding(value.grant.binding(), config.limits)?;
        if &value.grant.binding().tenant != tenant
            || value.grant.retained_bytes() > config.limits.max_grant_bytes
        {
            return Err(corrupt("web-admission-grant-association"));
        }
        value.grant.with_current(&mut |check| check.check())
    }
    fn web_storage(&self, reference: &PublicationRef) -> Result<storage::Stored, PlatformError> {
        let record = storage::Stored::read(
            &self.web_publication_path(&reference.id),
            self.web_authority()?.limits,
            self.config.max_component_bytes,
        )?;
        if record.publication != *reference {
            return Err(corrupt("web-storage-scope"));
        }
        Ok(record)
    }
}
fn capacity() -> PlatformError {
    resource_exhausted("web-catalog-capacity")
}
fn busy() -> PlatformError {
    error(
        PlatformErrorCode::Unavailable,
        "web-catalog-busy-or-reopen-required",
    )
}
fn denied() -> PlatformError {
    error(
        PlatformErrorCode::PermissionDenied,
        "web-publication-ineligible",
    )
}
