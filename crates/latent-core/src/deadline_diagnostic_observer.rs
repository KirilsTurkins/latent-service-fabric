//! Opt-in, bounded witnesses for deadline decisions in a diagnostic invocation.
//!
//! Records contain value copies only. They retain no activation, ledger, clock,
//! callback or runtime owner. Ordinary clocks expose no recorder. Instants are
//! preserved exactly; consumers must not turn an unsupported or pre-origin
//! observation into a fabricated zero-duration measurement.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

use crate::{
    ActivationPhase, ActivationTerminalState, EffectiveDeadline, PlatformError, PlatformErrorCode,
    ResourceBudget,
};

static NEXT_OWNER: AtomicU64 = AtomicU64::new(1);

/// An observer-scoped association, never constructed from invocation metadata.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DeadlineDiagnosticToken {
    owner: u64,
    id: u64,
}

impl DeadlineDiagnosticToken {
    #[must_use]
    pub const fn id(self) -> u64 {
        self.id
    }
}

/// A fixed decision vocabulary; terminal deadline checks precede the final
/// cancellation/journal winner, which the activation observer records separately.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeadlineDiagnosticDecision {
    Accepted,
    Completed,
    Cancelled,
    DeadlineExceeded,
    QueueInfeasible,
    LoadStale,
    QueueEstimateOverflow,
    MissingDeadline,
    Rejected(PlatformErrorCode),
}

/// Each hook supplies the values used at that boundary, without resampling to
/// reconstruct a decision. Absence means unavailable, not an observed zero.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeadlineDiagnosticObservation {
    Ingress {
        observed_at: Instant,
        expires_at: Option<Instant>,
        deadline_unix_millis: Option<u64>,
    },
    BodyDecoded {
        observed_at: Instant,
        request_deadline_unix_millis: Option<u64>,
        request_wall_time_limit_millis: Option<u64>,
    },
    AdmissionCheck {
        observed_at: Instant,
        deadline: EffectiveDeadline,
        remaining: Option<Duration>,
        required: Option<Duration>,
        decision: DeadlineDiagnosticDecision,
    },
    AdmittedLedger {
        observed_at: Instant,
        deadline: EffectiveDeadline,
        budget: ResourceBudget,
    },
    ExecutionDeadline {
        observed_at: Instant,
        deadline: EffectiveDeadline,
        budget: ResourceBudget,
    },
    TerminalDecision {
        observed_at: Instant,
        expires_at: Option<Instant>,
        decision: DeadlineDiagnosticDecision,
    },
    /// Observation after the successful lifecycle transition has committed.
    LifecyclePhase {
        observed_at: Instant,
        phase: ActivationPhase,
    },
    /// Observation after terminal publication, separate from its deadline check.
    TerminalWinner {
        observed_at: Instant,
        terminal_state: ActivationTerminalState,
    },
    /// Actual transfer of an existing lifecycle into its reserved supervisor
    /// slot. Cancelled denotes raw disconnect here, not an accepted Cancel RPC.
    TransportHandoff {
        observed_at: Instant,
        slot: u64,
        generation: u64,
        cause: DeadlineDiagnosticDecision,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeadlineDiagnosticIdentity {
    pub token: DeadlineDiagnosticToken,
    pub activation_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeadlineDiagnosticRecord {
    pub sequence: u64,
    pub token: DeadlineDiagnosticToken,
    pub observation: DeadlineDiagnosticObservation,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeadlineDiagnosticSnapshot {
    pub origin: Instant,
    /// Also set by an invalid association. A true value forbids complete proof.
    pub overflowed: bool,
    pub identities: Vec<DeadlineDiagnosticIdentity>,
    pub records: Vec<DeadlineDiagnosticRecord>,
}

#[derive(Debug)]
struct State {
    owner: Option<u64>,
    maximum_identities: usize,
    maximum_records: usize,
    snapshot: DeadlineDiagnosticSnapshot,
}

/// One explicitly enabled diagnostic population, with no helper or callback.
#[derive(Debug, Clone)]
pub struct DeadlineDiagnosticObserver {
    inner: Arc<Mutex<State>>,
}

impl DeadlineDiagnosticObserver {
    pub const MAXIMUM_IDENTITIES: usize = 23;
    pub const MAXIMUM_RECORDS: usize = 512;
    pub const MAXIMUM_IDENTIFIER_BYTES: usize = 256;
    pub const MAXIMUM_CONFIGURED_IDENTITIES: usize = 64;
    pub const MAXIMUM_CONFIGURED_RECORDS: usize = 2_048;

    #[must_use]
    pub fn new(origin: Instant) -> Self {
        Self::with_limits(origin, Self::MAXIMUM_IDENTITIES, Self::MAXIMUM_RECORDS)
            .expect("fixed diagnostic limits are valid")
    }

    /// Explicit finite diagnostic populations can opt into larger bounds. The
    /// ordinary constructor and its original population remain unchanged.
    pub fn with_limits(
        origin: Instant,
        maximum_identities: usize,
        maximum_records: usize,
    ) -> Result<Self, PlatformError> {
        if maximum_identities == 0
            || maximum_identities > Self::MAXIMUM_CONFIGURED_IDENTITIES
            || maximum_records < maximum_identities
            || maximum_records > Self::MAXIMUM_CONFIGURED_RECORDS
        {
            return Err(PlatformError {
                code: PlatformErrorCode::InvalidArgument,
                message: "deadline diagnostic limits are invalid".to_owned(),
                retryable: false,
                details: Vec::new(),
            });
        }
        let owner = NEXT_OWNER
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |next| {
                next.checked_add(1)
            })
            .ok();
        Ok(Self {
            inner: Arc::new(Mutex::new(State {
                owner,
                maximum_identities,
                maximum_records,
                snapshot: DeadlineDiagnosticSnapshot {
                    origin,
                    overflowed: owner.is_none(),
                    identities: Vec::with_capacity(maximum_identities),
                    records: Vec::with_capacity(maximum_records),
                },
            })),
        })
    }

    /// Allocate before decoding the body, for Invoke only. The token can cross
    /// a trusted request extension; binding the decoded identity happens later.
    #[must_use]
    pub fn begin(&self, ingress: DeadlineDiagnosticObservation) -> Option<DeadlineDiagnosticToken> {
        let mut state = self.lock();
        if !matches!(ingress, DeadlineDiagnosticObservation::Ingress { .. })
            || state.snapshot.identities.len() == state.maximum_identities
            || state.snapshot.records.len() == state.maximum_records
        {
            state.snapshot.overflowed = true;
            return None;
        }
        let token = DeadlineDiagnosticToken {
            owner: state.owner?,
            // The fixed population cap proves this conversion and uniqueness.
            id: u64::try_from(state.snapshot.identities.len()).expect("bounded identity count"),
        };
        state.snapshot.identities.push(DeadlineDiagnosticIdentity {
            token,
            activation_id: None,
        });
        push(&mut state, token, ingress);
        Some(token)
    }

    /// Bind exactly once. Duplicates, foreign tokens and invalid sizes invalidate
    /// coverage instead of truncating or aliasing an activation identity.
    #[must_use]
    pub fn bind(&self, token: DeadlineDiagnosticToken, activation_id: &str) -> bool {
        let mut state = self.lock();
        if !valid_token(&state, token)
            || activation_id.is_empty()
            || activation_id.len() > Self::MAXIMUM_IDENTIFIER_BYTES
            || state.snapshot.identities.iter().any(|identity| {
                identity.activation_id.as_deref() == Some(activation_id)
                    || (identity.token == token && identity.activation_id.is_some())
            })
        {
            state.snapshot.overflowed = true;
            return false;
        }
        state.snapshot.identities[usize::try_from(token.id).expect("validated token")]
            .activation_id = Some(activation_id.to_owned());
        true
    }

    /// Resolve before taking product locks. Unregistered invocations are outside
    /// this diagnostic population and do not create identities implicitly.
    #[must_use]
    pub fn token_for_activation(&self, activation_id: &str) -> Option<DeadlineDiagnosticToken> {
        self.lock()
            .snapshot
            .identities
            .iter()
            .find(|identity| identity.activation_id.as_deref() == Some(activation_id))
            .map(|identity| identity.token)
    }

    pub fn record(
        &self,
        token: DeadlineDiagnosticToken,
        observation: DeadlineDiagnosticObservation,
    ) {
        let mut state = self.lock();
        if !valid_token(&state, token) {
            state.snapshot.overflowed = true;
            return;
        }
        push(&mut state, token, observation);
    }

    pub fn record_for_activation(
        &self,
        activation_id: &str,
        observation: DeadlineDiagnosticObservation,
    ) {
        if let Some(token) = self.token_for_activation(activation_id) {
            self.record(token, observation);
        }
    }

    #[must_use]
    pub fn snapshot(&self) -> DeadlineDiagnosticSnapshot {
        self.lock().snapshot.clone()
    }

    fn lock(&self) -> MutexGuard<'_, State> {
        self.inner.lock().unwrap_or_else(|error| {
            let mut state = error.into_inner();
            state.snapshot.overflowed = true;
            state
        })
    }
}

fn valid_token(state: &State, token: DeadlineDiagnosticToken) -> bool {
    state.owner == Some(token.owner)
        && usize::try_from(token.id)
            .ok()
            .and_then(|id| state.snapshot.identities.get(id))
            .is_some_and(|identity| identity.token == token)
}

fn push(
    state: &mut State,
    token: DeadlineDiagnosticToken,
    observation: DeadlineDiagnosticObservation,
) {
    let snapshot = &mut state.snapshot;
    if snapshot.records.len() == state.maximum_records {
        snapshot.overflowed = true;
        return;
    }
    snapshot.records.push(DeadlineDiagnosticRecord {
        sequence: u64::try_from(snapshot.records.len()).expect("bounded record count"),
        token,
        observation,
    });
}

#[cfg(test)]
mod tests;
