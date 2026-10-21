//! The existing typed Exchange bounds, separated for concrete value controls.
//! These values are identical to the unchanged original .NET Exchange profile.
pub const CHUNK: usize = 16 * 1024;
pub const MAX_BODY: u64 = 1024 * 1024;
pub const MAX_HEADERS: usize = 32;
pub const MAX_HEADER_BYTES: usize = 8 * 1024;
