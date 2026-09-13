//! One-shot management operations. Input preparation performs no network I/O.

mod association;
mod bounds;
mod execute;
mod node;
pub(crate) mod phase2;
mod prepare;
mod response;
#[cfg(test)]
mod tests;

pub use execute::execute;
pub use prepare::{prepare, validate};

use crate::error::Failure;

fn invalid_manifest() -> Failure {
    Failure::local(
        "invalid-manifest",
        "The manifest is not a valid Phase 1 document.",
    )
}

fn invalid_response() -> Failure {
    Failure::protocol(
        "invalid-management-response",
        "The node returned an invalid management response.",
    )
}

fn canonical_digest(value: &str) -> bool {
    value.strip_prefix("sha256:").is_some_and(|hash| {
        hash.len() == 64
            && hash
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    })
}
