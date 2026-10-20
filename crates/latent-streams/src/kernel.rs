//! Kernel accounting is a source-selected platform property, not an operator
//! assertion or socket-buffer snapshot. No current Linux profile is qualified.
use crate::{error, StreamError, StreamErrorCode};

#[derive(Clone, Copy)]
pub(crate) enum Mode {
    // Historical library semantics only; never selected by normal installation.
    #[cfg(any(test, feature = "development-outbound"))]
    LogicalReference,
    RetainUnproved,
}
impl Mode {
    pub(crate) fn retains_unproved(self) -> bool {
        matches!(self, Self::RetainUnproved)
    }
}

pub(crate) fn require_supported_profile() -> Result<(), StreamError> {
    // No current kernel/image has a source-authenticated complete allocation
    // bound plus sealed full-socket/derived-tail final-free producer. This gate
    // has no operator/environment/boolean override and no permissive fallback.
    // Supplying a future exact platform implementation requires source review;
    // observed release strings, ss absence, RST or timeouts cannot promote it.
    Err(error(StreamErrorCode::Unsupported))
}
