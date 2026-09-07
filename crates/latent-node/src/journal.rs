//! One bounded record per activation, with writes held by its lifecycle owner.

mod bytes;
mod owner;
mod state;
#[cfg(test)]
mod tests;

use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::Duration;

use latent_activation::{ActivationEnvelope, ActivationEvent, ActivationJournal, ActivationStatus};
use latent_core::{
    ActivationClock, ActivationId, BoxFuture, CancelDisposition, PlatformError, PlatformErrorCode,
    TenantId,
};

pub(crate) use owner::{JournalOwner, JournalStamp};
use state::{Record, State};

const MAXIMUM_EVENTS: usize = 7;
const TERMINAL_RESERVE_BYTES: usize = 4096;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LocalActivationJournalConfig {
    pub maximum_active: usize,
    pub maximum_terminal: usize,
    /// One complete history/status allowance, including a terminal outcome.
    pub maximum_record_bytes: usize,
    /// Active records reserve their full allowance; terminal records charge
    /// their measured retained size. This includes conservative bookkeeping.
    pub maximum_retained_bytes: usize,
    pub terminal_retention: Duration,
}

impl Default for LocalActivationJournalConfig {
    fn default() -> Self {
        Self {
            maximum_active: 64,
            maximum_terminal: 1024,
            maximum_record_bytes: 4 * 1024 * 1024,
            maximum_retained_bytes: 256 * 1024 * 1024,
            terminal_retention: Duration::from_mins(5),
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ActivationJournalSnapshot {
    pub active: usize,
    pub terminal: usize,
    pub reserved_bytes: usize,
    pub retained_bytes: usize,
    pub evicted: u64,
    pub begun: u64,
    pub completed: u64,
}

/// Cloneable query handle. Only the manager's affine owner token advances or
/// completes a record. No terminal eviction can remove a live activation.
#[derive(Clone)]
pub struct LocalActivationJournal {
    inner: Arc<Inner>,
}

struct Inner {
    config: LocalActivationJournalConfig,
    clock: Arc<dyn ActivationClock>,
    state: Mutex<State>,
}

impl LocalActivationJournal {
    pub fn new(
        config: LocalActivationJournalConfig,
        clock: Arc<dyn ActivationClock>,
    ) -> Result<Self, PlatformError> {
        if config.maximum_active == 0
            || config.maximum_terminal == 0
            || config.maximum_record_bytes <= TERMINAL_RESERVE_BYTES
            || config.maximum_retained_bytes < config.maximum_record_bytes
            || config.terminal_retention.is_zero()
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-activation-journal-limits",
            ));
        }
        Ok(Self {
            inner: Arc::new(Inner {
                config,
                clock,
                state: Mutex::new(State {
                    records: BTreeMap::new(),
                    terminal_order: BTreeMap::new(),
                    next_serial: 1,
                    snapshot: ActivationJournalSnapshot::default(),
                }),
            }),
        })
    }

    #[cfg(test)]
    pub(crate) fn begin(
        &self,
        envelope: &ActivationEnvelope,
    ) -> Result<JournalOwner, PlatformError> {
        self.begin_with(envelope, || Ok(()))
            .map(|(owner, ())| owner)
    }

    /// Capacity/identity checks and cancellation registration share the journal
    /// lock. The callback must be synchronous, bounded, and never reenter it.
    pub(crate) fn begin_with<T>(
        &self,
        envelope: &ActivationEnvelope,
        register: impl FnOnce() -> Result<T, PlatformError>,
    ) -> Result<(JournalOwner, T), PlatformError> {
        let tenant = envelope
            .principal
            .tenant
            .as_ref()
            .filter(|tenant| *tenant == &envelope.target.tenant)
            .ok_or_else(|| {
                error(
                    PlatformErrorCode::PermissionDenied,
                    "activation-principal-not-authorized",
                )
            })?;
        self.validate_query(tenant, &envelope.activation_id)?;
        let record_bytes = bytes::base(&envelope.activation_id, tenant)?;
        if record_bytes > self.inner.config.maximum_record_bytes - TERMINAL_RESERVE_BYTES {
            return Err(capacity());
        }
        let sample = self.inner.clock.sample();
        let mut state = self.inner.lock();
        state.expire(sample.monotonic(), self.inner.config.terminal_retention);
        state.reserve(&envelope.activation_id, self.inner.config)?;
        let serial = state.next_serial;
        let next_serial = serial.checked_add(1).ok_or_else(capacity)?;
        let registration = register()?;
        state.next_serial = next_serial;
        let record = Record::new(
            tenant.clone(),
            &envelope.activation_id,
            serial,
            sample.unix_millis(),
            record_bytes,
        );
        state
            .records
            .insert(envelope.activation_id.clone(), Box::new(record));
        state.snapshot.active += 1;
        state.snapshot.reserved_bytes += self.inner.config.maximum_record_bytes;
        state.snapshot.begun = state.snapshot.begun.saturating_add(1);
        Ok((
            JournalOwner::new(self.clone(), envelope.activation_id.clone(), serial),
            registration,
        ))
    }

    pub fn status(
        &self,
        tenant: &TenantId,
        activation_id: &ActivationId,
    ) -> Result<Option<ActivationStatus>, PlatformError> {
        self.validate_query(tenant, activation_id)?;
        let mut state = self.inner.lock();
        state.expire(
            self.inner.clock.monotonic_now(),
            self.inner.config.terminal_retention,
        );
        Ok(state
            .records
            .get(activation_id)
            .filter(|record| &record.tenant == tenant)
            .map(|record| record.status.clone()))
    }

    pub fn events(
        &self,
        tenant: &TenantId,
        activation_id: &ActivationId,
    ) -> Result<Vec<ActivationEvent>, PlatformError> {
        self.validate_query(tenant, activation_id)?;
        let mut state = self.inner.lock();
        state.expire(
            self.inner.clock.monotonic_now(),
            self.inner.config.terminal_retention,
        );
        Ok(state
            .records
            .get(activation_id)
            .filter(|record| &record.tenant == tenant)
            .map_or_else(Vec::new, |record| record.events.clone()))
    }

    /// Scope remains locked through the existing registry's cancellation
    /// operation, preventing eviction/ID reuse between authorization and use.
    pub(crate) fn cancel_with(
        &self,
        tenant: &TenantId,
        activation_id: &ActivationId,
        cancel_active: impl FnOnce() -> CancelDisposition,
    ) -> Result<CancelDisposition, PlatformError> {
        self.validate_query(tenant, activation_id)?;
        let mut state = self.inner.lock();
        state.expire(
            self.inner.clock.monotonic_now(),
            self.inner.config.terminal_retention,
        );
        let Some(record) = state
            .records
            .get(activation_id)
            .filter(|record| &record.tenant == tenant)
        else {
            return Ok(CancelDisposition::NotFound);
        };
        Ok(record
            .status
            .terminal_state
            .map_or_else(cancel_active, CancelDisposition::AlreadyTerminal))
    }

    #[must_use]
    pub fn snapshot(&self) -> ActivationJournalSnapshot {
        let mut state = self.inner.lock();
        state.expire(
            self.inner.clock.monotonic_now(),
            self.inner.config.terminal_retention,
        );
        state.snapshot
    }

    fn validate_query(&self, tenant: &TenantId, id: &ActivationId) -> Result<(), PlatformError> {
        if tenant.0.is_empty()
            || id.0.is_empty()
            || tenant.0.len() > self.inner.config.maximum_record_bytes
            || id.0.len() > self.inner.config.maximum_record_bytes
            || tenant
                .0
                .chars()
                .chain(id.0.chars())
                .any(|character| character.is_control() || character.is_whitespace())
        {
            return Err(error(
                PlatformErrorCode::InvalidArgument,
                "invalid-activation-query",
            ));
        }
        Ok(())
    }
}

impl ActivationJournal for LocalActivationJournal {
    fn append(&self, _event: ActivationEvent) -> BoxFuture<'_, Result<(), PlatformError>> {
        Box::pin(async {
            Err(error(
                PlatformErrorCode::PermissionDenied,
                "activation-journal-lifecycle-owner-required",
            ))
        })
    }

    fn read<'a>(
        &'a self,
        activation_id: &'a ActivationId,
    ) -> BoxFuture<'a, Result<Vec<ActivationEvent>, PlatformError>> {
        Box::pin(async move {
            if activation_id.0.len() > self.inner.config.maximum_record_bytes {
                return Err(error(
                    PlatformErrorCode::InvalidArgument,
                    "invalid-activation-query",
                ));
            }
            let mut state = self.inner.lock();
            state.expire(
                self.inner.clock.monotonic_now(),
                self.inner.config.terminal_retention,
            );
            Ok(state
                .records
                .get(activation_id)
                .map_or_else(Vec::new, |record| record.events.clone()))
        })
    }
}

impl Inner {
    fn lock(&self) -> MutexGuard<'_, State> {
        self.state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

fn error(code: PlatformErrorCode, message: &str) -> PlatformError {
    PlatformError {
        code,
        message: message.to_owned(),
        retryable: false,
        details: Vec::new(),
    }
}

fn capacity() -> PlatformError {
    error(
        PlatformErrorCode::ResourceExhausted,
        "activation-journal-capacity",
    )
}
