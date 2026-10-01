use super::super::{
    codec::{Decoder, Encoder},
    AtomicError, CommandTime,
};
use latent_state::embedded::{Family, RowKey};

pub(in crate::atomic) const PROGRESS_KEY: &[u8] = b"result-retention-v1\0";

/// Host-derived clock observation. Guest/request fields cannot supply this
/// proof. A new boot or restored history needs an explicit authorized anchor;
/// anchoring writes only progress and never expires a response.
#[derive(Debug, Clone, Copy)]
pub struct MaintenanceClock {
    pub time: CommandTime,
    pub boot: [u8; 32],
    pub monotonic_millis: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MaintenanceProgress {
    pub generation: u64,
    pub unix_millis: u64,
    pub boot: [u8; 32],
    pub monotonic_millis: u64,
    pub anchor_unix_millis: u64,
    pub anchor_monotonic_millis: u64,
    pub visited: u64,
    pub retired: u64,
    pub reclaimed_bytes: u64,
    pub cursor: Option<Vec<u8>>,
}
impl MaintenanceClock {
    pub(super) fn validate(self) -> Result<(), AtomicError> {
        if !self.time.continuity_proven || self.boot == [0; 32] {
            return Err(AtomicError::RecoveryRequired);
        }
        Ok(())
    }
    pub(super) fn next(self, previous: &MaintenanceProgress) -> Result<(), AtomicError> {
        self.validate()?;
        let elapsed = self.monotonic_millis.checked_sub(previous.monotonic_millis);
        let wall = self.time.unix_millis.checked_sub(previous.unix_millis);
        // Persist the approved anchor. Refreshing the tolerance at each step
        // would let repeated small wall-only jumps erase a retained result.
        let anchored_elapsed = self
            .monotonic_millis
            .checked_sub(previous.anchor_monotonic_millis);
        let anchored_wall = self
            .time
            .unix_millis
            .checked_sub(previous.anchor_unix_millis);
        if self.boot != previous.boot
            || !matches!((elapsed, wall), (Some(e), Some(w))
                if e <= 60_000 && e.abs_diff(w) <= 1_000)
            || !matches!((anchored_elapsed, anchored_wall), (Some(e), Some(w))
                if e.abs_diff(w) <= 1_000)
        {
            return Err(AtomicError::RecoveryRequired);
        }
        Ok(())
    }
}
impl MaintenanceProgress {
    pub(super) fn anchor(clock: MaintenanceClock, generation: u64) -> Self {
        Self {
            generation,
            unix_millis: clock.time.unix_millis,
            boot: clock.boot,
            monotonic_millis: clock.monotonic_millis,
            anchor_unix_millis: clock.time.unix_millis,
            anchor_monotonic_millis: clock.monotonic_millis,
            visited: 0,
            retired: 0,
            reclaimed_bytes: 0,
            cursor: None,
        }
    }
    pub(in crate::atomic) fn encode(&self) -> Result<Vec<u8>, AtomicError> {
        let mut out = Encoder::new(b"LMP\0\x02");
        out.identity(super::super::Identity(self.boot));
        for number in [
            self.generation,
            self.unix_millis,
            self.monotonic_millis,
            self.anchor_unix_millis,
            self.anchor_monotonic_millis,
            self.visited,
            self.retired,
            self.reclaimed_bytes,
        ] {
            out.number(number);
        }
        let cursor = self.cursor.as_deref().unwrap_or_default();
        if !cursor.is_empty() && (cursor.len() != 43 || !cursor.starts_with(b"command-v1\0")) {
            return Err(AtomicError::Limit);
        }
        out.0.extend_from_slice(
            &u16::try_from(cursor.len())
                .map_err(|_| AtomicError::Limit)?
                .to_le_bytes(),
        );
        out.0.extend_from_slice(cursor);
        out.finish(146)
    }
    pub(in crate::atomic) fn decode(bytes: &[u8]) -> Result<Self, AtomicError> {
        let mut input = Decoder::new(bytes, b"LMP\0\x02", 146)?;
        let boot = input.identity()?.bytes();
        let generation = input.number()?;
        let unix_millis = input.number()?;
        let monotonic_millis = input.number()?;
        let anchor_unix_millis = input.number()?;
        let anchor_monotonic_millis = input.number()?;
        let visited = input.number()?;
        let retired = input.number()?;
        let reclaimed_bytes = input.number()?;
        let length = u16::from_le_bytes(
            input
                .take(2)?
                .try_into()
                .map_err(|_| AtomicError::Corrupt)?,
        );
        if !matches!(length, 0 | 43) || generation == 0 || boot == [0; 32] || retired > visited {
            return Err(AtomicError::Corrupt);
        }
        if !matches!(
            (
                unix_millis.checked_sub(anchor_unix_millis),
                monotonic_millis.checked_sub(anchor_monotonic_millis)
            ),
            (Some(w), Some(e)) if e.abs_diff(w) <= 1_000
        ) {
            return Err(AtomicError::Corrupt);
        }
        let cursor = (length != 0)
            .then(|| input.take(usize::from(length)).map(Vec::from))
            .transpose()?;
        if cursor
            .as_ref()
            .is_some_and(|key| !key.starts_with(b"command-v1\0"))
        {
            return Err(AtomicError::Corrupt);
        }
        input.finish()?;
        Ok(Self {
            generation,
            unix_millis,
            boot,
            monotonic_millis,
            anchor_unix_millis,
            anchor_monotonic_millis,
            visited,
            retired,
            reclaimed_bytes,
            cursor,
        })
    }
    pub(in crate::atomic) fn key() -> RowKey {
        RowKey {
            family: Family::Maintenance,
            key: PROGRESS_KEY.to_vec(),
        }
    }
}
