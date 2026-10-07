// SPDX-License-Identifier: MIT OR Apache-2.0
// Based on Rust 1.97.1 library/std/src/sys/time/unsupported.rs.
// This is a std platform overlay, not an application executor or replacement
// std crate. All arithmetic/layout remains the pinned upstream implementation.
use crate::time::Duration;

#[cfg_attr(target_arch = "wasm32", link(wasm_import_module = "latent:clock/monotonic@0.1.0"))]
unsafe extern "C" {
    #[link_name = "now-nanos"]
    fn lsf_std_monotonic_now_nanos() -> u64;
}

#[cfg_attr(target_arch = "wasm32", link(wasm_import_module = "latent:clock/wall@0.1.0"))]
unsafe extern "C" {
    #[link_name = "now-unix-millis"]
    fn lsf_std_wall_now_unix_millis() -> u64;
}

#[derive(Copy, Clone, PartialEq, Eq, PartialOrd, Ord, Debug, Hash)]
pub struct Instant(Duration);

#[derive(Copy, Clone, PartialEq, Eq, PartialOrd, Ord, Debug, Hash)]
pub struct SystemTime(Duration);

pub const UNIX_EPOCH: SystemTime = SystemTime(Duration::from_secs(0));

impl Instant {
    pub fn now() -> Instant {
        // Synchronous canonical scalar import: no executor, worker, timer or
        // ambient OS clock. Missing/failed host imports never become zero time.
        Instant(Duration::from_nanos(unsafe { lsf_std_monotonic_now_nanos() }))
    }

    pub fn checked_sub_instant(&self, other: &Instant) -> Option<Duration> {
        self.0.checked_sub(other.0)
    }

    pub fn checked_add_duration(&self, other: &Duration) -> Option<Instant> {
        Some(Instant(self.0.checked_add(*other)?))
    }

    pub fn checked_sub_duration(&self, other: &Duration) -> Option<Instant> {
        Some(Instant(self.0.checked_sub(*other)?))
    }
}

impl SystemTime {
    pub const MAX: SystemTime = SystemTime(Duration::MAX);
    pub const MIN: SystemTime = SystemTime(Duration::ZERO);

    pub fn now() -> SystemTime {
        SystemTime(Duration::from_millis(unsafe { lsf_std_wall_now_unix_millis() }))
    }

    pub fn sub_time(&self, other: &SystemTime) -> Result<Duration, Duration> {
        self.0.checked_sub(other.0).ok_or_else(|| other.0 - self.0)
    }

    pub fn checked_add_duration(&self, other: &Duration) -> Option<SystemTime> {
        Some(SystemTime(self.0.checked_add(*other)?))
    }

    pub fn checked_sub_duration(&self, other: &Duration) -> Option<SystemTime> {
        Some(SystemTime(self.0.checked_sub(*other)?))
    }
}
