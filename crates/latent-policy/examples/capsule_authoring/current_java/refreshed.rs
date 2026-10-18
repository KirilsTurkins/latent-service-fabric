//! One authentic fresh-profile cohort; historical custody stays immutable.
use std::{ffi::OsString, path::Path};

use super::{sign_selected, Result, NAMES};

#[cfg(test)]
mod tests;

const SOURCE: &str = "eba0d96e9439028aacd6c1f9a85d4ce0118a19bc";
const PROFILE: &str =
    "qualified-http-v1:bb85705ae221db0b883cf8253e00ef1091b7ea70e768299bb14a2175286c4391";
const PINS: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../docs/testing/evidence/java-current-http-refreshed-capture-2026-10-16.json"
));

pub(crate) fn sign_refreshed_current_java(
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
