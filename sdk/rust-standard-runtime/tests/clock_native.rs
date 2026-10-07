//! Reference checks for the actual std PAL source. This harness is native,
//! uses explicit fake host imports, and cannot qualify a rebuilt guest sysroot.
#![allow(dead_code)]

pub mod time {
    pub use std::time::Duration;
}
#[path = "../clock.rs"]
mod platform;

use std::sync::atomic::{AtomicU64, Ordering};
use time::Duration;

static MONOTONIC: AtomicU64 = AtomicU64::new(0);
static WALL: AtomicU64 = AtomicU64::new(0);

#[unsafe(export_name = "now-nanos")]
pub extern "C" fn mock_monotonic() -> u64 {
    MONOTONIC.load(Ordering::SeqCst)
}
#[unsafe(export_name = "now-unix-millis")]
pub extern "C" fn mock_wall() -> u64 {
    WALL.load(Ordering::SeqCst)
}

#[test]
fn nanoseconds_and_full_unsigned_domain_do_not_become_milliseconds_or_signed_time() {
    MONOTONIC.store(0, Ordering::SeqCst);
    let zero = platform::Instant::now();
    for value in [1, 999_999_999, 1_000_000_000, u64::MAX] {
        MONOTONIC.store(value, Ordering::SeqCst);
        assert_eq!(platform::Instant::now().checked_sub_instant(&zero), Some(Duration::from_nanos(value)));
    }
}

#[test]
fn monotonic_reverse_comparison_remains_none_instead_of_requested_elapsed_success() {
    MONOTONIC.store(20, Ordering::SeqCst);
    let later = platform::Instant::now();
    MONOTONIC.store(10, Ordering::SeqCst);
    let earlier = platform::Instant::now();
    assert_eq!(earlier.checked_sub_instant(&later), None);
    assert_eq!(later.checked_sub_instant(&earlier), Some(Duration::from_nanos(10)));
}

#[test]
fn wall_uses_milliseconds_and_preserves_forward_and_backward_differences() {
    WALL.store(u64::MAX, Ordering::SeqCst);
    let far = platform::SystemTime::now();
    assert_eq!(far.sub_time(&platform::UNIX_EPOCH), Ok(Duration::from_millis(u64::MAX)));
    assert_eq!(platform::UNIX_EPOCH.sub_time(&far), Err(Duration::from_millis(u64::MAX)));
    WALL.store(1, Ordering::SeqCst);
    assert_eq!(platform::SystemTime::now().sub_time(&platform::UNIX_EPOCH), Ok(Duration::from_millis(1)));
}

#[test]
fn original_duration_overflow_underflow_and_limits_are_preserved() {
    assert_eq!(platform::SystemTime::MAX.checked_add_duration(&Duration::from_nanos(1)), None);
    assert_eq!(platform::SystemTime::MIN.checked_sub_duration(&Duration::from_nanos(1)), None);
    assert_eq!(platform::UNIX_EPOCH.checked_add_duration(&Duration::MAX), Some(platform::SystemTime::MAX));
    MONOTONIC.store(0, Ordering::SeqCst);
    let zero = platform::Instant::now();
    assert_eq!(zero.checked_sub_duration(&Duration::from_nanos(1)), None);
    let far = zero.checked_add_duration(&Duration::MAX).unwrap();
    assert_eq!(far.checked_add_duration(&Duration::from_nanos(1)), None);
    assert_eq!(far.checked_sub_duration(&Duration::MAX), Some(zero));
}
