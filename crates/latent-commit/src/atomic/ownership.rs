//! Physical executor/commit/cleanup guards. A deadline or dropped caller never
//! retires one. Unretired guards quarantine the attempt and cannot mint abort proof.

use super::{AdmittedCommand, AtomicError, CommandRecord};
use latent_state::{
    embedded::ReadView,
    namespace::catalog::{NamespaceCatalog, NamespaceRead},
};
use std::sync::{
    atomic::{AtomicBool, AtomicU8, AtomicUsize, Ordering},
    Arc,
};
pub(super) const OPEN: u8 = 0;
pub(super) const ACCEPTED: u8 = 1;
pub(super) const TERMINAL: u8 = 2;
pub(super) const UNKNOWN: u8 = 3;
pub(super) struct AttemptState {
    pub record: CommandRecord,
    pub expected: Vec<u8>,
    pub owners: AtomicUsize,
    pub phase: AtomicU8,
    pub quarantined: AtomicBool,
}
impl AttemptState {
    pub fn new(record: CommandRecord, expected: Vec<u8>) -> Arc<Self> {
        Arc::new(Self {
            record,
            expected,
            owners: AtomicUsize::new(1),
            phase: AtomicU8::new(OPEN),
            quarantined: AtomicBool::new(false),
        })
    }
}
#[derive(Clone)]
pub struct AttemptRetirement {
    pub(super) state: Arc<AttemptState>,
}
pub struct RetiredAttempt {
    pub(super) record: CommandRecord,
    pub(super) expected: Vec<u8>,
}
impl RetiredAttempt {
    /// Association with the exact original record is descriptive only. This
    /// cannot create retirement, resume work, prove a commit or grant a retry.
    #[must_use]
    pub fn matches_original(&self, record: &CommandRecord) -> bool {
        &self.record == record
    }
}
pub struct PhysicalAttemptWork {
    state: Arc<AttemptState>,
    retired: bool,
}

/// A coherent observation from the actual claimed attempt's protected reader.
/// It owns no physical work, grant, writer, retry or retirement permission.
/// Rebinding still requires the live affine claim and original sealed authority.
pub struct CurrentClaimNamespace {
    state: Arc<AttemptState>,
    namespace: NamespaceRead,
}
impl CurrentClaimNamespace {
    #[must_use]
    pub fn namespace(&self) -> &NamespaceRead {
        &self.namespace
    }

    #[must_use]
    pub fn matches_claim(&self, claim: &AdmittedCommand) -> bool {
        Arc::ptr_eq(&self.state, &claim.physical)
            && self.state.record == claim.record
            && self.state.expected == claim.expected
            && self.state.phase.load(Ordering::Acquire) == OPEN
            && !self.state.quarantined.load(Ordering::Acquire)
    }

    #[must_use]
    pub fn into_namespace(self) -> NamespaceRead {
        self.namespace
    }
}
impl AdmittedCommand {
    #[must_use]
    pub fn retirement(&self) -> AttemptRetirement {
        AttemptRetirement {
            state: Arc::clone(&self.physical),
        }
    }
    /// Move this affine guard into the actual executor/cleanup/store work item.
    /// Taking it or observing it is not proof of resource reservation elsewhere.
    pub fn physical_work(&self) -> Result<PhysicalAttemptWork, AtomicError> {
        self.physical
            .owners
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |owners| {
                if (1..8).contains(&owners) {
                    Some(owners + 1)
                } else {
                    None
                }
            })
            .map_err(|_| AtomicError::Limit)?;
        Ok(PhysicalAttemptWork {
            state: Arc::clone(&self.physical),
            retired: false,
        })
    }
}
impl AttemptRetirement {
    /// Positive physical retirement is independent of durable disposition.
    /// This does not prove abort, noncommit, replay safety or retry permission.
    #[must_use]
    pub fn physically_retired(&self) -> bool {
        self.state.owners.load(Ordering::Acquire) == 0
            && !self.state.quarantined.load(Ordering::Acquire)
    }

    pub fn proven_noncommit(&self) -> Result<RetiredAttempt, AtomicError> {
        if self.state.owners.load(Ordering::Acquire) != 0
            || self.state.quarantined.load(Ordering::Acquire)
            || self.state.phase.load(Ordering::Acquire) != OPEN
        {
            return Err(AtomicError::RecoveryRequired);
        }
        Ok(RetiredAttempt {
            record: self.state.record.clone(),
            expected: self.state.expected.clone(),
        })
    }
}
impl PhysicalAttemptWork {
    /// Charge both bounded command comparisons and the namespace descriptor
    /// before reading. The original native/host reservation still owns these
    /// bytes; no production quota or per-job maximum changes.
    #[must_use]
    pub fn namespace_observation_bytes(&self) -> u64 {
        self.state.expected.len() as u64 * 2 + 8192
    }

    /// Only the actual worker can make this observation. It must retain this
    /// affine work through the view's destruction, then positively retire it.
    pub fn observe_claim_namespace(
        &self,
        view: &ReadView,
    ) -> Result<CurrentClaimNamespace, AtomicError> {
        if self.retired
            || self.state.phase.load(Ordering::Acquire) != OPEN
            || self.state.quarantined.load(Ordering::Acquire)
        {
            return Err(AtomicError::RecoveryRequired);
        }
        let record = &self.state.record;
        for key in [
            super::record::command_row_key(record.id()),
            super::record::attempt_row_key(record.id(), record.attempt()),
        ] {
            if view
                .get_bounded(&key, self.state.expected.len())?
                .as_deref()
                != Some(self.state.expected.as_slice())
            {
                return Err(AtomicError::Conflict);
            }
        }
        let namespace = NamespaceCatalog::read_in(
            view,
            &latent_core::TenantId(record.key().tenant.clone()),
            &latent_core::StateNamespaceId(record.key().namespace.clone()),
        )
        .map_err(|_| AtomicError::Corrupt)?
        .ok_or(AtomicError::NotFound)?;
        if namespace.record().version.incarnation.to_string() != record.key().incarnation
            || namespace.record().state_schema != record.source().state_schema
        {
            return Err(AtomicError::Conflict);
        }
        Ok(CurrentClaimNamespace {
            state: Arc::clone(&self.state),
            namespace,
        })
    }

    /// Invoke only after the physical executor, IO or cleanup operation has
    /// completed. A cancelled waiter cannot call it on the worker's guard.
    pub fn retire(mut self) {
        self.retired = true;
        self.state.owners.fetch_sub(1, Ordering::AcqRel);
    }
}
impl Drop for PhysicalAttemptWork {
    fn drop(&mut self) {
        if !self.retired {
            self.state.quarantined.store(true, Ordering::Release);
        }
    }
}
impl Drop for AdmittedCommand {
    fn drop(&mut self) {
        self.physical.owners.fetch_sub(1, Ordering::AcqRel);
    }
}
