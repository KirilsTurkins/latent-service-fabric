//! Explicit Phase 2 operations: bounded input, one RPC and lossless result facts.
mod execute;
pub(super) mod prepare;
pub(super) mod projection;
mod recovery;
#[cfg(test)]
mod tests;
pub(super) use execute::execute;
pub(crate) use recovery::audit_metadata;
pub(crate) use recovery::RecoveryContext;

use super::invalid_response;
use crate::error::Failure;
use latent_rpc::control::v1 as proto;

fn invalid_input() -> Failure {
    Failure::local(
        "invalid-control-input",
        "The control request is invalid or exceeds its bounds.",
    )
}
