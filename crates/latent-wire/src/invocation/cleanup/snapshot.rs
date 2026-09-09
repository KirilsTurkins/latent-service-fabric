use serde::Serialize;

/// Observations of one fixed task and its affine slots, not proof of cell reuse.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
#[expect(
    clippy::struct_excessive_bools,
    reason = "These independently observed admission, task, join and failure facts are the bounded evidence contract."
)]
pub struct ActivationCleanupSnapshot {
    pub capacity: usize,
    pub accepting: bool,
    pub driver_alive: bool,
    pub driver_joined: bool,
    pub reserved: usize,
    pub queued: usize,
    pub running: usize,
    /// Includes late transfers that require conservative synchronous fallback.
    pub handoffs: u64,
    pub completed: u64,
    pub timed_out: u64,
    pub panicked: u64,
    pub fallbacks: u64,
    pub failed: bool,
}
