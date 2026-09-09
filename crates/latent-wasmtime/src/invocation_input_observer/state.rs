use std::time::Instant;

use latent_core::ActivationId;

use super::{
    InvocationInputDropReason, InvocationInputIdentity, InvocationInputPhase,
    InvocationInputRecord, InvocationInputSnapshot, MAXIMUM_IDENTITIES, MAXIMUM_IDENTITY_BYTES,
    MAXIMUM_RECORDS,
};

pub(super) struct Identity {
    value: InvocationInputIdentity,
    started: bool,
    retired: bool,
    stages: u8,
    raw: Option<(u64, u64)>,
    raw_live: bool,
}

impl Identity {
    pub(super) fn new(token: u8, activation_id: &ActivationId) -> Self {
        Self {
            value: InvocationInputIdentity {
                token,
                activation_id: activation_id.clone(),
            },
            started: false,
            retired: false,
            stages: 0,
            raw: None,
            raw_live: false,
        }
    }
}

#[derive(Default)]
pub(super) struct State {
    pub(super) identities: Vec<Identity>,
    pub(super) records: Vec<InvocationInputRecord>,
    pub(super) overflowed: bool,
    started: u64,
    finished: u64,
    dropped: u64,
    live: u64,
    raw_live: u64,
    raw_bytes: u64,
    maximum_raw_live: u64,
    maximum_raw_bytes: u64,
}

impl State {
    pub(super) fn begin(&mut self, id: &ActivationId) -> Option<u8> {
        let Some(identity) = self
            .identities
            .iter_mut()
            .find(|entry| &entry.value.activation_id == id)
        else {
            self.overflowed = true;
            return None;
        };
        let Some((started, live)) = self.started.checked_add(1).zip(self.live.checked_add(1))
        else {
            self.overflowed = true;
            return None;
        };
        if identity.started {
            self.overflowed = true;
            return None;
        }
        identity.started = true;
        self.started = started;
        self.live = live;
        Some(identity.value.token)
    }

    pub(super) fn raw_created(
        &mut self,
        token: u8,
        length: u64,
        capacity: u64,
        origin: Instant,
    ) -> bool {
        let identity = &mut self.identities[usize::from(token)];
        let next = self
            .raw_live
            .checked_add(1)
            .zip(self.raw_bytes.checked_add(capacity));
        if identity.raw.is_some() || identity.retired || length > capacity || next.is_none() {
            self.overflowed = true;
            return false;
        }
        identity.raw = Some((length, capacity));
        identity.raw_live = true;
        let (live, bytes) = next.expect("checked raw counts");
        self.raw_live = live;
        self.raw_bytes = bytes;
        self.maximum_raw_live = self.maximum_raw_live.max(live);
        self.maximum_raw_bytes = self.maximum_raw_bytes.max(bytes);
        self.record(token, InvocationInputPhase::RawOwnerCreated, None, origin);
        true
    }

    pub(super) fn raw_dropped(
        &mut self,
        token: u8,
        reason: InvocationInputDropReason,
        origin: Instant,
    ) {
        let identity = &mut self.identities[usize::from(token)];
        let capacity = identity.raw.map_or(0, |(_, capacity)| capacity);
        let next = self
            .raw_live
            .checked_sub(1)
            .zip(self.raw_bytes.checked_sub(capacity));
        if !identity.raw_live || identity.retired || next.is_none() {
            self.overflowed = true;
            return;
        }
        identity.raw_live = false;
        (self.raw_live, self.raw_bytes) = next.expect("checked raw refund");
        self.record(
            token,
            InvocationInputPhase::RawOwnerDropped,
            Some(reason),
            origin,
        );
    }

    pub(super) fn stage(&mut self, token: u8, phase: InvocationInputPhase, origin: Instant) {
        let identity = &self.identities[usize::from(token)];
        let valid = match phase {
            InvocationInputPhase::BeforeCallExport => identity.raw.is_some(),
            InvocationInputPhase::GuestCallStart => identity.stages & (1 << 1) != 0,
            _ => false,
        };
        if !valid || identity.retired {
            self.overflowed = true;
            return;
        }
        self.record(token, phase, None, origin);
    }

    pub(super) fn retire(&mut self, token: u8, completed: bool, origin: Instant) {
        let identity = &mut self.identities[usize::from(token)];
        let count = if completed {
            self.finished
        } else {
            self.dropped
        };
        let next = count.checked_add(1).zip(self.live.checked_sub(1));
        if identity.retired || identity.raw_live || next.is_none() {
            self.overflowed = true;
            return;
        }
        identity.retired = true;
        let (count, live) = next.expect("checked invocation retirement");
        self.live = live;
        let phase = if completed {
            self.finished = count;
            InvocationInputPhase::InvocationFinished
        } else {
            self.dropped = count;
            InvocationInputPhase::InvocationDropped
        };
        self.record(token, phase, None, origin);
    }

    fn record(
        &mut self,
        token: u8,
        phase: InvocationInputPhase,
        drop_reason: Option<InvocationInputDropReason>,
        origin: Instant,
    ) {
        let identity = &mut self.identities[usize::from(token)];
        let bit = 1 << phase as u8;
        if identity.stages & bit != 0 {
            self.overflowed = true;
            return;
        }
        identity.stages |= bit;
        if self.records.len() == MAXIMUM_RECORDS {
            self.overflowed = true;
            return;
        }
        let raw = identity.raw;
        let observed_nanos = self.now(origin);
        self.records.push(InvocationInputRecord {
            sequence: u64::try_from(self.records.len()).expect("64 records"),
            token,
            phase,
            observed_nanos,
            raw_length_bytes: raw.map(|(length, _)| length),
            raw_capacity_bytes: raw.map(|(_, capacity)| capacity),
            drop_reason,
            live_invocations: self.live,
            live_raw_owners: self.raw_live,
            live_raw_capacity_bytes: self.raw_bytes,
            maximum_live_raw_owners: self.maximum_raw_live,
            maximum_live_raw_capacity_bytes: self.maximum_raw_bytes,
        });
    }

    pub(super) fn now(&mut self, origin: Instant) -> u64 {
        let Some(value) = Instant::now()
            .checked_duration_since(origin)
            .and_then(|elapsed| u64::try_from(elapsed.as_nanos()).ok())
        else {
            self.overflowed = true;
            return u64::MAX;
        };
        value
    }

    pub(super) fn snapshot(&self, enabled: bool, observed_nanos: u64) -> InvocationInputSnapshot {
        InvocationInputSnapshot {
            enabled,
            overflowed: self.overflowed,
            maximum_identities: MAXIMUM_IDENTITIES,
            maximum_identity_bytes: MAXIMUM_IDENTITY_BYTES,
            maximum_records: MAXIMUM_RECORDS,
            observed_nanos,
            identities: self
                .identities
                .iter()
                .map(|entry| entry.value.clone())
                .collect(),
            records: self.records.clone(),
            started_invocations: self.started,
            finished_invocations: self.finished,
            dropped_invocations: self.dropped,
            live_invocations: self.live,
            live_raw_owners: self.raw_live,
            live_raw_capacity_bytes: self.raw_bytes,
            maximum_live_raw_owners: self.maximum_raw_live,
            maximum_live_raw_capacity_bytes: self.maximum_raw_bytes,
        }
    }
}
