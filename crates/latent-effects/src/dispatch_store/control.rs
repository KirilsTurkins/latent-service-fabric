//! Bounded node-control receipts in the dispatcher's existing engine. These
//! records describe original acceptance; they never grant operator authority.

use latent_state::embedded::{
    AtomicBatch, EmbeddedStore, ExpectedRow, Family, ReadView, RowKey, RowMutation, StoreError,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::authority::EffectTime;
use crate::runtime::control::{
    DispatcherControlAction, DispatcherControlError, DispatcherControlGeneration,
    DispatcherControlRequest,
};

use super::codec::OwnerRecord;

pub const CONTROL_STATE_KEY: &[u8] = b"dispatch-control-v1\0";
pub const CONTROL_RECEIPT_PREFIX: &[u8] = b"dispatch-control-receipt-v1\0";
const FORMAT: &[u8; 5] = b"LDC\0\x01";
const MAXIMUM_RECEIPT_BYTES: usize = 4096;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct DispatcherControlReceipt {
    request: DispatcherControlRequest,
    generation: DispatcherControlGeneration,
    observed_at_millis: u64,
    clock_continuity_proven: bool,
    restore_review: bool,
}

impl DispatcherControlReceipt {
    #[must_use]
    pub const fn request(&self) -> &DispatcherControlRequest {
        &self.request
    }
    #[must_use]
    pub const fn generation(&self) -> DispatcherControlGeneration {
        self.generation
    }
    #[must_use]
    pub const fn observed_at_millis(&self) -> u64 {
        self.observed_at_millis
    }
    #[must_use]
    pub const fn clock_continuity_proven(&self) -> bool {
        self.clock_continuity_proven
    }
    #[must_use]
    pub const fn restore_review(&self) -> bool {
        self.restore_review
    }

    fn validate(&self) -> Result<(), StoreError> {
        self.request.validate().map_err(|_| StoreError::Invalid)?;
        if self
            .request
            .expected()
            .next()
            .map_err(|_| StoreError::Invalid)?
            != self.generation
            || (self.request.action() == DispatcherControlAction::Resume
                && (!self.clock_continuity_proven || self.restore_review))
        {
            return Err(StoreError::Invalid);
        }
        Ok(())
    }

    fn encode(&self) -> Result<Vec<u8>, StoreError> {
        self.validate()?;
        let body = serde_json::to_vec(self).map_err(|_| StoreError::Invalid)?;
        if body.len() > MAXIMUM_RECEIPT_BYTES - FORMAT.len() {
            return Err(StoreError::Capacity);
        }
        let mut bytes = Vec::with_capacity(FORMAT.len() + body.len());
        bytes.extend_from_slice(FORMAT);
        bytes.extend_from_slice(&body);
        Ok(bytes)
    }

    fn decode(bytes: &[u8]) -> Result<Self, StoreError> {
        if !bytes.starts_with(FORMAT) {
            return Err(StoreError::UnsupportedFormat);
        }
        if bytes.len() > MAXIMUM_RECEIPT_BYTES {
            return Err(StoreError::Capacity);
        }
        let receipt: Self =
            serde_json::from_slice(&bytes[FORMAT.len()..]).map_err(|_| StoreError::Corrupt)?;
        receipt.validate().map_err(|_| StoreError::Corrupt)?;
        Ok(receipt)
    }
}

pub(crate) enum PlannedControl {
    Write {
        batch: AtomicBatch,
        receipt: DispatcherControlReceipt,
    },
    Replay(DispatcherControlReceipt),
}

/// All physical reads/writes run inside `ProtectedStoreOwner`'s fixed workers.
/// This catalog owns no Arc<EmbeddedStore>, raw native view or independent DB.
pub struct ControlCatalog;

impl ControlCatalog {
    pub(crate) fn plan(
        store: &EmbeddedStore,
        request: &DispatcherControlRequest,
        restore_review: bool,
        time: EffectTime,
    ) -> Result<PlannedControl, DispatcherControlError> {
        request.validate()?;
        let view = store.snapshot()?;
        if let Some(receipt) = Self::lookup(&view, request)? {
            return Ok(PlannedControl::Replay(receipt));
        }
        let owner_key = OwnerRecord::key();
        let owner_bytes = view.get(&owner_key)?.ok_or(StoreError::Corrupt)?;
        let mut owner = OwnerRecord::decode(&owner_bytes)?;
        if owner.epoch != request.expected().owner_epoch() {
            return Err(DispatcherControlError::Conflict);
        }
        if request.action() == DispatcherControlAction::Resume {
            owner
                .observe(time)
                .map_err(|_| DispatcherControlError::ClockDiscontinuity)?;
            if restore_review {
                return Err(DispatcherControlError::RestoreReviewRequired);
            }
        }
        let state_key = state_key();
        let state_bytes = view.get(&state_key)?;
        if let Some(previous) = state_bytes.as_deref() {
            let previous = DispatcherControlReceipt::decode(previous)?;
            if previous.generation().owner_epoch() > owner.epoch
                || (previous.generation().owner_epoch() == owner.epoch
                    && previous.generation().revision() > request.expected().revision())
            {
                return Err(DispatcherControlError::Conflict);
            }
        }
        let receipt = DispatcherControlReceipt {
            request: request.clone(),
            generation: request.expected().next()?,
            observed_at_millis: time.unix_millis,
            clock_continuity_proven: time.continuity_proven,
            restore_review,
        };
        let encoded = receipt.encode()?;
        let receipt_key = receipt_key(request);
        drop(view);
        Ok(PlannedControl::Write {
            batch: AtomicBatch {
                expectations: vec![
                    ExpectedRow {
                        key: owner_key.clone(),
                        value: Some(owner_bytes),
                    },
                    ExpectedRow {
                        key: state_key.clone(),
                        value: state_bytes,
                    },
                    ExpectedRow {
                        key: receipt_key.clone(),
                        value: None,
                    },
                ],
                mutations: vec![
                    RowMutation {
                        key: owner_key,
                        value: Some(owner.encode()?),
                    },
                    RowMutation {
                        key: state_key,
                        value: Some(encoded.clone()),
                    },
                    RowMutation {
                        key: receipt_key,
                        value: Some(encoded),
                    },
                ],
            },
            receipt,
        })
    }

    /// The exact original actor/ID/action/precondition must match. Knowing an
    /// operation ID is not permission to call this or release its receipt.
    pub fn lookup(
        view: &ReadView,
        request: &DispatcherControlRequest,
    ) -> Result<Option<DispatcherControlReceipt>, StoreError> {
        request.validate().map_err(|_| StoreError::Invalid)?;
        let Some(bytes) = view.get(&receipt_key(request))? else {
            return Ok(None);
        };
        let receipt = DispatcherControlReceipt::decode(&bytes)?;
        if receipt.request() != request {
            return Err(StoreError::Conflict);
        }
        Ok(Some(receipt))
    }

    pub(crate) fn startup(
        view: &ReadView,
        owner_epoch: u64,
    ) -> Result<Option<(bool, bool)>, StoreError> {
        let Some(bytes) = view.get(&state_key())? else {
            return Ok(None);
        };
        let receipt = DispatcherControlReceipt::decode(&bytes)?;
        if receipt.generation().owner_epoch() >= owner_epoch {
            return Err(StoreError::Corrupt);
        }
        Ok(Some((
            receipt.request().action() == DispatcherControlAction::Pause,
            receipt.restore_review(),
        )))
    }

    pub fn validate_row(key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        if key.family != Family::Maintenance
            || (key.key != CONTROL_STATE_KEY && !key.key.starts_with(CONTROL_RECEIPT_PREFIX))
        {
            return Err(StoreError::UnsupportedFormat);
        }
        let receipt = DispatcherControlReceipt::decode(bytes)?;
        if key.key != CONTROL_STATE_KEY && *key != receipt_key(receipt.request()) {
            return Err(StoreError::Corrupt);
        }
        Ok(())
    }

    pub fn validate_view(view: &ReadView) -> Result<(), StoreError> {
        let owner = view
            .get(&OwnerRecord::key())?
            .as_deref()
            .map(OwnerRecord::decode)
            .transpose()?;
        if let Some(bytes) = view.get(&state_key())? {
            let receipt = DispatcherControlReceipt::decode(&bytes)?;
            if owner.is_none_or(|owner| owner.epoch < receipt.generation().owner_epoch())
                || Self::lookup(view, receipt.request())?.as_ref() != Some(&receipt)
            {
                return Err(StoreError::Corrupt);
            }
        }
        let mut after = None;
        loop {
            let page = view.scan_after(
                Family::Maintenance,
                CONTROL_RECEIPT_PREFIX,
                after.as_deref(),
                128,
                1024 * 1024,
            )?;
            for (key, bytes) in page.rows {
                Self::validate_row(&key, &bytes)?;
                let receipt = DispatcherControlReceipt::decode(&bytes)?;
                if owner.is_none_or(|owner| owner.epoch < receipt.generation().owner_epoch()) {
                    return Err(StoreError::Corrupt);
                }
            }
            after = page.resume;
            if after.is_none() {
                return Ok(());
            }
        }
    }
}

fn state_key() -> RowKey {
    RowKey {
        family: Family::Maintenance,
        key: CONTROL_STATE_KEY.to_vec(),
    }
}

fn receipt_key(request: &DispatcherControlRequest) -> RowKey {
    let mut hasher = Sha256::new();
    hasher.update(b"latent.dispatcher-control-operation.v1\0");
    for value in [
        request.actor_tenant(),
        request.actor_subject(),
        request.operation_id(),
    ] {
        // Every input has been bounded to 256 bytes before this port is used.
        hasher.update((value.len() as u64).to_be_bytes());
        hasher.update(value.as_bytes());
    }
    let mut key = Vec::with_capacity(CONTROL_RECEIPT_PREFIX.len() + 32);
    key.extend_from_slice(CONTROL_RECEIPT_PREFIX);
    key.extend_from_slice(&hasher.finalize());
    RowKey {
        family: Family::Maintenance,
        key,
    }
}
