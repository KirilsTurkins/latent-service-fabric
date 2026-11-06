//! Durable authorization for bounded physical cleanup. No content is inferred
//! from missing files: every absence must belong to this exact committed plan.
use super::{capacity, conflict, corrupt, encode, Head, PlatformError, MAX_HEAD};
use crate::lifecycle::LifecycleIdentity;
use crate::local_repository::shared_content::reclamation::ContentPlan;
use crate::local_repository::web::cleanup::WebCleanupIdentity;
use crate::{
    LifecycleScope, PublicationReclamationReceipt, PublicationReclamationRequest,
    PublicationRetentionFence, MAX_PUBLICATION_DELETION_RECEIPTS, MAX_PUBLICATION_TOMBSTONES,
};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(in crate::local_repository) struct Plan {
    pub request: PublicationReclamationRequest,
    pub reference_revision: u64,
    pub identities: Vec<LifecycleIdentity>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub web_identities: Vec<WebCleanupIdentity>,
    pub files: ContentPlan,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(in crate::local_repository) struct Cleanup {
    pub revision: u64,
    pub fence: PublicationRetentionFence,
    pub identities: Vec<LifecycleIdentity>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub web_identities: Vec<WebCleanupIdentity>,
    pub active: Option<Plan>,
    pub receipts: Vec<PublicationReclamationReceipt>,
}
impl Cleanup {
    pub fn receipt(
        &self,
        scope: &LifecycleScope,
        id: &str,
    ) -> Option<&PublicationReclamationReceipt> {
        self.receipts
            .iter()
            .find(|r| r.request.deletion.scope == *scope && r.request.deletion.operation_id == id)
    }
    pub fn validate(&self, head: &Head) -> Result<(), PlatformError> {
        if self.revision == 0
            || (self.identities.is_empty() && self.web_identities.is_empty())
            || self
                .identities
                .len()
                .saturating_add(self.web_identities.len())
                > MAX_PUBLICATION_TOMBSTONES
            || self.receipts.len() > MAX_PUBLICATION_DELETION_RECEIPTS
            || self.revision > 2 * MAX_PUBLICATION_TOMBSTONES as u64
            || (self.active.is_some() != (self.revision % 2 == 1))
            || (self.active.is_none() && self.receipts.is_empty())
        {
            return Err(corrupt());
        }
        let deleted = head.deletion.as_ref().ok_or_else(corrupt)?;
        let mut previous = None;
        for identity in &self.identities {
            let reference = identity.publication().map_err(|_| corrupt())?;
            reference.scope.validate().map_err(|_| corrupt())?;
            if previous.as_ref().is_some_and(|id| id >= &reference.id)
                || !deleted
                    .tombstones
                    .iter()
                    .any(|t| t.target.publication == reference)
            {
                return Err(corrupt());
            }
            previous = Some(reference.id);
        }
        let mut previous_web = None;
        for identity in &self.web_identities {
            identity.validate().map_err(|_| corrupt())?;
            let reference = &identity.record.publication;
            if previous_web.is_some_and(|id| id >= &reference.id)
                || self.identities.iter().any(|i| {
                    i.publication()
                        .ok()
                        .as_ref()
                        .is_some_and(|r| r.id == reference.id)
                })
                || !deleted.tombstones.iter().any(|t| {
                    t.target.publication == *reference
                        && t.target.expected_generation == identity.record.generation
                })
            {
                return Err(corrupt());
            }
            previous_web = Some(&reference.id);
        }
        if let Some(plan) = &self.active {
            plan.validate(head)?;
            if plan.identities.iter().any(|i| !self.identities.contains(i))
                || plan
                    .web_identities
                    .iter()
                    .any(|i| !self.web_identities.contains(i))
            {
                return Err(corrupt());
            }
        }
        let mut ids = std::collections::BTreeSet::new();
        for receipt in &self.receipts {
            receipt.request.validate().map_err(|_| corrupt())?;
            if !ids.insert((
                &receipt.request.deletion.scope,
                &receipt.request.deletion.operation_id,
            )) || self.active.as_ref().is_some_and(|p| {
                p.request.deletion.scope == receipt.request.deletion.scope
                    && p.request.deletion.operation_id == receipt.request.deletion.operation_id
            }) || receipt.request.deletion.targets.iter().any(|t| {
                !self
                    .identities
                    .iter()
                    .any(|i| i.publication().ok().as_ref() == Some(&t.publication))
                    && !self
                        .web_identities
                        .iter()
                        .any(|i| i.record.publication == t.publication)
            }) {
                return Err(corrupt());
            }
            if receipt.request.deletion.targets.iter().any(|target| {
                !deleted.tombstones.iter().any(|t| {
                    t.target == *target && t.operation_id == receipt.request.deletion.operation_id
                })
            }) {
                return Err(corrupt());
            }
            receipt
                .content
                .validate_summary(receipt.request.deletion.targets.len())?;
        }
        Ok(())
    }
}
impl Plan {
    pub fn validate(&self, head: &Head) -> Result<(), PlatformError> {
        self.request.validate().map_err(|_| corrupt())?;
        let receipt = head
            .deletion_receipt(
                &self.request.deletion.scope,
                &self.request.deletion.operation_id,
            )
            .ok_or_else(corrupt)?;
        if receipt.request != self.request.deletion
            || self.identities.len() + self.web_identities.len() != receipt.request.targets.len()
            || self.files.directories.len() != receipt.request.targets.len()
        {
            return Err(corrupt());
        }
        if self
            .identities
            .windows(2)
            .any(|p| p[0].publication().ok().map(|r| r.id) >= p[1].publication().ok().map(|r| r.id))
            || self
                .web_identities
                .windows(2)
                .any(|p| p[0].record.publication.id >= p[1].record.publication.id)
        {
            return Err(corrupt());
        }
        for (directory, target) in self.files.directories.iter().zip(&receipt.request.targets) {
            let capsule = self
                .identities
                .iter()
                .any(|i| i.publication().ok().as_ref() == Some(&target.publication));
            let web = self.web_identities.iter().any(|i| {
                i.record.publication == target.publication
                    && i.record.generation == target.expected_generation
            });
            if directory.id != target.publication.id || capsule == web || directory.web != web {
                return Err(corrupt());
            }
        }
        for identity in &self.web_identities {
            identity.validate().map_err(|_| corrupt())?;
        }
        self.files.validate(self.request.limits)?;
        encode(self, 1024 * 1024)?;
        Ok(())
    }
    pub fn receipt(&self) -> PublicationReclamationReceipt {
        PublicationReclamationReceipt {
            request: self.request.clone(),
            reference_revision: self.reference_revision,
            content: self.files.content,
        }
    }
}
impl Head {
    pub fn begin_cleanup(&self, plan: &Plan) -> Result<Self, PlatformError> {
        plan.validate(self)?;
        let mut next = self.clone();
        let cleanup = next.cleanup.get_or_insert(Cleanup {
            revision: 0,
            fence: plan.request.expected_catalog_fence,
            identities: Vec::new(),
            web_identities: Vec::new(),
            active: None,
            receipts: Vec::new(),
        });
        if cleanup.active.is_some() {
            return Err(conflict());
        }
        for identity in &plan.identities {
            let id = identity.publication()?.id;
            let position = cleanup
                .identities
                .binary_search_by(|i| i.publication().expect("validated identity").id.cmp(&id))
                .err()
                .ok_or_else(conflict)?;
            if cleanup.identities.len() + cleanup.web_identities.len() >= MAX_PUBLICATION_TOMBSTONES
            {
                return Err(capacity());
            }
            cleanup.identities.insert(position, identity.clone());
        }
        for identity in &plan.web_identities {
            let id = &identity.record.publication.id;
            let position = cleanup
                .web_identities
                .binary_search_by(|i| i.record.publication.id.cmp(id))
                .err()
                .ok_or_else(conflict)?;
            if cleanup.identities.len() + cleanup.web_identities.len() >= MAX_PUBLICATION_TOMBSTONES
            {
                return Err(capacity());
            }
            cleanup.web_identities.insert(position, identity.clone());
        }
        cleanup.revision = cleanup.revision.checked_add(1).ok_or_else(capacity)?;
        cleanup.fence = plan.request.expected_catalog_fence;
        cleanup.active = Some(plan.clone());
        next.validate(self.mode)?;
        encode(&next, MAX_HEAD)?;
        Ok(next)
    }
    pub fn finish_cleanup(&self, fence: PublicationRetentionFence) -> Result<Self, PlatformError> {
        let mut next = self.clone();
        let cleanup = next.cleanup.as_mut().ok_or_else(corrupt)?;
        let plan = cleanup.active.take().ok_or_else(corrupt)?;
        if cleanup.receipts.len() == MAX_PUBLICATION_DELETION_RECEIPTS {
            cleanup.receipts.remove(0);
        }
        cleanup.receipts.push(plan.receipt());
        cleanup.revision = cleanup.revision.checked_add(1).ok_or_else(capacity)?;
        cleanup.fence = fence;
        next.validate(self.mode)?;
        encode(&next, MAX_HEAD)?;
        Ok(next)
    }
}
