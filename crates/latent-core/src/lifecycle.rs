//! Activation lifecycle states.

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[non_exhaustive]
pub enum ActivationPhase {
    Received,
    Resolved,
    Admitted,
    Queued,
    Materializing,
    Running,
    Suspended,
    PreparingCommit,
    Committed,
    EffectsPending,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[non_exhaustive]
pub enum ActivationTerminalState {
    Completed,
    Rejected,
    Cancelled,
    DeadlineExceeded,
    ResourceExhausted,
    GuestTrap,
    StateConflict,
    DependencyFailed,
    PlatformFailed,
}

/// Stable result of a cancellation request.
///
/// Platform transport and validation failures remain `PlatformError`s.  These
/// values are normal, deterministic outcomes that clients need to distinguish
/// without interpreting a generic boolean or an error string.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum CancelDisposition {
    Accepted,
    AlreadyTerminal(ActivationTerminalState),
    NotFound,
}
