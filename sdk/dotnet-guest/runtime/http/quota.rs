//! A finite guest resource cap underneath both closed and admitted HTTP modes.
//! Actual linear memory remains on the original Wasmtime activation ledger.
use std::cell::Cell;
const MAX_RESOURCES: usize = 64;
thread_local! { static RESOURCES: Cell<usize> = const { Cell::new(0) }; }
pub struct Slot;
impl Slot {
    pub fn new() -> Self {
        RESOURCES.with(|count| {
            assert!(count.get() < MAX_RESOURCES, "HTTP guest resource limit");
            count.set(count.get() + 1);
        });
        Self
    }
}
impl Drop for Slot {
    fn drop(&mut self) {
        RESOURCES.with(|count| count.set(count.get().checked_sub(1).expect("HTTP resource owner")));
    }
}
