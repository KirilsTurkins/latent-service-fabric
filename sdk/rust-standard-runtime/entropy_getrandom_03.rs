// SPDX-License-Identifier: MIT OR Apache-2.0
// Appended to the shared scalar implementation inside the exact getrandom
// 0.3.4 runtime backend, preserving its ordinary fallible public API.
use crate::Error;
use core::mem::MaybeUninit;
pub use crate::util::{inner_u32, inner_u64};

pub fn fill_inner(destination: &mut [MaybeUninit<u8>]) -> Result<(), Error> {
    if destination.len() > 65_536 {
        return Err(Error::new_custom(1));
    }
    for value in destination.iter_mut() {
        value.write(0);
    }
    // SAFETY: all bytes were initialized above; length and ownership are the
    // original borrowed slice. The common implementation never retains it.
    let initialized = unsafe {
        core::slice::from_raw_parts_mut(destination.as_mut_ptr().cast::<u8>(), destination.len())
    };
    approved_fill(initialized).map_err(|ordinal| Error::new_custom(u16::from(ordinal) + 1))
}
