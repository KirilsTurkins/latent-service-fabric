use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};

use super::{decimal, EvidenceError, MAXIMUM_COMMANDS, MAXIMUM_INVOKE_ATTEMPTS};

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkCounts {
    #[serde(with = "decimal")]
    pub commands: u64,
    #[serde(with = "decimal")]
    pub invoke_attempts: u64,
    pub budget_exhausted: bool,
}

impl WorkCounts {
    pub(super) fn within(self, invokes: u64, commands: u64) -> bool {
        !self.budget_exhausted
            && self.invoke_attempts <= invokes
            && self.commands <= commands
            && self.invoke_attempts <= self.commands
    }

    pub(super) fn checked_add(self, other: Self) -> Option<Self> {
        Some(Self {
            commands: self.commands.checked_add(other.commands)?,
            invoke_attempts: self.invoke_attempts.checked_add(other.invoke_attempts)?,
            budget_exhausted: self.budget_exhausted || other.budget_exhausted,
        })
    }
}

/// Shared by every driver and charged immediately before attempted dispatch.
/// Rejected/malformed Invoke RPCs cost exactly the same unit as successful ones.
#[derive(Debug, Clone)]
pub struct WorkCounter {
    counts: Arc<Mutex<WorkCounts>>,
    invokes: u64,
    commands: u64,
}

impl Default for WorkCounter {
    fn default() -> Self {
        Self {
            counts: Arc::default(),
            invokes: MAXIMUM_INVOKE_ATTEMPTS,
            commands: MAXIMUM_COMMANDS,
        }
    }
}

impl WorkCounter {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_limits(invokes: u64, commands: u64) -> Result<Self, EvidenceError> {
        if invokes > MAXIMUM_INVOKE_ATTEMPTS
            || commands > MAXIMUM_COMMANDS
            || invokes > commands
            || commands == 0
        {
            return Err(EvidenceError("invalid-conformance-work-limits"));
        }
        Ok(Self {
            counts: Arc::default(),
            invokes,
            commands,
        })
    }

    pub fn before_command(&self, is_invoke: bool) -> Result<(), EvidenceError> {
        let mut counts = self
            .counts
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if counts.commands == self.commands || (is_invoke && counts.invoke_attempts == self.invokes)
        {
            counts.budget_exhausted = true;
            return Err(EvidenceError("conformance-work-limit"));
        }
        counts.commands += 1;
        counts.invoke_attempts += u64::from(is_invoke);
        Ok(())
    }

    pub fn snapshot(&self) -> WorkCounts {
        *self
            .counts
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}
