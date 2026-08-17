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
