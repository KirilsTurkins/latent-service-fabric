use std::collections::BTreeMap;
use std::time::{Duration, Instant};

use latent_activation::{ActivationEvent, ActivationStatus};
use latent_core::{
    ActivationId, ActivationPhase, Metadata, PlatformError, PlatformErrorCode, TenantId,
};

use super::{
    capacity, error, ActivationJournalSnapshot, LocalActivationJournalConfig, MAXIMUM_EVENTS,
};

pub(super) struct Record {
    pub tenant: TenantId,
    pub serial: u64,
    pub status: ActivationStatus,
    pub events: Vec<ActivationEvent>,
    pub bytes: usize,
    pub terminal_at: Option<Instant>,
}

impl Record {
    pub fn new(tenant: TenantId, id: &ActivationId, serial: u64, now: u64, bytes: usize) -> Self {
        let mut events = Vec::with_capacity(MAXIMUM_EVENTS);
        events.push(ActivationEvent {
            activation_id: id.clone(),
            phase: ActivationPhase::Received,
            terminal_state: None,
            occurred_at_unix_millis: now,
            sequence: 1,
            attributes: Metadata::new(),
        });
        Self {
            tenant,
            serial,
            events,
            bytes,
            terminal_at: None,
            status: ActivationStatus {
                activation_id: id.clone(),
                phase: ActivationPhase::Received,
                terminal_state: None,
                terminal_outcome: None,
                final_consumption: None,
                last_updated_unix_millis: now,
                terminal_at_unix_millis: None,
                metadata: Metadata::new(),
            },
        }
    }
}

pub(super) struct State {
    // Keep sparse index nodes small: unused B-tree slots contain pointers,
    // rather than reserving a full inline status and outcome for each slot.
    pub records: BTreeMap<ActivationId, Box<Record>>,
    // Ordered by completion, not admission. B-tree nodes are freed on eviction
    // so an empty journal retains no vector's former terminal capacity.
    pub terminal_order: BTreeMap<u64, (ActivationId, u64)>,
    pub next_serial: u64,
    pub snapshot: ActivationJournalSnapshot,
}

impl State {
    pub fn reserve(
        &mut self,
        id: &ActivationId,
        config: LocalActivationJournalConfig,
    ) -> Result<(), PlatformError> {
        if self.records.contains_key(id) {
            return Err(error(
                PlatformErrorCode::AlreadyExists,
                "activation-already-exists",
            ));
        }
        if self.snapshot.active >= config.maximum_active {
            return Err(capacity());
        }
        while self
            .snapshot
            .reserved_bytes
            .checked_add(self.snapshot.retained_bytes)
            .and_then(|total| total.checked_add(config.maximum_record_bytes))
            .is_none_or(|total| total > config.maximum_retained_bytes)
        {
            if !self.evict_oldest() {
                return Err(capacity());
            }
        }
        Ok(())
    }

    pub fn expire(&mut self, now: Instant, retention: Duration) {
        while let Some((_, (id, serial))) = self.terminal_order.first_key_value() {
            let expired = self
                .records
                .get(id)
                .filter(|record| record.serial == *serial)
                .and_then(|record| record.terminal_at)
                .is_none_or(|terminal| now.saturating_duration_since(terminal) >= retention);
            if !expired {
                break;
            }
            self.evict_oldest();
        }
    }

    pub fn evict_oldest(&mut self) -> bool {
        while let Some((_, (id, serial))) = self.terminal_order.pop_first() {
            if self
                .records
                .get(&id)
                .is_some_and(|record| record.serial == serial && record.terminal_at.is_some())
            {
                let record = self.records.remove(&id).expect("matching terminal record");
                self.snapshot.retained_bytes -= record.bytes;
                self.snapshot.terminal -= 1;
                self.snapshot.evicted = self.snapshot.evicted.saturating_add(1);
                return true;
            }
        }
        false
    }
}
