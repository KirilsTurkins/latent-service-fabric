//! Research measurement of actual successful linear-memory reservations.
use wasmtime::{ResourceLimiter, StoreLimits, StoreLimitsBuilder};

pub const MEMORY_LIMIT: usize = 16 * 1024 * 1024;
pub struct Memory {
    limits: StoreLimits,
    pub current: usize,
    pub peak: usize,
    pending: Option<(usize, usize)>,
}
impl Memory {
    pub fn new() -> Self {
        Self {
            limits: StoreLimitsBuilder::new()
                .memory_size(MEMORY_LIMIT)
                .memories(1)
                .tables(2)
                .instances(8)
                .table_elements(4096)
                .trap_on_grow_failure(true)
                .build(),
            current: 0,
            peak: 0,
            pending: None,
        }
    }
}
impl ResourceLimiter for Memory {
    fn memory_growing(
        &mut self,
        current: usize,
        desired: usize,
        maximum: Option<usize>,
    ) -> wasmtime::Result<bool> {
        self.pending = None;
        let total = self.current.checked_add(desired.saturating_sub(current))
            .ok_or_else(|| wasmtime::Error::msg("memory accounting overflow"))?;
        if total > MEMORY_LIMIT {
            return Err(wasmtime::Error::msg("research aggregate memory limit"));
        }
        let allowed = self.limits.memory_growing(current, desired, maximum)?;
        if allowed {
            self.pending = Some((self.current, self.peak));
            self.current = total;
            self.peak = self.peak.max(total);
        }
        Ok(allowed)
    }
    fn memory_grow_failed(&mut self, error: wasmtime::Error) -> wasmtime::Result<()> {
        if let Some((current, peak)) = self.pending.take() {
            self.current = current;
            self.peak = peak;
        }
        self.limits.memory_grow_failed(error)
    }
    fn table_growing(
        &mut self,
        current: usize,
        desired: usize,
        maximum: Option<usize>,
    ) -> wasmtime::Result<bool> {
        self.pending = None;
        self.limits.table_growing(current, desired, maximum)
    }
    fn table_grow_failed(&mut self, error: wasmtime::Error) -> wasmtime::Result<()> {
        self.limits.table_grow_failed(error)
    }
    fn instances(&self) -> usize { self.limits.instances() }
    fn tables(&self) -> usize { self.limits.tables() }
    fn memories(&self) -> usize { self.limits.memories() }
}
