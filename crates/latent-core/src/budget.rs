//! Hardened activation resource budgets, deadline grants, and accounting.

use std::fmt;
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::error::{ErrorDetail, PlatformError, PlatformErrorCode};
use crate::lifecycle::ActivationTerminalState;
use crate::Metadata;

/// One independently enforced resource dimension.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[non_exhaustive]
pub enum BudgetDimension {
    CpuFuel,
    MemoryBytes,
    WallTime,
    ChildCalls,
    OutboundRequests,
    StateReadBytes,
    StateWriteBytes,
    BlobReadBytes,
    BlobWriteBytes,
    LogBytes,
    EffectCount,
}

impl BudgetDimension {
    /// Stable lower-kebab-case name used in diagnostics and telemetry.
    #[must_use]
    pub const fn wire_name(self) -> &'static str {
        match self {
            Self::CpuFuel => "cpu-fuel",
            Self::MemoryBytes => "memory-bytes",
            Self::WallTime => "wall-time-micros",
            Self::ChildCalls => "child-calls",
            Self::OutboundRequests => "outbound-requests",
            Self::StateReadBytes => "state-read-bytes",
            Self::StateWriteBytes => "state-write-bytes",
            Self::BlobReadBytes => "blob-read-bytes",
            Self::BlobWriteBytes => "blob-write-bytes",
            Self::LogBytes => "log-bytes",
            Self::EffectCount => "effect-count",
        }
    }

    /// Whether Phase 1 actively enforces this dimension.
    #[must_use]
    pub const fn is_phase1_enforced(self) -> bool {
        matches!(
            self,
            Self::CpuFuel | Self::MemoryBytes | Self::WallTime | Self::LogBytes
        )
    }

    /// Whether this dimension is an additive counter.
    #[must_use]
    pub const fn is_cumulative(self) -> bool {
        !matches!(self, Self::MemoryBytes | Self::WallTime)
    }

    /// Every additive counter dimension.
    pub const CUMULATIVE: [Self; 9] = [
        Self::CpuFuel,
        Self::ChildCalls,
        Self::OutboundRequests,
        Self::StateReadBytes,
        Self::StateWriteBytes,
        Self::BlobReadBytes,
        Self::BlobWriteBytes,
        Self::LogBytes,
        Self::EffectCount,
    ];

    /// Dimensions whose implementation belongs to a later phase.
    pub const LATER_PHASE: [Self; 7] = [
        Self::ChildCalls,
        Self::OutboundRequests,
        Self::StateReadBytes,
        Self::StateWriteBytes,
        Self::BlobReadBytes,
        Self::BlobWriteBytes,
        Self::EffectCount,
    ];

    /// Every Phase 1-enforced dimension.
    pub const PHASE1_ENFORCED: [Self; 4] = [
        Self::CpuFuel,
        Self::MemoryBytes,
        Self::WallTime,
        Self::LogBytes,
    ];

    /// Dimensions whose terminal totals may be reported by an execution backend.
    /// Wall time is deliberately excluded because the host-owned monotonic clock
    /// is the authoritative source for terminal elapsed time.
    pub const PHASE1_REPORTED: [Self; 3] = [Self::CpuFuel, Self::MemoryBytes, Self::LogBytes];
}

/// Maximum resources delegated to an activation and its descendants.
///
/// Every numeric member is an exact hard ceiling: zero means that no amount of
/// that resource is granted. It never means "use a default". This makes the
/// same value safe to use in an invocation request, a deployment ceiling, and
/// a node ceiling.
///
/// `wall_time_limit_millis` is deliberately relative. It is measured from
/// admission/grant, never from deployment creation or document parsing. A
/// missing value adds no wall-time constraint; `Some(0)` grants no wall time.
/// An invocation's caller-supplied absolute deadline is carried separately by
/// the invocation envelope.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResourceBudget {
    pub cpu_fuel: u64,
    pub memory_bytes: u64,
    pub wall_time_limit_millis: Option<u64>,
    pub child_calls: u32,
    pub outbound_requests: u32,
    pub state_read_bytes: u64,
    pub state_write_bytes: u64,
    pub blob_read_bytes: u64,
    pub blob_write_bytes: u64,
    pub log_bytes: u64,
    pub effect_count: u32,
}

impl ResourceBudget {
    /// Returns the strict intersection of two independently granted budgets.
    ///
    /// `None` for a relative wall-time limit means that particular layer is
    /// unconstrained. All other dimensions are exact numeric ceilings.
    #[must_use]
    pub fn intersect(&self, ceiling: &Self) -> Self {
        Self {
            cpu_fuel: self.cpu_fuel.min(ceiling.cpu_fuel),
            memory_bytes: self.memory_bytes.min(ceiling.memory_bytes),
            wall_time_limit_millis: minimum_optional(
                self.wall_time_limit_millis,
                ceiling.wall_time_limit_millis,
            ),
            child_calls: self.child_calls.min(ceiling.child_calls),
            outbound_requests: self.outbound_requests.min(ceiling.outbound_requests),
            state_read_bytes: self.state_read_bytes.min(ceiling.state_read_bytes),
            state_write_bytes: self.state_write_bytes.min(ceiling.state_write_bytes),
            blob_read_bytes: self.blob_read_bytes.min(ceiling.blob_read_bytes),
            blob_write_bytes: self.blob_write_bytes.min(ceiling.blob_write_bytes),
            log_bytes: self.log_bytes.min(ceiling.log_bytes),
            effect_count: self.effect_count.min(ceiling.effect_count),
        }
    }

    /// Intersects request, deployment, and node ceilings and applies Phase 1's
    /// deliberately unavailable dimensions.
    pub fn phase1_effective(
        request: &Self,
        deployment_ceiling: &Self,
        node_ceiling: &Self,
    ) -> Result<Self, BudgetError> {
        request.validate_phase1_request()?;
        let mut effective = request
            .intersect(deployment_ceiling)
            .intersect(node_ceiling);
        effective.zero_later_phase_dimensions();
        Ok(effective)
    }

    /// Rejects callers that attempt to grant themselves capacity for a feature
    /// whose accounting is not implemented in Phase 1.
    pub fn validate_phase1_request(&self) -> Result<(), BudgetError> {
        for dimension in BudgetDimension::LATER_PHASE {
            let value = self.limit_for(dimension);
            if value != 0 {
                return Err(BudgetError::UnsupportedRequestDimension { dimension, value });
            }
        }
        Ok(())
    }

    /// Computes the absolute deadline using the contract-compatible saturating
    /// Unix-millisecond rule.
    ///
    /// New admission code should normally call [`EffectiveActivationBudget::admit_at`]
    /// so an already-expired or non-representable monotonic deadline is rejected.
    #[must_use]
    pub fn effective_deadline_unix_millis<'a>(
        admitted_at_unix_millis: u64,
        caller_deadline_unix_millis: Option<u64>,
        limits: impl IntoIterator<Item = &'a Self>,
    ) -> Option<u64> {
        limits
            .into_iter()
            .filter_map(|budget| {
                budget
                    .wall_time_limit_millis
                    .map(|limit| admitted_at_unix_millis.saturating_add(limit))
            })
            .fold(caller_deadline_unix_millis, |effective, candidate| {
                Some(effective.map_or(candidate, |current| current.min(candidate)))
            })
    }

    #[must_use]
    pub fn limit_for(&self, dimension: BudgetDimension) -> u64 {
        match dimension {
            BudgetDimension::CpuFuel => self.cpu_fuel,
            BudgetDimension::MemoryBytes => self.memory_bytes,
            BudgetDimension::WallTime => self
                .wall_time_limit_millis
                .map_or(u64::MAX, |millis| millis.saturating_mul(1_000)),
            BudgetDimension::ChildCalls => u64::from(self.child_calls),
            BudgetDimension::OutboundRequests => u64::from(self.outbound_requests),
            BudgetDimension::StateReadBytes => self.state_read_bytes,
            BudgetDimension::StateWriteBytes => self.state_write_bytes,
            BudgetDimension::BlobReadBytes => self.blob_read_bytes,
            BudgetDimension::BlobWriteBytes => self.blob_write_bytes,
            BudgetDimension::LogBytes => self.log_bytes,
            BudgetDimension::EffectCount => u64::from(self.effect_count),
        }
    }

    fn zero_later_phase_dimensions(&mut self) {
        self.child_calls = 0;
        self.outbound_requests = 0;
        self.state_read_bytes = 0;
        self.state_write_bytes = 0;
        self.blob_read_bytes = 0;
        self.blob_write_bytes = 0;
        self.effect_count = 0;
    }
}

fn minimum_optional(first: Option<u64>, second: Option<u64>) -> Option<u64> {
    match (first, second) {
        (Some(first), Some(second)) => Some(first.min(second)),
        (Some(value), None) | (None, Some(value)) => Some(value),
        (None, None) => None,
    }
}

/// Resources consumed by a completed or interrupted activation.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BudgetConsumption {
    pub cpu_fuel: u64,
    pub peak_memory_bytes: u64,
    pub wall_time_micros: u64,
    pub child_calls: u32,
    pub outbound_requests: u32,
    pub state_read_bytes: u64,
    pub state_write_bytes: u64,
    pub blob_read_bytes: u64,
    pub blob_write_bytes: u64,
    pub log_bytes: u64,
    pub effect_count: u32,
}

impl BudgetConsumption {
    #[must_use]
    pub fn consumed(&self, dimension: BudgetDimension) -> u64 {
        match dimension {
            BudgetDimension::CpuFuel => self.cpu_fuel,
            BudgetDimension::MemoryBytes => self.peak_memory_bytes,
            BudgetDimension::WallTime => self.wall_time_micros,
            BudgetDimension::ChildCalls => u64::from(self.child_calls),
            BudgetDimension::OutboundRequests => u64::from(self.outbound_requests),
            BudgetDimension::StateReadBytes => self.state_read_bytes,
            BudgetDimension::StateWriteBytes => self.state_write_bytes,
            BudgetDimension::BlobReadBytes => self.blob_read_bytes,
            BudgetDimension::BlobWriteBytes => self.blob_write_bytes,
            BudgetDimension::LogBytes => self.log_bytes,
            BudgetDimension::EffectCount => u64::from(self.effect_count),
        }
    }

    /// Validates backend-owned terminal totals against the granted Phase 1 budget.
    ///
    /// Wall time is intentionally excluded: terminal elapsed time is measured
    /// from the host-owned monotonic clock by [`ActivationBudget::finalize_at`].
    pub fn validate_phase1_report(&self, granted: &ResourceBudget) -> Result<(), BudgetError> {
        for dimension in BudgetDimension::LATER_PHASE {
            let value = self.consumed(dimension);
            if value != 0 {
                return Err(BudgetError::UnsupportedConsumptionDimension { dimension, value });
            }
        }
        for dimension in BudgetDimension::PHASE1_REPORTED {
            let consumed = self.consumed(dimension);
            let limit = granted.limit_for(dimension);
            if consumed > limit {
                return Err(BudgetError::exhausted(dimension, limit, consumed, 0));
            }
        }
        Ok(())
    }

    fn set_consumed(&mut self, dimension: BudgetDimension, value: u64) {
        match dimension {
            BudgetDimension::CpuFuel => self.cpu_fuel = value,
            BudgetDimension::MemoryBytes => self.peak_memory_bytes = value,
            BudgetDimension::WallTime => self.wall_time_micros = value,
            BudgetDimension::ChildCalls => {
                self.child_calls = u32::try_from(value).unwrap_or(u32::MAX);
            }
            BudgetDimension::OutboundRequests => {
                self.outbound_requests = u32::try_from(value).unwrap_or(u32::MAX);
            }
            BudgetDimension::StateReadBytes => self.state_read_bytes = value,
            BudgetDimension::StateWriteBytes => self.state_write_bytes = value,
            BudgetDimension::BlobReadBytes => self.blob_read_bytes = value,
            BudgetDimension::BlobWriteBytes => self.blob_write_bytes = value,
            BudgetDimension::LogBytes => self.log_bytes = value,
            BudgetDimension::EffectCount => {
                self.effect_count = u32::try_from(value).unwrap_or(u32::MAX);
            }
        }
    }
}

/// Coherent wall-clock and monotonic anchors captured for one admission.
///
/// System sampling always captures the monotonic anchor first. Any delay before
/// reading wall time therefore shortens the installed deadline instead of
/// extending a caller's absolute deadline.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ClockSample {
    unix_millis: u64,
    monotonic: Instant,
}

impl ClockSample {
    #[must_use]
    pub const fn new(unix_millis: u64, monotonic: Instant) -> Self {
        Self {
            unix_millis,
            monotonic,
        }
    }

    #[must_use]
    pub fn system_now() -> Self {
        let monotonic = Instant::now();
        let unix_millis = now_unix_millis();
        Self::new(unix_millis, monotonic)
    }

    #[must_use]
    pub const fn unix_millis(self) -> u64 {
        self.unix_millis
    }

    #[must_use]
    pub const fn monotonic(self) -> Instant {
        self.monotonic
    }
}

/// Wall-clock representation for APIs plus the monotonic deadline used after
/// admission.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EffectiveDeadline {
    admitted_at_unix_millis: u64,
    admitted_at_monotonic: Instant,
    unix_millis: Option<u64>,
    monotonic: Option<Instant>,
}

impl EffectiveDeadline {
    #[must_use]
    pub const fn admitted_at_unix_millis(&self) -> u64 {
        self.admitted_at_unix_millis
    }

    #[must_use]
    pub fn admitted_at_monotonic(&self) -> Instant {
        self.admitted_at_monotonic
    }

    #[must_use]
    pub const fn unix_millis(&self) -> Option<u64> {
        self.unix_millis
    }

    #[must_use]
    pub fn monotonic(&self) -> Option<Instant> {
        self.monotonic
    }

    #[must_use]
    pub fn is_expired_at(&self, now: Instant) -> bool {
        self.monotonic.is_some_and(|deadline| now >= deadline)
    }

    #[must_use]
    pub fn remaining_at(&self, now: Instant) -> Option<Duration> {
        self.monotonic
            .map(|deadline| deadline.saturating_duration_since(now))
    }
}

/// Result of deterministic request/deployment/node budget admission.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EffectiveActivationBudget {
    pub budget: ResourceBudget,
    pub deadline: EffectiveDeadline,
}

impl EffectiveActivationBudget {
    /// Computes one effective grant at a caller-supplied wall/monotonic clock
    /// sample. Supplying the clock sample makes boundary tests deterministic.
    pub fn admit_at(
        request: &ResourceBudget,
        deployment_ceiling: &ResourceBudget,
        node_ceiling: &ResourceBudget,
        caller_deadline_unix_millis: Option<u64>,
        sample: ClockSample,
    ) -> Result<Self, BudgetError> {
        let budget = ResourceBudget::phase1_effective(request, deployment_ceiling, node_ceiling)?;
        let admitted_at_unix_millis = sample.unix_millis();
        let admitted_at_monotonic = sample.monotonic();
        let unix_millis = ResourceBudget::effective_deadline_unix_millis(
            admitted_at_unix_millis,
            caller_deadline_unix_millis,
            [&budget],
        );
        let monotonic = match unix_millis {
            Some(deadline) if deadline <= admitted_at_unix_millis => {
                return Err(BudgetError::DeadlineExceeded {
                    deadline_unix_millis: deadline,
                    admitted_at_unix_millis,
                });
            }
            Some(deadline) => {
                let elapsed = Duration::from_millis(deadline - admitted_at_unix_millis);
                Some(admitted_at_monotonic.checked_add(elapsed).ok_or(
                    BudgetError::DeadlineOutOfRange {
                        deadline_unix_millis: deadline,
                        admitted_at_unix_millis,
                    },
                )?)
            }
            None => None,
        };

        Ok(Self {
            budget,
            deadline: EffectiveDeadline {
                admitted_at_unix_millis,
                admitted_at_monotonic,
                unix_millis,
                monotonic,
            },
        })
    }

    /// Computes one effective grant from the process clocks.
    pub fn admit_now(
        request: &ResourceBudget,
        deployment_ceiling: &ResourceBudget,
        node_ceiling: &ResourceBudget,
        caller_deadline_unix_millis: Option<u64>,
    ) -> Result<Self, BudgetError> {
        Self::admit_at(
            request,
            deployment_ceiling,
            node_ceiling,
            caller_deadline_unix_millis,
            ClockSample::system_now(),
        )
    }

    /// Rejects a grant that cannot execute even one instruction or own any
    /// linear memory. Zero remains a valid ceiling; this converts the resulting
    /// infeasible activation into a pre-allocation resource exhaustion.
    pub fn require_executable_capacity(&self) -> Result<(), BudgetError> {
        if self.budget.cpu_fuel == 0 {
            return Err(BudgetError::exhausted(BudgetDimension::CpuFuel, 0, 0, 1));
        }
        if self.budget.memory_bytes == 0 {
            return Err(BudgetError::exhausted(
                BudgetDimension::MemoryBytes,
                0,
                0,
                1,
            ));
        }
        Ok(())
    }
}

/// A deterministic budget validation or accounting failure.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum BudgetError {
    UnsupportedRequestDimension {
        dimension: BudgetDimension,
        value: u64,
    },
    UnsupportedConsumptionDimension {
        dimension: BudgetDimension,
        value: u64,
    },
    DeadlineExceeded {
        deadline_unix_millis: u64,
        admitted_at_unix_millis: u64,
    },
    DeadlineOutOfRange {
        deadline_unix_millis: u64,
        admitted_at_unix_millis: u64,
    },
    Exhausted {
        dimension: BudgetDimension,
        limit: u64,
        consumed: u64,
        requested: u64,
    },
    ArithmeticOverflow {
        dimension: BudgetDimension,
    },
    InvalidAccountingOperation {
        dimension: BudgetDimension,
    },
    AccountingFinalized,
}

impl BudgetError {
    fn exhausted(dimension: BudgetDimension, limit: u64, consumed: u64, requested: u64) -> Self {
        debug_assert_ne!(dimension, BudgetDimension::WallTime);
        Self::Exhausted {
            dimension,
            limit,
            consumed,
            requested,
        }
    }

    #[must_use]
    pub const fn platform_code(&self) -> PlatformErrorCode {
        match self {
            Self::UnsupportedRequestDimension { .. } | Self::DeadlineOutOfRange { .. } => {
                PlatformErrorCode::InvalidArgument
            }
            Self::DeadlineExceeded { .. } => PlatformErrorCode::DeadlineExceeded,
            Self::Exhausted { .. } => PlatformErrorCode::ResourceExhausted,
            Self::UnsupportedConsumptionDimension { .. }
            | Self::ArithmeticOverflow { .. }
            | Self::InvalidAccountingOperation { .. }
            | Self::AccountingFinalized => PlatformErrorCode::Internal,
        }
    }

    #[must_use]
    pub const fn terminal_state(&self) -> ActivationTerminalState {
        match self {
            Self::DeadlineExceeded { .. } => ActivationTerminalState::DeadlineExceeded,
            Self::Exhausted { .. } => ActivationTerminalState::ResourceExhausted,
            Self::UnsupportedRequestDimension { .. } | Self::DeadlineOutOfRange { .. } => {
                ActivationTerminalState::Rejected
            }
            Self::UnsupportedConsumptionDimension { .. }
            | Self::ArithmeticOverflow { .. }
            | Self::InvalidAccountingOperation { .. }
            | Self::AccountingFinalized => ActivationTerminalState::PlatformFailed,
        }
    }

    #[must_use]
    pub fn to_platform_error(&self) -> PlatformError {
        let mut fields = Metadata::new();
        let kind = match self {
            Self::UnsupportedRequestDimension { dimension, value } => {
                fields.insert("dimension".to_owned(), dimension.wire_name().to_owned());
                fields.insert("value".to_owned(), value.to_string());
                "budget.unsupported-request-dimension"
            }
            Self::UnsupportedConsumptionDimension { dimension, value } => {
                fields.insert("dimension".to_owned(), dimension.wire_name().to_owned());
                fields.insert("value".to_owned(), value.to_string());
                "budget.unsupported-consumption-dimension"
            }
            Self::DeadlineExceeded {
                deadline_unix_millis,
                admitted_at_unix_millis,
            } => {
                fields.insert(
                    "deadline_unix_millis".to_owned(),
                    deadline_unix_millis.to_string(),
                );
                fields.insert(
                    "admitted_at_unix_millis".to_owned(),
                    admitted_at_unix_millis.to_string(),
                );
                "activation.deadline-exceeded"
            }
            Self::DeadlineOutOfRange {
                deadline_unix_millis,
                admitted_at_unix_millis,
            } => {
                fields.insert(
                    "deadline_unix_millis".to_owned(),
                    deadline_unix_millis.to_string(),
                );
                fields.insert(
                    "admitted_at_unix_millis".to_owned(),
                    admitted_at_unix_millis.to_string(),
                );
                "budget.deadline-out-of-range"
            }
            Self::Exhausted {
                dimension,
                limit,
                consumed,
                requested,
            } => {
                fields.insert("dimension".to_owned(), dimension.wire_name().to_owned());
                fields.insert("limit".to_owned(), limit.to_string());
                fields.insert("consumed".to_owned(), consumed.to_string());
                fields.insert("requested".to_owned(), requested.to_string());
                "activation.resource-exhausted"
            }
            Self::ArithmeticOverflow { dimension } => {
                fields.insert("dimension".to_owned(), dimension.wire_name().to_owned());
                "budget.accounting-overflow"
            }
            Self::InvalidAccountingOperation { dimension } => {
                fields.insert("dimension".to_owned(), dimension.wire_name().to_owned());
                "budget.invalid-accounting-operation"
            }
            Self::AccountingFinalized => "budget.accounting-finalized",
        };
        PlatformError {
            code: self.platform_code(),
            message: self.to_string(),
            retryable: false,
            details: vec![ErrorDetail {
                kind: kind.to_owned(),
                fields,
            }],
        }
    }
}

impl fmt::Display for BudgetError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnsupportedRequestDimension { dimension, value } => write!(
                formatter,
                "Phase 1 invocation requests must set {} to zero, got {value}",
                dimension.wire_name()
            ),
            Self::UnsupportedConsumptionDimension { dimension, value } => write!(
                formatter,
                "Phase 1 terminal consumption must keep {} at zero, got {value}",
                dimension.wire_name()
            ),
            Self::DeadlineExceeded { .. } => {
                formatter.write_str("activation wall-clock deadline exceeded")
            }
            Self::DeadlineOutOfRange { .. } => {
                formatter.write_str("activation deadline cannot be represented monotonically")
            }
            Self::Exhausted {
                dimension,
                limit,
                consumed,
                requested,
            } => write!(
                formatter,
                "{} exhausted: limit={limit}, consumed={consumed}, requested={requested}",
                dimension.wire_name()
            ),
            Self::ArithmeticOverflow { dimension } => {
                write!(formatter, "{} accounting overflowed", dimension.wire_name())
            }
            Self::InvalidAccountingOperation { dimension } => write!(
                formatter,
                "{} does not support additive consumption",
                dimension.wire_name()
            ),
            Self::AccountingFinalized => {
                formatter.write_str("activation consumption is already finalized")
            }
        }
    }
}

impl std::error::Error for BudgetError {}

/// One repeatable terminal accounting transition.
///
/// Finalization always freezes `consumption`, even when an untrusted backend
/// report contains a deterministic violation. Callers use `violation` to choose
/// the terminal platform outcome without leaving the accounting state mutable.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BudgetFinalization {
    consumption: BudgetConsumption,
    violation: Option<BudgetError>,
}

impl BudgetFinalization {
    #[must_use]
    pub fn consumption(&self) -> &BudgetConsumption {
        &self.consumption
    }

    #[must_use]
    pub fn violation(&self) -> Option<&BudgetError> {
        self.violation.as_ref()
    }

    #[must_use]
    pub fn into_consumption(self) -> BudgetConsumption {
        self.consumption
    }
}

/// Thread-safe activation-scoped accounting state.
///
/// Clones share one state. All mutations and finalization are serialized so a
/// concurrent consumer cannot overflow, exceed a ceiling, race a refund, or
/// mutate a finalized report.
#[derive(Debug, Clone)]
pub struct ActivationBudget {
    inner: Arc<ActivationBudgetInner>,
}

#[derive(Debug)]
struct ActivationBudgetInner {
    granted: ResourceBudget,
    deadline: EffectiveDeadline,
    started_at: Instant,
    state: Mutex<AccountingState>,
}

#[derive(Debug, Default)]
struct AccountingState {
    consumption: BudgetConsumption,
    reserved: BudgetConsumption,
    finalized: Option<BudgetFinalization>,
    outstanding_reservations: u64,
}

impl ActivationBudget {
    #[must_use]
    pub fn new(grant: EffectiveActivationBudget) -> Self {
        let started_at = grant.deadline.admitted_at_monotonic();
        Self {
            inner: Arc::new(ActivationBudgetInner {
                granted: grant.budget,
                deadline: grant.deadline,
                started_at,
                state: Mutex::new(AccountingState::default()),
            }),
        }
    }

    #[must_use]
    pub fn granted(&self) -> &ResourceBudget {
        &self.inner.granted
    }

    /// Whether two handles refer to the same activation accounting state.
    #[must_use]
    pub fn is_same_instance(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.inner, &other.inner)
    }

    #[must_use]
    pub fn deadline(&self) -> &EffectiveDeadline {
        &self.inner.deadline
    }

    /// Consumes an additive counter atomically with respect to all other budget
    /// operations.
    pub fn consume(&self, dimension: BudgetDimension, amount: u64) -> Result<(), BudgetError> {
        if !dimension.is_cumulative() {
            return Err(BudgetError::InvalidAccountingOperation { dimension });
        }
        let mut state = self.lock_state();
        Self::ensure_mutable(&state)?;
        self.consume_locked(&mut state, dimension, amount)
    }

    pub fn consume_cpu_fuel(&self, amount: u64) -> Result<(), BudgetError> {
        self.consume(BudgetDimension::CpuFuel, amount)
    }

    pub fn consume_log_bytes(&self, amount: u64) -> Result<(), BudgetError> {
        self.consume(BudgetDimension::LogBytes, amount)
    }

    /// Reserves capacity immediately. Committing keeps it consumed; refunding
    /// or dropping the reservation releases it exactly once.
    pub fn reserve(
        &self,
        dimension: BudgetDimension,
        amount: u64,
    ) -> Result<BudgetReservation, BudgetError> {
        if !dimension.is_cumulative() {
            return Err(BudgetError::InvalidAccountingOperation { dimension });
        }
        let mut state = self.lock_state();
        Self::ensure_mutable(&state)?;
        let reservation_count = state
            .outstanding_reservations
            .checked_add(1)
            .ok_or(BudgetError::ArithmeticOverflow { dimension })?;
        let reserved = state.reserved.consumed(dimension);
        let reserved = reserved
            .checked_add(amount)
            .ok_or(BudgetError::ArithmeticOverflow { dimension })?;
        self.consume_locked(&mut state, dimension, amount)?;
        state.reserved.set_consumed(dimension, reserved);
        state.outstanding_reservations = reservation_count;
        Ok(BudgetReservation {
            budget: self.clone(),
            dimension,
            amount,
            active: true,
        })
    }

    pub fn reserve_log_bytes(&self, amount: u64) -> Result<BudgetReservation, BudgetError> {
        self.reserve(BudgetDimension::LogBytes, amount)
    }

    /// Records the highest observed linear-memory usage.
    pub fn observe_peak_memory(&self, bytes: u64) -> Result<(), BudgetError> {
        let mut state = self.lock_state();
        Self::ensure_mutable(&state)?;
        let limit = self.inner.granted.memory_bytes;
        if bytes > limit {
            return Err(BudgetError::Exhausted {
                dimension: BudgetDimension::MemoryBytes,
                limit,
                consumed: state.consumption.peak_memory_bytes,
                requested: bytes,
            });
        }
        state.consumption.peak_memory_bytes = state.consumption.peak_memory_bytes.max(bytes);
        Ok(())
    }

    /// Checks the monotonic deadline fixed at admission.
    pub fn check_deadline_at(&self, now: Instant) -> Result<(), BudgetError> {
        if self.inner.deadline.is_expired_at(now) {
            return Err(BudgetError::DeadlineExceeded {
                deadline_unix_millis: self
                    .inner
                    .deadline
                    .unix_millis()
                    .expect("an expired monotonic deadline has a Unix representation"),
                admitted_at_unix_millis: self.inner.deadline.admitted_at_unix_millis(),
            });
        }
        Ok(())
    }

    /// Returns a non-final snapshot. Wall time is measured monotonically.
    #[must_use]
    pub fn snapshot_at(&self, now: Instant) -> BudgetConsumption {
        let state = self.lock_state();
        if let Some(finalized) = &state.finalized {
            return finalized.consumption().clone();
        }
        let mut snapshot = state.consumption.clone();
        snapshot.wall_time_micros = snapshot.wall_time_micros.max(duration_micros(
            now.saturating_duration_since(self.inner.started_at),
        ));
        snapshot
    }

    /// Remaining Phase 1 budget, suitable for immutable activation context.
    #[must_use]
    pub fn remaining_at(&self, now: Instant) -> ResourceBudget {
        let snapshot = self.snapshot_at(now);
        ResourceBudget {
            cpu_fuel: self
                .inner
                .granted
                .cpu_fuel
                .saturating_sub(snapshot.cpu_fuel),
            memory_bytes: self
                .inner
                .granted
                .memory_bytes
                .saturating_sub(snapshot.peak_memory_bytes),
            wall_time_limit_millis: self.inner.deadline.remaining_at(now).map(duration_millis),
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: self
                .inner
                .granted
                .log_bytes
                .saturating_sub(snapshot.log_bytes),
            effect_count: 0,
        }
    }

    /// Finalizes terminal consumption exactly once and returns the same frozen
    /// transition on every subsequent call.
    ///
    /// Unresolved reservations are atomically refunded before the terminal
    /// snapshot is frozen. A reservation handle that loses this race observes
    /// [`BudgetError::AccountingFinalized`] from an explicit commit or refund,
    /// and dropping it cannot mutate the frozen result.
    ///
    /// `reported` is an execution backend's total terminal report. Host-owned
    /// monotonic elapsed time is authoritative for wall time, while valid CPU,
    /// peak-memory, and log totals are reconciled as lower bounds. An invalid
    /// report is retained as `violation` without preventing finalization.
    #[must_use]
    pub fn finalize_at(
        &self,
        reported: Option<&BudgetConsumption>,
        now: Instant,
    ) -> BudgetFinalization {
        let mut state = self.lock_state();
        if let Some(finalized) = &state.finalized {
            return finalized.clone();
        }

        let mut consumption = state.consumption.clone();
        for dimension in BudgetDimension::CUMULATIVE {
            let current = consumption.consumed(dimension);
            let reserved = state.reserved.consumed(dimension);
            debug_assert!(reserved <= current);
            consumption.set_consumed(dimension, current.saturating_sub(reserved));
        }
        consumption.wall_time_micros =
            duration_micros(now.saturating_duration_since(self.inner.started_at));

        let violation =
            reported.and_then(|report| report.validate_phase1_report(&self.inner.granted).err());
        if let Some(report) = reported {
            for dimension in BudgetDimension::PHASE1_REPORTED {
                let reported_value = report.consumed(dimension);
                if reported_value <= self.inner.granted.limit_for(dimension) {
                    consumption.set_consumed(
                        dimension,
                        consumption.consumed(dimension).max(reported_value),
                    );
                }
            }
        }

        let finalized = BudgetFinalization {
            consumption,
            violation,
        };
        state.consumption = finalized.consumption().clone();
        state.reserved = BudgetConsumption::default();
        state.outstanding_reservations = 0;
        state.finalized = Some(finalized.clone());
        finalized
    }

    #[must_use]
    pub fn finalization(&self) -> Option<BudgetFinalization> {
        self.lock_state().finalized.clone()
    }

    #[must_use]
    pub fn finalized(&self) -> Option<BudgetConsumption> {
        self.finalization()
            .map(BudgetFinalization::into_consumption)
    }

    #[must_use]
    pub fn outstanding_reservations(&self) -> u64 {
        self.lock_state().outstanding_reservations
    }

    fn consume_locked(
        &self,
        state: &mut AccountingState,
        dimension: BudgetDimension,
        amount: u64,
    ) -> Result<(), BudgetError> {
        let current = state.consumption.consumed(dimension);
        let next = current
            .checked_add(amount)
            .ok_or(BudgetError::ArithmeticOverflow { dimension })?;
        let limit = self.inner.granted.limit_for(dimension);
        if next > limit {
            return Err(BudgetError::Exhausted {
                dimension,
                limit,
                consumed: current,
                requested: amount,
            });
        }
        state.consumption.set_consumed(dimension, next);
        Ok(())
    }

    fn ensure_mutable(state: &AccountingState) -> Result<(), BudgetError> {
        if state.finalized.is_some() {
            return Err(BudgetError::AccountingFinalized);
        }
        Ok(())
    }

    fn lock_state(&self) -> MutexGuard<'_, AccountingState> {
        self.inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

/// One non-cloneable reservation with exactly-once commit/refund semantics.
#[must_use = "a budget reservation must be committed or refunded"]
pub struct BudgetReservation {
    budget: ActivationBudget,
    dimension: BudgetDimension,
    amount: u64,
    active: bool,
}

impl BudgetReservation {
    #[must_use]
    pub const fn dimension(&self) -> BudgetDimension {
        self.dimension
    }

    #[must_use]
    pub const fn amount(&self) -> u64 {
        self.amount
    }

    pub fn commit(mut self) -> Result<(), BudgetError> {
        self.close(false)
    }

    pub fn refund(mut self) -> Result<(), BudgetError> {
        self.close(true)
    }

    fn close(&mut self, refund: bool) -> Result<(), BudgetError> {
        if !self.active {
            return Ok(());
        }
        let mut state = self.budget.lock_state();
        if state.finalized.is_some() {
            self.active = false;
            return Err(BudgetError::AccountingFinalized);
        }

        let reservation_count = state.outstanding_reservations.checked_sub(1).ok_or(
            BudgetError::ArithmeticOverflow {
                dimension: self.dimension,
            },
        )?;
        let reserved = state.reserved.consumed(self.dimension);
        let reserved =
            reserved
                .checked_sub(self.amount)
                .ok_or(BudgetError::ArithmeticOverflow {
                    dimension: self.dimension,
                })?;
        let remaining = if refund {
            Some(
                state
                    .consumption
                    .consumed(self.dimension)
                    .checked_sub(self.amount)
                    .ok_or(BudgetError::ArithmeticOverflow {
                        dimension: self.dimension,
                    })?,
            )
        } else {
            None
        };

        state.outstanding_reservations = reservation_count;
        state.reserved.set_consumed(self.dimension, reserved);
        if let Some(remaining) = remaining {
            state.consumption.set_consumed(self.dimension, remaining);
        }
        self.active = false;
        Ok(())
    }
}

impl fmt::Debug for BudgetReservation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BudgetReservation")
            .field("dimension", &self.dimension)
            .field("amount", &self.amount)
            .field("active", &self.active)
            .finish_non_exhaustive()
    }
}

impl Drop for BudgetReservation {
    fn drop(&mut self) {
        let _ = self.close(true);
    }
}

fn duration_micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}

fn duration_millis(duration: Duration) -> u64 {
    u64::try_from(duration.as_millis()).unwrap_or(u64::MAX)
}

fn now_unix_millis() -> u64 {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis();
    u64::try_from(millis).unwrap_or(u64::MAX)
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::Barrier;
    use std::thread;

    use super::*;

    fn budget(wall_time_limit_millis: Option<u64>) -> ResourceBudget {
        ResourceBudget {
            cpu_fuel: 10,
            memory_bytes: 20,
            wall_time_limit_millis,
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 90,
            effect_count: 0,
        }
    }

    fn grant(budget: &ResourceBudget) -> EffectiveActivationBudget {
        let now = Instant::now();
        EffectiveActivationBudget::admit_at(
            budget,
            budget,
            budget,
            None,
            ClockSample::new(1_000, now),
        )
        .expect("test grant is valid")
    }

    #[test]
    fn intersection_uses_the_strictest_ceiling_without_default_zeroes() {
        let requested = budget(None);
        let mut deployment = budget(Some(250));
        deployment.cpu_fuel = 8;
        deployment.memory_bytes = 16;
        let mut node = budget(Some(500));
        node.log_bytes = 75;

        let granted = ResourceBudget::phase1_effective(&requested, &deployment, &node)
            .expect("budget is valid");

        assert_eq!(granted.cpu_fuel, 8);
        assert_eq!(granted.memory_bytes, 16);
        assert_eq!(granted.log_bytes, 75);
        assert_eq!(granted.wall_time_limit_millis, Some(250));
    }

    #[test]
    fn effective_deadline_combines_caller_and_relative_ceilings() {
        let request = budget(Some(500));
        let deployment = budget(Some(250));
        let node = budget(None);
        let admitted = Instant::now();

        let granted = EffectiveActivationBudget::admit_at(
            &request,
            &deployment,
            &node,
            Some(1_400),
            ClockSample::new(1_000, admitted),
        )
        .expect("deadline is valid");

        assert_eq!(granted.deadline.unix_millis(), Some(1_250));
        assert_eq!(
            granted.deadline.monotonic(),
            admitted.checked_add(Duration::from_millis(250))
        );
    }

    #[test]
    fn zero_relative_limit_is_explicit_and_rejected_as_already_expired() {
        let zero = budget(Some(0));
        let error = EffectiveActivationBudget::admit_at(
            &zero,
            &budget(None),
            &budget(None),
            None,
            ClockSample::new(1_000, Instant::now()),
        )
        .expect_err("zero wall time cannot survive admission");
        assert!(matches!(error, BudgetError::DeadlineExceeded { .. }));
    }

    #[test]
    fn an_old_absolute_deadline_is_rejected_but_reusable_ceilings_do_not_age() {
        let persistent = budget(Some(250));
        let admitted = Instant::now();
        let expired = EffectiveActivationBudget::admit_at(
            &budget(None),
            &persistent,
            &budget(None),
            Some(999),
            ClockSample::new(1_000, admitted),
        )
        .expect_err("caller deadline is expired");
        assert_eq!(expired.platform_code(), PlatformErrorCode::DeadlineExceeded);

        let later = EffectiveActivationBudget::admit_at(
            &budget(None),
            &persistent,
            &budget(None),
            None,
            ClockSample::new(9_000_000, admitted),
        )
        .expect("relative deployment ceiling remains valid");
        assert_eq!(later.deadline.unix_millis(), Some(9_000_250));
    }

    #[test]
    fn later_phase_request_capacity_is_rejected_and_effective_capacity_is_zero() {
        let mut request = budget(None);
        request.state_read_bytes = 1;
        assert!(matches!(
            ResourceBudget::phase1_effective(&request, &budget(None), &budget(None)),
            Err(BudgetError::UnsupportedRequestDimension {
                dimension: BudgetDimension::StateReadBytes,
                value: 1,
            })
        ));

        let mut deployment = budget(None);
        deployment.state_read_bytes = 10_000;
        let effective = ResourceBudget::phase1_effective(&budget(None), &deployment, &deployment)
            .expect("reusable future ceilings are harmless in Phase 1");
        assert_eq!(effective.state_read_bytes, 0);
    }

    #[test]
    fn concurrent_consumption_never_exceeds_the_grant() {
        let mut allowed = budget(None);
        allowed.cpu_fuel = 1_000;
        let accounting = ActivationBudget::new(grant(&allowed));
        let successes = Arc::new(AtomicU64::new(0));
        let mut workers = Vec::new();
        for _ in 0..16 {
            let accounting = accounting.clone();
            let successes = Arc::clone(&successes);
            workers.push(thread::spawn(move || {
                for _ in 0..200 {
                    if accounting.consume_cpu_fuel(1).is_ok() {
                        successes.fetch_add(1, Ordering::Relaxed);
                    }
                }
            }));
        }
        for worker in workers {
            worker.join().expect("worker completes");
        }
        assert_eq!(successes.load(Ordering::Relaxed), 1_000);
        assert_eq!(accounting.snapshot_at(Instant::now()).cpu_fuel, 1_000);
    }

    #[test]
    fn reservations_commit_refund_and_drop_exactly_once() {
        let accounting = ActivationBudget::new(grant(&budget(None)));
        accounting
            .reserve_log_bytes(10)
            .expect("first reservation")
            .commit()
            .expect("commit succeeds");
        accounting
            .reserve_log_bytes(20)
            .expect("second reservation")
            .refund()
            .expect("refund succeeds");
        {
            let _dropped = accounting.reserve_log_bytes(30).expect("drop reservation");
        }
        assert_eq!(accounting.snapshot_at(Instant::now()).log_bytes, 10);
        assert_eq!(accounting.outstanding_reservations(), 0);
    }

    #[test]
    fn peak_memory_is_monotonic_and_bounded() {
        let accounting = ActivationBudget::new(grant(&budget(None)));
        accounting.observe_peak_memory(12).expect("within limit");
        accounting.observe_peak_memory(4).expect("lower sample");
        assert_eq!(accounting.snapshot_at(Instant::now()).peak_memory_bytes, 12);
        assert!(matches!(
            accounting.observe_peak_memory(21),
            Err(BudgetError::Exhausted {
                dimension: BudgetDimension::MemoryBytes,
                ..
            })
        ));
    }

    #[test]
    fn finalization_is_idempotent_and_freezes_all_counters() {
        let accounting = ActivationBudget::new(grant(&budget(None)));
        accounting.consume_cpu_fuel(3).expect("fuel consumed");
        let reported = BudgetConsumption {
            cpu_fuel: 5,
            peak_memory_bytes: 7,
            log_bytes: 11,
            ..BudgetConsumption::default()
        };
        let now = Instant::now();
        let first = accounting.finalize_at(Some(&reported), now);
        let second = accounting.finalize_at(None, now + Duration::from_secs(1));
        assert_eq!(first, second);
        assert!(first.violation().is_none());
        assert_eq!(accounting.finalization(), Some(first.clone()));
        assert_eq!(accounting.finalized(), Some(first.consumption().clone()));
        assert!(matches!(
            accounting.consume_cpu_fuel(1),
            Err(BudgetError::AccountingFinalized)
        ));
    }

    #[test]
    fn deadline_exhaustion_freezes_truthful_repeatable_accounting() {
        let mut limited = budget(Some(10));
        limited.cpu_fuel = 100;
        let admitted = Instant::now();
        let grant = EffectiveActivationBudget::admit_at(
            &limited,
            &limited,
            &limited,
            None,
            ClockSample::new(1_000, admitted),
        )
        .expect("deadline grant is valid");
        let accounting = ActivationBudget::new(grant);
        let terminal = admitted + Duration::from_millis(12);

        let error = accounting
            .check_deadline_at(terminal)
            .expect_err("deadline is exhausted");
        assert_eq!(
            error,
            BudgetError::DeadlineExceeded {
                deadline_unix_millis: 1_010,
                admitted_at_unix_millis: 1_000,
            }
        );
        let platform = error.to_platform_error();
        assert_eq!(
            platform.details[0].fields.get("deadline_unix_millis"),
            Some(&"1010".to_owned())
        );
        assert_eq!(
            platform.details[0].fields.get("admitted_at_unix_millis"),
            Some(&"1000".to_owned())
        );

        let first = accounting.finalize_at(None, terminal);
        let later = accounting.finalize_at(None, terminal + Duration::from_secs(1));
        assert_eq!(first, later);
        assert_eq!(first.consumption().wall_time_micros, 12_000);
        assert_eq!(accounting.finalized(), Some(first.consumption().clone()));
        assert!(matches!(
            accounting.consume_cpu_fuel(1),
            Err(BudgetError::AccountingFinalized)
        ));
    }

    #[test]
    fn terminalization_refunds_unresolved_reservations_atomically() {
        let accounting = ActivationBudget::new(grant(&budget(None)));
        let reservation = accounting
            .reserve_log_bytes(20)
            .expect("reservation succeeds");
        let first = accounting.finalize_at(None, Instant::now());
        assert_eq!(first.consumption().log_bytes, 0);
        assert_eq!(accounting.outstanding_reservations(), 0);
        assert!(matches!(
            reservation.refund(),
            Err(BudgetError::AccountingFinalized)
        ));
        assert_eq!(accounting.finalization(), Some(first));

        let accounting = ActivationBudget::new(grant(&budget(None)));
        let reservation = accounting
            .reserve_log_bytes(30)
            .expect("reservation succeeds");
        let first = accounting.finalize_at(None, Instant::now());
        drop(reservation);
        assert_eq!(accounting.finalization(), Some(first));
        assert_eq!(accounting.outstanding_reservations(), 0);
        assert_eq!(accounting.finalized().expect("frozen").log_bytes, 0);
    }

    #[test]
    fn reservation_and_finalization_race_has_one_atomic_winner() {
        for _ in 0..128 {
            let accounting = ActivationBudget::new(grant(&budget(None)));
            let barrier = Arc::new(Barrier::new(3));

            let reserve_accounting = accounting.clone();
            let reserve_barrier = Arc::clone(&barrier);
            let reserve = thread::spawn(move || {
                reserve_barrier.wait();
                reserve_accounting.reserve_log_bytes(10)
            });

            let finalize_accounting = accounting.clone();
            let finalize_barrier = Arc::clone(&barrier);
            let finalize = thread::spawn(move || {
                finalize_barrier.wait();
                finalize_accounting.finalize_at(None, Instant::now())
            });

            barrier.wait();
            let reservation = reserve.join().expect("reservation racer completes");
            let finalized = finalize.join().expect("finalizer completes");
            assert_eq!(finalized.consumption().log_bytes, 0);
            assert_eq!(accounting.outstanding_reservations(), 0);
            match reservation {
                Ok(reservation) => assert!(matches!(
                    reservation.refund(),
                    Err(BudgetError::AccountingFinalized)
                )),
                Err(BudgetError::AccountingFinalized) => {}
                Err(error) => panic!("unexpected reservation race error: {error}"),
            }
            assert_eq!(accounting.finalization(), Some(finalized));
        }
    }

    #[test]
    fn forged_later_phase_terminal_consumption_is_rejected_and_frozen() {
        let accounting = ActivationBudget::new(grant(&budget(None)));
        let reported = BudgetConsumption {
            cpu_fuel: 4,
            effect_count: 1,
            ..BudgetConsumption::default()
        };
        let first = accounting.finalize_at(Some(&reported), Instant::now());
        assert!(matches!(
            first.violation(),
            Some(BudgetError::UnsupportedConsumptionDimension {
                dimension: BudgetDimension::EffectCount,
                value: 1,
            })
        ));
        assert_eq!(first.consumption().cpu_fuel, 4);
        assert_eq!(first.consumption().effect_count, 0);
        assert_eq!(accounting.finalization(), Some(first.clone()));
        assert_eq!(
            accounting.finalize_at(None, Instant::now() + Duration::from_secs(1)),
            first
        );
        assert!(matches!(
            accounting.consume_log_bytes(1),
            Err(BudgetError::AccountingFinalized)
        ));
    }

    #[test]
    fn every_enforced_dimension_has_a_stable_terminal_mapping() {
        for dimension in BudgetDimension::PHASE1_ENFORCED {
            let error = if dimension == BudgetDimension::WallTime {
                BudgetError::DeadlineExceeded {
                    deadline_unix_millis: 10,
                    admitted_at_unix_millis: 5,
                }
            } else {
                BudgetError::Exhausted {
                    dimension,
                    limit: 1,
                    consumed: 1,
                    requested: 1,
                }
            };
            let platform = error.to_platform_error();
            if dimension == BudgetDimension::WallTime {
                assert_eq!(platform.code, PlatformErrorCode::DeadlineExceeded);
                assert_eq!(
                    error.terminal_state(),
                    ActivationTerminalState::DeadlineExceeded
                );
            } else {
                assert_eq!(platform.code, PlatformErrorCode::ResourceExhausted);
                assert_eq!(
                    error.terminal_state(),
                    ActivationTerminalState::ResourceExhausted
                );
            }
            assert_eq!(platform.details.len(), 1);
        }
    }

    #[test]
    fn intersection_and_deadline_property_never_exceed_any_input() {
        let mut seed = 0x9e37_79b9_7f4a_7c15_u64;
        let admitted_unix_millis = 1_000_000_u64;
        let admitted_monotonic = Instant::now();
        for _ in 0..10_000 {
            seed = seed.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
            let request_wall = seed % 10_000 + 1;
            let request = ResourceBudget {
                cpu_fuel: seed,
                memory_bytes: seed.rotate_left(7),
                wall_time_limit_millis: Some(request_wall),
                child_calls: 0,
                outbound_requests: 0,
                state_read_bytes: 0,
                state_write_bytes: 0,
                blob_read_bytes: 0,
                blob_write_bytes: 0,
                log_bytes: seed.rotate_left(29),
                effect_count: 0,
            };
            seed = seed.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
            let deployment_wall = seed % 10_000 + 1;
            let deployment = ResourceBudget {
                cpu_fuel: seed,
                memory_bytes: seed.rotate_left(7),
                wall_time_limit_millis: Some(deployment_wall),
                child_calls: 0,
                outbound_requests: 0,
                state_read_bytes: 0,
                state_write_bytes: 0,
                blob_read_bytes: 0,
                blob_write_bytes: 0,
                log_bytes: seed.rotate_left(29),
                effect_count: 0,
            };
            seed = seed.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
            let node_wall = seed % 10_000 + 1;
            let node = ResourceBudget {
                cpu_fuel: seed,
                memory_bytes: seed.rotate_left(7),
                wall_time_limit_millis: Some(node_wall),
                child_calls: 0,
                outbound_requests: 0,
                state_read_bytes: 0,
                state_write_bytes: 0,
                blob_read_bytes: 0,
                blob_write_bytes: 0,
                log_bytes: seed.rotate_left(29),
                effect_count: 0,
            };
            let caller_delta = seed.rotate_left(41) % 10_000 + 1;
            let caller_deadline = admitted_unix_millis + caller_delta;

            let effective = ResourceBudget::phase1_effective(&request, &deployment, &node)
                .expect("generated budget is valid");
            assert!(effective.cpu_fuel <= request.cpu_fuel);
            assert!(effective.cpu_fuel <= deployment.cpu_fuel);
            assert!(effective.cpu_fuel <= node.cpu_fuel);
            assert!(effective.memory_bytes <= request.memory_bytes);
            assert!(effective.memory_bytes <= deployment.memory_bytes);
            assert!(effective.memory_bytes <= node.memory_bytes);
            assert!(effective.log_bytes <= request.log_bytes);
            assert!(effective.log_bytes <= deployment.log_bytes);
            assert!(effective.log_bytes <= node.log_bytes);
            let effective_wall = effective
                .wall_time_limit_millis
                .expect("all generated ceilings are bounded");
            assert!(effective_wall <= request_wall);
            assert!(effective_wall <= deployment_wall);
            assert!(effective_wall <= node_wall);

            let grant = EffectiveActivationBudget::admit_at(
                &request,
                &deployment,
                &node,
                Some(caller_deadline),
                ClockSample::new(admitted_unix_millis, admitted_monotonic),
            )
            .expect("generated deadline is representable");
            let deadline_unix = grant.deadline.unix_millis().expect("bounded deadline");
            assert!(deadline_unix <= caller_deadline);
            assert!(deadline_unix <= admitted_unix_millis + request_wall);
            assert!(deadline_unix <= admitted_unix_millis + deployment_wall);
            assert!(deadline_unix <= admitted_unix_millis + node_wall);
            let deadline_monotonic = grant.deadline.monotonic().expect("bounded deadline");
            assert!(deadline_monotonic <= admitted_monotonic + Duration::from_millis(caller_delta));
            assert!(
                deadline_monotonic <= admitted_monotonic + Duration::from_millis(effective_wall)
            );
        }
    }
}
