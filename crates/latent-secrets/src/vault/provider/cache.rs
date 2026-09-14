use super::{memory, Arc, AtomicBool, Ordering, Result, SecretError};
use crate::vault::VaultLimits;
use latent_core::ClockSample;
use std::time::{Duration, Instant};
use zeroize::Zeroizing;

pub(super) struct Expiry {
    pub unix: Option<u64>,
    mono: Option<Instant>,
    expired: AtomicBool,
}
impl Expiry {
    pub fn new(unix: Option<u64>, now: ClockSample) -> Result<Self> {
        let mono = unix
            .map(|v| {
                now.monotonic()
                    .checked_add(Duration::from_millis(v.saturating_sub(now.unix_millis())))
                    .ok_or(SecretError::Unavailable)
            })
            .transpose()?;
        Ok(Self {
            unix,
            mono,
            expired: AtomicBool::new(false),
        })
    }
    pub fn check(&self, now: ClockSample) -> Result<()> {
        if self.expired.load(Ordering::Acquire)
            || self.unix.is_some_and(|t| now.unix_millis() >= t)
            || self.mono.is_some_and(|t| now.monotonic() >= t)
        {
            self.expired.store(true, Ordering::Release);
            return Err(SecretError::Expired);
        }
        Ok(())
    }
}
pub(super) struct Value {
    pub bytes: Zeroizing<Vec<u8>>,
    pub version: u64,
    pub version_text: String,
    pub expiry: Expiry,
    pub fresh_until: Option<Instant>,
    pub token: Zeroizing<[u8; 32]>,
    pub sequence: u64,
    pub _plaintext: memory::Charge,
}
impl Value {
    pub fn check(&self, now: ClockSample) -> Result<()> {
        self.expiry.check(now)?;
        if self.fresh_until.is_some_and(|t| now.monotonic() >= t) {
            return Err(SecretError::Unavailable);
        }
        Ok(())
    }
}
#[derive(Default)]
struct Slot {
    value: Option<Arc<Value>>,
    request: u64,
    version: u64,
}
pub(super) struct Cache {
    slots: Vec<Slot>,
    sequence: u64,
}
impl Cache {
    pub fn new(count: usize) -> Self {
        Self {
            slots: (0..count).map(|_| Slot::default()).collect(),
            sequence: 0,
        }
    }
    pub fn usage(&self) -> (usize, usize) {
        self.slots
            .iter()
            .filter_map(|s| s.value.as_ref())
            .fold((0, 0), |(n, b), v| (n + 1, b + v.bytes.capacity()))
    }
    pub fn cached(
        &mut self,
        index: usize,
        token: &[u8; 32],
        now: ClockSample,
    ) -> Option<Arc<Value>> {
        let slot = &mut self.slots[index];
        if slot.value.as_ref().is_some_and(|v| {
            *v.token != *token || v.check(now).is_err() || v.sequence != slot.request
        }) {
            slot.value.take();
        }
        slot.value.clone()
    }
    pub fn begin(&mut self, index: usize) -> Result<u64> {
        self.sequence = self
            .sequence
            .checked_add(1)
            .ok_or(SecretError::Unavailable)?;
        self.slots[index].request = self.sequence;
        Ok(self.sequence)
    }
    pub fn install(&mut self, index: usize, value: &Arc<Value>, limits: VaultLimits) -> Result<()> {
        let slot = &mut self.slots[index];
        if slot.request != value.sequence || value.version < slot.version {
            return Err(SecretError::Unavailable);
        }
        slot.version = value.version;
        slot.value.take();
        let bytes = value.bytes.capacity();
        if limits.cache_ttl_millis == 0
            || limits.maximum_cache_entries == 0
            || bytes > limits.maximum_cache_bytes
        {
            return Ok(());
        }
        loop {
            let (count, retained) = self.usage();
            if count < limits.maximum_cache_entries
                && retained + bytes <= limits.maximum_cache_bytes
            {
                break;
            }
            let oldest = self
                .slots
                .iter()
                .enumerate()
                .filter_map(|(i, s)| s.value.as_ref().map(|v| (i, v.sequence)))
                .min_by_key(|(_, s)| *s)
                .map(|(i, _)| i)
                .ok_or(SecretError::Unavailable)?;
            self.slots[oldest].value.take();
        }
        self.slots[index].value = Some(value.clone());
        Ok(())
    }
    pub fn verify(&self, index: usize, value: &Value, now: ClockSample) -> Result<()> {
        let slot = &self.slots[index];
        if slot.request != value.sequence || slot.version != value.version {
            return Err(SecretError::Unavailable);
        }
        value.check(now)
    }
    pub fn prune(&mut self, now: ClockSample) {
        for slot in &mut self.slots {
            if slot.value.as_ref().is_some_and(|v| v.check(now).is_err()) {
                slot.value.take();
            }
        }
    }
    pub fn clear(&mut self) {
        for slot in &mut self.slots {
            slot.value.take();
        }
    }
}
