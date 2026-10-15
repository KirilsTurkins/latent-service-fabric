//! One authentic reconstructed cohort, with no authority from caller-selected pins.
use std::{ffi::OsString, path::Path};

use super::{sign_selected, Result, NAMES};

#[cfg(test)]
mod tests;

const SOURCE: &str = "eba0d96e9439028aacd6c1f9a85d4ce0118a19bc";
const PROFILE: &str =
    "qualified-http-v1:2da352e29a0c7981e96f4eb3678ce600a71717bb777b056de93d7365793b7a11";
const PINS: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../docs/testing/evidence/java-current-http-reconstructed-capture-2026-10-15.json"
));

pub(crate) fn sign_reconstructed_current_java(
    output: &Path,
    compiler_source: &str,
    paths: &[OsString],
) -> Result<()> {
    sign_selected(
        output,
        compiler_source,
        paths,
        &NAMES,
        PINS,
        PROFILE,
        SOURCE,
    )
}
