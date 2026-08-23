use super::errors::sequence_exhausted;
use super::state::PoolInner;
use super::{FixedCellPoolConfig, DROPPED_LEASE_REASON};
use crate::{CellClass, CellLease};
use latent_core::{ActivationId, CellId, NodeId, PlatformError, ResourceBudget, TenantId};
use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::Weak;
use tokio::sync::oneshot;

pub(super) enum Reservation {
    Immediate(CellLease),
    Queued {
        waiter_id: u64,
        activation_id: ActivationId,
        receiver: oneshot::Receiver<Result<PendingGrant, PlatformError>>,
    },
}

pub(super) struct PoolState {
    pub(super) idle: VecDeque<IdleCell>,
    pub(super) active: HashMap<ActivationId, LeaseIdentity>,
    pub(super) waiters: VecDeque<Waiter>,
    pub(super) waiting_by_activation: HashMap<ActivationId, u64>,
    pub(super) quarantined: HashMap<CellId, QuarantinedCell>,
    pub(super) next_waiter_id: u64,
    pub(super) next_lease_token: u64,
}

impl PoolState {
    pub(super) fn take_waiter_id(&mut self) -> Result<u64, PlatformError> {
        let current = self.next_waiter_id;
        self.next_waiter_id = current.checked_add(1).ok_or_else(sequence_exhausted)?;
        Ok(current)
    }

    pub(super) fn take_lease_token(&mut self) -> Result<u64, PlatformError> {
        let current = self.next_lease_token;
        self.next_lease_token = current.checked_add(1).ok_or_else(sequence_exhausted)?;
        Ok(current)
    }

    pub(super) fn assert_invariants(&self, config: &FixedCellPoolConfig) {
        debug_assert_eq!(
            self.idle.len() + self.active.len() + self.quarantined.len(),
            usize::try_from(config.capacity).expect("u32 capacity fits usize"),
            "fixed cell capacity changed"
        );
        debug_assert_eq!(
            self.waiters.len(),
            self.waiting_by_activation.len(),
            "waiter indexes diverged"
        );
        let configured_capacity =
            usize::try_from(config.capacity).expect("u32 capacity fits usize");
        let cell_ids: HashSet<&CellId> = self
            .idle
            .iter()
            .map(|cell| &cell.id)
            .chain(self.active.values().map(|identity| &identity.cell.id))
            .chain(self.quarantined.keys())
            .collect();
        debug_assert_eq!(cell_ids.len(), configured_capacity, "cell slots duplicated");
        debug_assert!(self
            .active
            .iter()
            .all(|(activation_id, identity)| activation_id == &identity.activation_id));
        debug_assert!(self
            .quarantined
            .iter()
            .all(|(cell_id, quarantined)| cell_id == &quarantined.cell.id));
        debug_assert!(self.waiters.iter().all(|waiter| {
            self.waiting_by_activation.get(&waiter.activation_id) == Some(&waiter.id)
        }));
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct IdleCell {
    pub(super) id: CellId,
    pub(super) generation: u64,
}

#[derive(Debug, Clone)]
pub(super) struct LeaseIdentity {
    pub(super) token: u64,
    pub(super) cell: IdleCell,
    pub(super) activation_id: ActivationId,
    pub(super) tenant: TenantId,
    pub(super) node: NodeId,
    pub(super) class: CellClass,
    pub(super) granted_budget: ResourceBudget,
    pub(super) expires_at_unix_millis: u64,
}

impl LeaseIdentity {
    pub(super) fn matches_active(&self, other: &Self) -> bool {
        self.token == other.token
            && self.cell == other.cell
            && self.activation_id == other.activation_id
            && self.tenant == other.tenant
            && self.node == other.node
            && self.class == other.class
            && self.granted_budget == other.granted_budget
            && self.expires_at_unix_millis == other.expires_at_unix_millis
    }

    pub(super) fn matches_visible(&self, lease: &CellLease) -> bool {
        self.cell.id == lease.id
            && self.activation_id == lease.activation_id
            && self.node == lease.node
            && self.class == lease.class
            && self.granted_budget == lease.granted_budget
            && self.expires_at_unix_millis == lease.expires_at_unix_millis
    }
}

pub(super) struct LeaseRequest {
    pub(super) activation_id: ActivationId,
    pub(super) tenant: TenantId,
    pub(super) budget: ResourceBudget,
    pub(super) deadline: Option<u64>,
}

pub(super) struct Waiter {
    pub(super) id: u64,
    pub(super) activation_id: ActivationId,
    pub(super) tenant: TenantId,
    pub(super) budget: ResourceBudget,
    pub(super) deadline: Option<u64>,
    pub(super) sender: oneshot::Sender<Result<PendingGrant, PlatformError>>,
}

#[derive(Debug)]
pub(super) struct QuarantinedCell {
    pub(super) cell: IdleCell,
    pub(super) _reason: String,
}

pub(crate) struct LeaseControl {
    pub(super) owner: Weak<PoolInner>,
    pub(super) identity: LeaseIdentity,
}

impl LeaseControl {
    pub(super) fn reclaim_unaccepted(self) {
        if let Some(owner) = self.owner.upgrade() {
            let _ = owner.finish_lease(self.identity, LeaseDisposition::Reusable);
        }
    }

    pub(super) fn quarantine_dropped(self) {
        if let Some(owner) = self.owner.upgrade() {
            let _ = owner.finish_lease(
                self.identity,
                LeaseDisposition::Quarantine(DROPPED_LEASE_REASON.to_owned()),
            );
        }
    }
}

#[derive(Debug)]
pub(super) enum LeaseDisposition {
    Reusable,
    Quarantine(String),
}

pub(super) struct PendingGrant {
    lease: Option<CellLease>,
}

impl PendingGrant {
    pub(super) fn new(lease: CellLease) -> Self {
        Self { lease: Some(lease) }
    }

    pub(super) fn accept(mut self) -> CellLease {
        self.lease.take().expect("pending grant contains one lease")
    }
}

impl Drop for PendingGrant {
    fn drop(&mut self) {
        if let Some(mut lease) = self.lease.take() {
            lease.reclaim_unaccepted();
        }
    }
}

pub(super) enum Delivery {
    Grant {
        sender: oneshot::Sender<Result<PendingGrant, PlatformError>>,
        grant: PendingGrant,
    },
    Error {
        sender: oneshot::Sender<Result<PendingGrant, PlatformError>>,
        error: PlatformError,
    },
}

pub(super) fn deliver(deliveries: Vec<Delivery>) {
    for delivery in deliveries {
        match delivery {
            Delivery::Grant { sender, grant } => {
                if let Err(result) = sender.send(Ok(grant)) {
                    if let Ok(grant) = result {
                        drop(grant);
                    }
                }
            }
            Delivery::Error { sender, error } => {
                let _ = sender.send(Err(error));
            }
        }
    }
}

pub(super) struct WaitRegistration {
    owner: Weak<PoolInner>,
    waiter_id: u64,
    activation_id: ActivationId,
    armed: bool,
}

impl WaitRegistration {
    pub(super) fn new(owner: Weak<PoolInner>, waiter_id: u64, activation_id: ActivationId) -> Self {
        Self {
            owner,
            waiter_id,
            activation_id,
            armed: true,
        }
    }

    pub(super) fn disarm(&mut self) {
        self.armed = false;
    }

    pub(super) fn expire(&mut self) {
        if self.armed {
            if let Some(owner) = self.owner.upgrade() {
                owner.remove_waiter(self.waiter_id, &self.activation_id);
            }
            self.armed = false;
        }
    }
}

impl Drop for WaitRegistration {
    fn drop(&mut self) {
        if self.armed {
            if let Some(owner) = self.owner.upgrade() {
                owner.remove_waiter(self.waiter_id, &self.activation_id);
            }
        }
    }
}
