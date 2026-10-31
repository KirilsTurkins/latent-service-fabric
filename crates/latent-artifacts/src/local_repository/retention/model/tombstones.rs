//! Bounded deletion authority in the same durable HEAD as rollback pins.
use super::{capacity, conflict, corrupt, encode, Head, PlatformError, MAX_HEAD, MAX_REQUEST};
use crate::{
    LifecycleScope, PublicationDeletionReceipt, PublicationDeletionRequest,
    PublicationDeletionStage, PublicationRetentionFence, PublicationRetentionTarget,
    MAX_PUBLICATION_DELETION_RECEIPTS, MAX_PUBLICATION_TOMBSTONES,
};
use latent_core::PublicationId;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(in crate::local_repository::retention) struct Tombstone {
    pub target: PublicationRetentionTarget,
    pub operation_id: String,
    pub revision: u64,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(in crate::local_repository::retention) struct DeletionHistory {
    pub revision: u64,
    pub tombstones: Vec<Tombstone>,
    pub receipts: Vec<PublicationDeletionReceipt>,
}
impl DeletionHistory {
    pub fn contains(&self, id: &PublicationId) -> bool {
        self.tombstones
            .binary_search_by(|t| t.target.publication.id.cmp(id))
            .is_ok()
    }
    pub fn validate(&self) -> Result<(), PlatformError> {
        if self.revision == 0
            || self.tombstones.is_empty()
            || self.tombstones.len() > MAX_PUBLICATION_TOMBSTONES
            || self.receipts.is_empty()
            || self.receipts.len() > MAX_PUBLICATION_DELETION_RECEIPTS
            || self
                .tombstones
                .windows(2)
                .any(|t| t[0].target.publication.id >= t[1].target.publication.id)
        {
            return Err(corrupt());
        }
        let mut operations = std::collections::BTreeMap::new();
        let mut revisions = std::collections::BTreeMap::new();
        for tombstone in &self.tombstones {
            tombstone
                .target
                .publication
                .scope
                .validate()
                .map_err(|_| corrupt())?;
            crate::publication_retention::token(&tombstone.operation_id).map_err(|_| corrupt())?;
            if tombstone.target.expected_generation == 0
                || tombstone.revision == 0
                || tombstone.revision > self.revision
            {
                return Err(corrupt());
            }
            let key = (&tombstone.target.publication.scope, &tombstone.operation_id);
            if operations
                .insert(key, tombstone.revision)
                .is_some_and(|old| old != tombstone.revision)
            {
                return Err(corrupt());
            }
            let (owner, count) = revisions.entry(tombstone.revision).or_insert((key, 0usize));
            if *owner != key || *count >= crate::MAX_PUBLICATION_RETENTION_BATCH {
                return Err(corrupt());
            }
            *count += 1;
        }
        if revisions.len() as u64 != self.revision {
            return Err(corrupt());
        }
        let start = self
            .revision
            .checked_sub(self.receipts.len() as u64)
            .ok_or_else(corrupt)?;
        for (index, receipt) in self.receipts.iter().enumerate() {
            receipt.request.validate().map_err(|_| corrupt())?;
            encode(&receipt.request, MAX_REQUEST).map_err(|_| corrupt())?;
            if receipt.revision != start + index as u64 + 1 {
                return Err(corrupt());
            }
            let targets: Vec<_> = self
                .tombstones
                .iter()
                .filter(|t| t.revision == receipt.revision)
                .collect();
            if targets.len() != receipt.request.targets.len()
                || targets
                    .iter()
                    .zip(&receipt.request.targets)
                    .any(|(saved, target)| {
                        saved.target != *target
                            || saved.operation_id != receipt.request.operation_id
                    })
            {
                return Err(corrupt());
            }
        }
        Ok(())
    }
}
impl Head {
    pub fn deletion_receipt(
        &self,
        scope: &LifecycleScope,
        id: &str,
    ) -> Option<&PublicationDeletionReceipt> {
        self.deletion
            .as_ref()?
            .receipts
            .iter()
            .find(|r| r.request.scope == *scope && r.request.operation_id == id)
    }
    pub fn next_deletion(
        &self,
        request: &PublicationDeletionRequest,
        reference_revision: u64,
    ) -> Result<Self, PlatformError> {
        request.validate()?;
        encode(request, MAX_REQUEST)?;
        let mut next = self.clone();
        let history = next.deletion.get_or_insert(DeletionHistory {
            revision: 0,
            tombstones: Vec::new(),
            receipts: Vec::new(),
        });
        if history
            .tombstones
            .len()
            .checked_add(request.targets.len())
            .is_none_or(|n| n > MAX_PUBLICATION_TOMBSTONES)
        {
            return Err(capacity());
        }
        // Even after receipt eviction, an operation ID cannot name a different
        // batch or supply a fresh replay precondition.
        if history.tombstones.iter().any(|t| {
            t.target.publication.scope == request.scope && t.operation_id == request.operation_id
        }) {
            return Err(conflict());
        }
        history.revision = history.revision.checked_add(1).ok_or_else(capacity)?;
        for target in &request.targets {
            if self.pin(&target.publication)?.is_some() {
                return Err(conflict());
            }
            let position = history
                .tombstones
                .binary_search_by(|t| t.target.publication.id.cmp(&target.publication.id))
                .err()
                .ok_or_else(conflict)?;
            history.tombstones.insert(
                position,
                Tombstone {
                    target: target.clone(),
                    operation_id: request.operation_id.clone(),
                    revision: history.revision,
                },
            );
        }
        if history.receipts.len() == MAX_PUBLICATION_DELETION_RECEIPTS {
            history.receipts.remove(0);
        }
        history.receipts.push(PublicationDeletionReceipt {
            request: request.clone(),
            revision: history.revision,
            reference_revision,
            stage: PublicationDeletionStage::VisibilityRemoved,
        });
        next.validate(self.mode)?;
        encode(&next, MAX_HEAD)?;
        Ok(next)
    }
    /// Reconstruct exactly one authorized transition. Neither a changed pin set
    /// nor a mixed pin/deletion transition can be laundered through recovery.
    pub fn successor_fence(&self, next: &Self) -> Result<PublicationRetentionFence, PlatformError> {
        if self.deletion == next.deletion {
            let receipt = next.receipts.last().ok_or_else(corrupt)?;
            if self.next(&receipt.request).map_err(|_| corrupt())? != *next {
                return Err(corrupt());
            }
            Ok(receipt.request.expected_catalog_fence)
        } else {
            let receipt = next
                .deletion
                .as_ref()
                .and_then(|d| d.receipts.last())
                .ok_or_else(corrupt)?;
            if self
                .next_deletion(&receipt.request, receipt.reference_revision)
                .map_err(|_| corrupt())?
                != *next
            {
                return Err(corrupt());
            }
            Ok(receipt.request.expected_catalog_fence)
        }
    }
}
