// SPDX-License-Identifier: MIT OR Apache-2.0
// Appended to the shared, exact compiler-owned scalar implementation.
pub fn fill_bytes(destination: &mut [u8]) {
    approved_fill(destination).expect("approved RANDOM source refused standard entropy");
}

pub fn hashmap_random_keys() -> (u64, u64) {
    let mut value = [0; 16];
    fill_bytes(&mut value);
    let first = u64::from_le_bytes(value[..8].try_into().unwrap());
    let second = u64::from_le_bytes(value[8..].try_into().unwrap());
    (first, second)
}
