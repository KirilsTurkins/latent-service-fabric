//! Finite, deterministic reference model for ADR-0062 and issue #380.
//!
//! This model has no filesystem, engine, provider, executor, clock or RPC implementation.
//! Its atomic `DurableImage` replacement describes the required storage boundary; it
//! does not prove atomic writes, power-loss durability, physical cleanup or authority
//! sealing in a production host. Model-issued grants and private attempt state let
//! schedules distinguish current authority, durable disposition and retired owners.

use std::collections::{BTreeMap, BTreeSet};

/// Owned, finite prefix-page entries in the model.
pub type StateEntries = Vec<(Vec<u8>, Vec<u8>)>;

/// One authenticated namespace and, optionally, one entity. A host must derive
/// `recovery_scope`; accepting this descriptive value is not a production grant.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct Scope {
    pub tenant: String,
    pub namespace: String,
    pub incarnation: u64,
    pub recovery_scope: String,
    pub operation: String,
    pub entity: Option<String>,
}

/// Route, executable revision, activation and session credentials are deliberately absent.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct CommandKey {
    pub scope: Scope,
    pub caller_key: String,
}

/// Canonical application bytes and original stale-edit precondition are immutable.
/// Production #382 supplies the versioned canonical encoding and digest.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommandBody {
    pub bytes: Vec<u8>,
    pub expected_version: Option<ViewVersion>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ViewVersion {
    pub incarnation: u64,
    pub generation: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct CommandAttemptId {
    generation: u64,
    transaction: u64,
    physical_owner: u64,
}

impl CommandAttemptId {
    #[must_use]
    pub fn generation(self) -> u64 {
        self.generation
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AbortFence {
    key: CommandKey,
    attempt: CommandAttemptId,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct EffectId {
    transaction: u64,
    sequence: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProcessedInputIdentity {
    pub binding: String,
    pub message_id: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DurableFormats {
    pub state_schema: u16,
    pub result: u16,
    pub intent: u16,
    pub inbox: u16,
    pub ordering: u16,
    pub checkpoint: u16,
}

impl Default for DurableFormats {
    fn default() -> Self {
        Self {
            state_schema: 1,
            result: 1,
            intent: 1,
            inbox: 1,
            ordering: 1,
            checkpoint: 1,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommitReceipt {
    pub key: CommandKey,
    pub attempt: CommandAttemptId,
    pub version: ViewVersion,
    pub business_committed: bool,
    pub effects: Vec<EffectId>,
    pub formats: DurableFormats,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DurableOutcome {
    InProgress(CommandAttemptId),
    Committed(CommitReceipt),
    BusinessRejected(CommitReceipt),
    TechnicalAborted {
        attempt: CommandAttemptId,
        owners_retired: bool,
    },
    RecoveryRequired(CommandAttemptId),
    /// Absence, expiry and unknown history do not provide affirmative abort proof.
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Admission {
    Execute(CommandAttemptId),
    Existing(Box<DurableOutcome>),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RecoveredResult {
    pub outcome: DurableOutcome,
    /// Absence means receipt-only recovery; it does not erase the command identity.
    pub payload: Option<Vec<u8>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CleanupStatus {
    Owned,
    Retired,
    Quarantined,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Cancellation {
    AbortedBeforeCommit,
    CommitMayHaveOccurred,
    AlreadyTerminal,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModelError {
    Invalid,
    PermissionDenied,
    ScopeMismatch,
    ChangedBody,
    Conflict,
    StaleEdit,
    StaleAttempt,
    NotEligible,
    StagingClosed,
    Limit,
    ForbiddenCapability,
    AbortUnproven,
    DuplicateInput,
    AcknowledgementBeforeDurableDisposition,
    RetainedFormatRequired,
    LinkedRetention,
    ClockDiscontinuity,
    RestorePaused,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GuestOutcome {
    Successful,
    TerminalBusinessRejection,
    TechnicalFailure,
}

/// These are reviewed semantic classes, never classifications by HTTP method or
/// an application's claimed purity. Runtime support confers no application authority.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CapabilityClass {
    RuntimeClock,
    RuntimeEntropy,
    RuntimeLogging,
    RuntimeGc,
    RuntimeSuspension,
    ReviewedReadOnly,
    ImmediateApplicationEffect,
    UnsupportedSynchronousChild,
    Unclassified,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RetentionTime {
    QualifiedElapsed(u64),
    Discontinuous,
}

#[derive(Debug, Clone)]
pub struct Limits {
    pub key_bytes: usize,
    pub value_bytes: usize,
    pub result_bytes: usize,
    pub scan_entries: usize,
    pub scan_bytes: usize,
    pub mutations: usize,
    pub intents: usize,
    pub envelope_bytes: usize,
    pub admitted_commands: usize,
    /// Model recovery is read-only and uses this separate finite response capacity.
    pub recovery_bytes: usize,
    pub support_operations: usize,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            key_bytes: 1024,
            value_bytes: 1024 * 1024,
            result_bytes: 1024 * 1024,
            scan_entries: 128,
            scan_bytes: 1024 * 1024,
            mutations: 128,
            intents: 32,
            envelope_bytes: 8 * 1024 * 1024,
            admitted_commands: 128,
            recovery_bytes: 2 * 1024 * 1024,
            support_operations: 128,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Permissions {
    pub command: bool,
    pub query: bool,
    pub result_read: bool,
    /// Models the current application/result policy, including any original business check.
    pub result_policy: u64,
}

/// Created only by the model's host-side grant method; command/effect IDs mint no grants.
#[derive(Debug, Clone)]
pub struct Authority {
    scope: Scope,
    epoch: u64,
    permissions: Permissions,
}

#[derive(Debug, Clone)]
struct CommandRecord {
    body: CommandBody,
    outcome: DurableOutcome,
    payload: Option<Vec<u8>>,
    result_policy: u64,
    input: Option<ProcessedInputIdentity>,
    result_format: u16,
}

#[derive(Debug, Clone)]
struct Intent {
    command: CommandKey,
    payload: Vec<u8>,
    format: u16,
    unresolved: bool,
}

/// Owned model snapshot. Cloning/replacement stands for, but does not implement,
/// the qualified engine's one physical atomic envelope.
#[derive(Debug, Clone)]
pub struct DurableImage {
    tenant: String,
    namespace: String,
    version: ViewVersion,
    state: BTreeMap<Vec<u8>, Vec<u8>>,
    commands: BTreeMap<CommandKey, CommandRecord>,
    intents: BTreeMap<EffectId, Intent>,
    inbox: BTreeMap<(String, String), CommandKey>,
    formats: DurableFormats,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Phase {
    Staging,
    Eligible,
    CommitInFlight,
    Committed,
    Rejected,
    Aborted,
    RecoveryRequired,
}

#[derive(Debug, Clone)]
struct Activation {
    id: u64,
    authority: Authority,
    key: CommandKey,
    snapshot: BTreeMap<Vec<u8>, Vec<u8>>,
    version: ViewVersion,
    mutations: BTreeMap<Vec<u8>, Option<Vec<u8>>>,
    intents: Vec<Vec<u8>>,
    guest_outcome: Option<GuestOutcome>,
    outputs_validated: bool,
    output: Vec<u8>,
    required_work: usize,
    support_operations: usize,
    phase: Phase,
    cleanup: CleanupStatus,
}

#[derive(Debug, Clone)]
pub struct QueryView {
    version: ViewVersion,
    physical_owner: u64,
    authority: Authority,
    snapshot: BTreeMap<Vec<u8>, Vec<u8>>,
    returned_bytes: usize,
    returned_entries: usize,
}

impl QueryView {
    #[must_use]
    pub fn version(&self) -> ViewVersion {
        self.version
    }
}

/// A single tenant/namespace reference machine; multiple instances cannot transact together.
#[derive(Debug)]
pub struct TransactionModel {
    image: DurableImage,
    limits: Limits,
    grants: BTreeMap<Scope, (u64, Permissions)>,
    next_grant: u64,
    next_transaction: u64,
    physical_owner: u64,
    active: BTreeMap<CommandAttemptId, Activation>,
    effects_paused: bool,
}

impl TransactionModel {
    pub fn new(tenant: String, namespace: String, limits: Limits) -> Result<Self, ModelError> {
        if tenant.is_empty()
            || namespace.is_empty()
            || limits.recovery_bytes == 0
            || limits.recovery_bytes < limits.result_bytes
        {
            return Err(ModelError::Invalid);
        }
        Ok(Self {
            image: DurableImage {
                tenant,
                namespace,
                version: ViewVersion {
                    incarnation: 1,
                    generation: 0,
                },
                state: BTreeMap::new(),
                commands: BTreeMap::new(),
                intents: BTreeMap::new(),
                inbox: BTreeMap::new(),
                formats: DurableFormats::default(),
            },
            limits,
            grants: BTreeMap::new(),
            next_grant: 1,
            next_transaction: 1,
            physical_owner: 1,
            active: BTreeMap::new(),
            effects_paused: false,
        })
    }

    /// Host decision: delegated/shared recovery scopes need explicit authorization here.
    pub fn grant(
        &mut self,
        scope: Scope,
        permissions: Permissions,
    ) -> Result<Authority, ModelError> {
        self.check_scope(&scope)?;
        let epoch = self.next_grant;
        self.next_grant = epoch.checked_add(1).ok_or(ModelError::Limit)?;
        self.grants.insert(scope.clone(), (epoch, permissions));
        Ok(Authority {
            scope,
            epoch,
            permissions,
        })
    }

    pub fn admit(
        &mut self,
        authority: &Authority,
        key: CommandKey,
        body: CommandBody,
        activation_id: u64,
        input: Option<ProcessedInputIdentity>,
    ) -> Result<Admission, ModelError> {
        self.check_authority(authority, &key.scope)?;
        if !authority.permissions.command {
            return Err(ModelError::PermissionDenied);
        }
        if key.caller_key.is_empty()
            || key.caller_key.len() > 256
            || body.bytes.is_empty()
            || body.bytes.len() > self.limits.value_bytes
            || activation_id == 0
        {
            return Err(ModelError::Invalid);
        }
        if let Some(record) = self.image.commands.get(&key) {
            self.check_result_authority(authority, &key, record)?;
            if record.body != body || record.input != input {
                return Err(ModelError::ChangedBody);
            }
            return Ok(Admission::Existing(Box::new(record.outcome.clone())));
        }
        if self.effects_paused {
            return Err(ModelError::RestorePaused);
        }
        if body
            .expected_version
            .is_some_and(|expected| expected != self.image.version)
        {
            return Err(ModelError::StaleEdit);
        }
        if let Some(identity) = &input {
            if identity.binding.is_empty()
                || identity.message_id.is_empty()
                || identity.binding.len() > 256
                || identity.message_id.len() > 256
            {
                return Err(ModelError::Invalid);
            }
            if self
                .image
                .inbox
                .contains_key(&(identity.binding.clone(), identity.message_id.clone()))
            {
                return Err(ModelError::DuplicateInput);
            }
        }
        if self.image.commands.len() >= self.limits.admitted_commands {
            return Err(ModelError::Limit);
        }
        let attempt = self.start(authority, key.clone(), 1, activation_id)?;
        self.image.commands.insert(
            key,
            CommandRecord {
                body,
                outcome: DurableOutcome::InProgress(attempt),
                payload: None,
                result_policy: authority.permissions.result_policy,
                input,
                result_format: self.image.formats.result,
            },
        );
        Ok(Admission::Execute(attempt))
    }

    fn start(
        &mut self,
        authority: &Authority,
        key: CommandKey,
        generation: u64,
        activation_id: u64,
    ) -> Result<CommandAttemptId, ModelError> {
        if activation_id == 0
            || self
                .active
                .values()
                .any(|active| active.id == activation_id && active.cleanup == CleanupStatus::Owned)
        {
            return Err(ModelError::Invalid);
        }
        let transaction = self.next_transaction;
        self.next_transaction = transaction.checked_add(1).ok_or(ModelError::Limit)?;
        let attempt = CommandAttemptId {
            generation,
            transaction,
            physical_owner: self.physical_owner,
        };
        self.active.insert(
            attempt,
            Activation {
                id: activation_id,
                authority: authority.clone(),
                key,
                snapshot: self.image.state.clone(),
                version: self.image.version,
                mutations: BTreeMap::new(),
                intents: Vec::new(),
                guest_outcome: None,
                outputs_validated: false,
                output: Vec::new(),
                required_work: 0,
                support_operations: 0,
                phase: Phase::Staging,
                cleanup: CleanupStatus::Owned,
            },
        );
        Ok(attempt)
    }

    pub fn get(
        &self,
        attempt: CommandAttemptId,
        key: &[u8],
    ) -> Result<Option<Vec<u8>>, ModelError> {
        self.check_key(key)?;
        let active = self.staging(attempt)?;
        Ok(active
            .mutations
            .get(key)
            .cloned()
            .unwrap_or_else(|| active.snapshot.get(key).cloned()))
    }

    pub fn scan(
        &self,
        attempt: CommandAttemptId,
        prefix: &[u8],
        limit: usize,
    ) -> Result<StateEntries, ModelError> {
        if prefix.len() > self.limits.key_bytes || limit == 0 || limit > self.limits.scan_entries {
            return Err(ModelError::Limit);
        }
        let active = self.staging(attempt)?;
        let mut view = active.snapshot.clone();
        apply_mutations(&mut view, &active.mutations);
        let entries: Vec<_> = view
            .into_iter()
            .filter(|(key, _)| key.starts_with(prefix))
            .take(limit)
            .collect();
        if entries
            .iter()
            .map(|(key, value)| key.len() + value.len())
            .sum::<usize>()
            > self.limits.scan_bytes
        {
            return Err(ModelError::Limit);
        }
        Ok(entries)
    }

    pub fn put(
        &mut self,
        attempt: CommandAttemptId,
        key: Vec<u8>,
        value: Vec<u8>,
    ) -> Result<(), ModelError> {
        self.check_key(&key)?;
        if value.len() > self.limits.value_bytes {
            return Err(ModelError::Limit);
        }
        self.stage_mutation(attempt, key, Some(value))
    }

    pub fn delete(&mut self, attempt: CommandAttemptId, key: Vec<u8>) -> Result<(), ModelError> {
        self.check_key(&key)?;
        self.stage_mutation(attempt, key, None)
    }

    fn stage_mutation(
        &mut self,
        attempt: CommandAttemptId,
        key: Vec<u8>,
        value: Option<Vec<u8>>,
    ) -> Result<(), ModelError> {
        let maximum = self.limits.mutations;
        let active = self.staging_mut(attempt)?;
        if !active.mutations.contains_key(&key) && active.mutations.len() >= maximum {
            return Err(ModelError::Limit);
        }
        active.mutations.insert(key, value);
        Ok(())
    }

    /// Stages owned payload only. A real host selects approved bindings, dispatch
    /// authority, expiry and attempt budgets; the guest supplies none of those grants.
    pub fn stage_intent(
        &mut self,
        attempt: CommandAttemptId,
        payload: Vec<u8>,
    ) -> Result<u32, ModelError> {
        if payload.len() > self.limits.value_bytes {
            return Err(ModelError::Limit);
        }
        let maximum = self.limits.intents;
        let active = self.staging_mut(attempt)?;
        if active.intents.len() >= maximum {
            return Err(ModelError::Limit);
        }
        let sequence = u32::try_from(active.intents.len()).map_err(|_| ModelError::Limit)?;
        active.intents.push(payload);
        Ok(sequence)
    }

    pub fn capability(
        &mut self,
        attempt: CommandAttemptId,
        class: CapabilityClass,
        reviewed: bool,
    ) -> Result<(), ModelError> {
        if !reviewed
            || matches!(
                class,
                CapabilityClass::ImmediateApplicationEffect
                    | CapabilityClass::UnsupportedSynchronousChild
                    | CapabilityClass::Unclassified
            )
        {
            return Err(ModelError::ForbiddenCapability);
        }
        let maximum = self.limits.support_operations;
        let active = self.staging_mut(attempt)?;
        if active.support_operations >= maximum {
            return Err(ModelError::Limit);
        }
        active.support_operations += 1;
        Ok(())
    }

    /// The selected language profile defines which accepted work must settle.
    pub fn accept_required_work(&mut self, attempt: CommandAttemptId) -> Result<(), ModelError> {
        let active = self.staging_mut(attempt)?;
        active.required_work = active
            .required_work
            .checked_add(1)
            .ok_or(ModelError::Limit)?;
        Ok(())
    }

    pub fn settle_required_work(&mut self, attempt: CommandAttemptId) -> Result<(), ModelError> {
        let active = self.staging_mut(attempt)?;
        active.required_work = active
            .required_work
            .checked_sub(1)
            .ok_or(ModelError::Invalid)?;
        Ok(())
    }

    pub fn guest_return(
        &mut self,
        attempt: CommandAttemptId,
        outcome: GuestOutcome,
        output: Vec<u8>,
    ) -> Result<(), ModelError> {
        let active = self.staging_mut(attempt)?;
        if active.guest_outcome.is_some() {
            return Err(ModelError::Invalid);
        }
        active.guest_outcome = Some(outcome);
        active.output = output;
        if outcome == GuestOutcome::TechnicalFailure {
            self.abort_before_commit(attempt)?;
        }
        Ok(())
    }

    /// Host observation after typed lifting, application result validation and
    /// payload ownership checks. A true value here is a model input, not a compiler proof.
    pub fn validate_outputs(
        &mut self,
        attempt: CommandAttemptId,
        valid: bool,
    ) -> Result<(), ModelError> {
        let active = self.staging_mut(attempt)?;
        if active.guest_outcome.is_none() {
            return Err(ModelError::NotEligible);
        }
        if !valid {
            self.abort_before_commit(attempt)?;
            return Err(ModelError::Invalid);
        }
        active.outputs_validated = true;
        Ok(())
    }

    /// Preflights all finite output/envelope limits and seals guest staging. A
    /// successful root return cannot hand off a mutable plan with required work live.
    pub fn seal(&mut self, attempt: CommandAttemptId) -> Result<(), ModelError> {
        let active = self.staging(attempt)?;
        if active.guest_outcome.is_none() || !active.outputs_validated || active.required_work != 0
        {
            return Err(ModelError::NotEligible);
        }
        let cost = active
            .mutations
            .iter()
            .map(|(key, value)| key.len() + value.as_ref().map_or(0, Vec::len))
            .sum::<usize>()
            + active.intents.iter().map(Vec::len).sum::<usize>()
            + active.output.len();
        // This deterministic cost is a model bound, not the production encoder's sizing proof.
        if active.output.len() > self.limits.result_bytes || cost > self.limits.envelope_bytes {
            self.abort_before_commit(attempt)?;
            return Err(ModelError::Limit);
        }
        self.active
            .get_mut(&attempt)
            .ok_or(ModelError::StaleAttempt)?
            .phase = Phase::Eligible;
        Ok(())
    }

    /// Models the writer's final current-authorization/cancellation/OCC fence.
    /// Once admitted to irreversible I/O, cancellation alone cannot prove abort.
    pub fn begin_physical_commit(&mut self, attempt: CommandAttemptId) -> Result<(), ModelError> {
        let active = self.active.get(&attempt).ok_or(ModelError::StaleAttempt)?;
        if active.phase != Phase::Eligible {
            return Err(ModelError::NotEligible);
        }
        self.check_authority(&active.authority, &active.key.scope)?;
        if active.version != self.image.version {
            self.abort_before_commit(attempt)?;
            return Err(ModelError::Conflict);
        }
        if let Some(identity) = self
            .image
            .commands
            .get(&active.key)
            .and_then(|record| record.input.as_ref())
        {
            if self
                .image
                .inbox
                .contains_key(&(identity.binding.clone(), identity.message_id.clone()))
            {
                self.abort_before_commit(attempt)?;
                return Err(ModelError::DuplicateInput);
            }
        }
        self.active
            .get_mut(&attempt)
            .ok_or(ModelError::StaleAttempt)?
            .phase = Phase::CommitInFlight;
        Ok(())
    }

    /// One indivisible model step for state + intents + result + optional inbox.
    /// #381/#386, rather than this memory replacement, must prove physical durability.
    pub fn physical_commit(
        &mut self,
        attempt: CommandAttemptId,
    ) -> Result<CommitReceipt, ModelError> {
        let active = self.active.get(&attempt).ok_or(ModelError::StaleAttempt)?;
        if active.phase != Phase::CommitInFlight {
            return Err(ModelError::StaleAttempt);
        }
        // Describes validation under the same physical writer, not a second unfenced publish.
        if active.version != self.image.version {
            return Err(ModelError::Conflict);
        }
        let rejection = active.guest_outcome == Some(GuestOutcome::TerminalBusinessRejection);
        let mut candidate = self.image.clone();
        candidate.version.generation = candidate
            .version
            .generation
            .checked_add(1)
            .ok_or(ModelError::Limit)?;
        let mut effects = Vec::new();
        if !rejection {
            apply_mutations(&mut candidate.state, &active.mutations);
            for (sequence, payload) in active.intents.iter().enumerate() {
                let id = EffectId {
                    transaction: attempt.transaction,
                    sequence: u32::try_from(sequence).map_err(|_| ModelError::Limit)?,
                };
                candidate.intents.insert(
                    id,
                    Intent {
                        command: active.key.clone(),
                        payload: payload.clone(),
                        format: candidate.formats.intent,
                        unresolved: true,
                    },
                );
                effects.push(id);
            }
        }
        let receipt = CommitReceipt {
            key: active.key.clone(),
            attempt,
            version: candidate.version,
            business_committed: !rejection,
            effects,
            formats: candidate.formats,
        };
        let record = candidate
            .commands
            .get_mut(&active.key)
            .ok_or(ModelError::StaleAttempt)?;
        if record.outcome != DurableOutcome::InProgress(attempt) {
            return Err(ModelError::StaleAttempt);
        }
        record.outcome = if rejection {
            DurableOutcome::BusinessRejected(receipt.clone())
        } else {
            DurableOutcome::Committed(receipt.clone())
        };
        record.payload = Some(active.output.clone());
        if let Some(input) = &record.input {
            candidate.inbox.insert(
                (input.binding.clone(), input.message_id.clone()),
                active.key.clone(),
            );
        }
        self.image = candidate;
        let active = self
            .active
            .get_mut(&attempt)
            .ok_or(ModelError::StaleAttempt)?;
        active.phase = if rejection {
            Phase::Rejected
        } else {
            Phase::Committed
        };
        active.mutations.clear();
        active.intents.clear();
        Ok(receipt)
    }

    pub fn uncertain_commit(&mut self, attempt: CommandAttemptId) -> Result<(), ModelError> {
        let active = self
            .active
            .get_mut(&attempt)
            .ok_or(ModelError::StaleAttempt)?;
        if active.phase != Phase::CommitInFlight {
            return Err(ModelError::StaleAttempt);
        }
        active.phase = Phase::RecoveryRequired;
        self.image
            .commands
            .get_mut(&active.key)
            .ok_or(ModelError::StaleAttempt)?
            .outcome = DurableOutcome::RecoveryRequired(attempt);
        Ok(())
    }

    pub fn cancel(&mut self, attempt: CommandAttemptId) -> Result<Cancellation, ModelError> {
        let phase = self
            .active
            .get(&attempt)
            .ok_or(ModelError::StaleAttempt)?
            .phase;
        match phase {
            Phase::Staging | Phase::Eligible => {
                self.abort_before_commit(attempt)?;
                Ok(Cancellation::AbortedBeforeCommit)
            }
            Phase::CommitInFlight | Phase::RecoveryRequired => {
                Ok(Cancellation::CommitMayHaveOccurred)
            }
            Phase::Committed | Phase::Rejected | Phase::Aborted => {
                Ok(Cancellation::AlreadyTerminal)
            }
        }
    }

    fn abort_before_commit(&mut self, attempt: CommandAttemptId) -> Result<(), ModelError> {
        let active = self
            .active
            .get_mut(&attempt)
            .ok_or(ModelError::StaleAttempt)?;
        if !matches!(active.phase, Phase::Staging | Phase::Eligible) {
            return Err(ModelError::AbortUnproven);
        }
        active.mutations.clear();
        active.intents.clear();
        active.output.clear();
        active.phase = Phase::Aborted;
        self.image
            .commands
            .get_mut(&active.key)
            .ok_or(ModelError::StaleAttempt)?
            .outcome = DurableOutcome::TechnicalAborted {
            attempt,
            owners_retired: false,
        };
        Ok(())
    }

    /// Records a separate model observation; this is not affirmative real I/O retirement.
    pub fn cleanup(
        &mut self,
        attempt: CommandAttemptId,
        status: CleanupStatus,
    ) -> Result<(), ModelError> {
        let active = self
            .active
            .get_mut(&attempt)
            .ok_or(ModelError::StaleAttempt)?;
        if matches!(
            active.phase,
            Phase::Staging | Phase::Eligible | Phase::CommitInFlight
        ) {
            return Err(ModelError::NotEligible);
        }
        if active.cleanup != CleanupStatus::Owned || status == CleanupStatus::Owned {
            return Err(ModelError::Invalid);
        }
        active.cleanup = status;
        if status == CleanupStatus::Retired {
            active.snapshot.clear();
            active.output.clear();
        }
        if active.phase == Phase::Aborted && status == CleanupStatus::Retired {
            self.image
                .commands
                .get_mut(&active.key)
                .ok_or(ModelError::StaleAttempt)?
                .outcome = DurableOutcome::TechnicalAborted {
                attempt,
                owners_retired: true,
            };
        }
        Ok(())
    }

    pub fn cleanup_status(&self, attempt: CommandAttemptId) -> Result<CleanupStatus, ModelError> {
        Ok(self
            .active
            .get(&attempt)
            .ok_or(ModelError::StaleAttempt)?
            .cleanup)
    }

    pub fn lookup(
        &self,
        authority: &Authority,
        key: &CommandKey,
    ) -> Result<RecoveredResult, ModelError> {
        self.check_authority(authority, &key.scope)?;
        if !authority.permissions.result_read {
            return Err(ModelError::PermissionDenied);
        }
        let Some(record) = self.image.commands.get(key) else {
            return Ok(RecoveredResult {
                outcome: DurableOutcome::Unknown,
                payload: None,
            });
        };
        self.check_result_authority(authority, key, record)?;
        if record.payload.as_ref().map_or(0, Vec::len) > self.limits.recovery_bytes {
            return Err(ModelError::Limit);
        }
        Ok(RecoveredResult {
            outcome: record.outcome.clone(),
            payload: record.payload.clone(),
        })
    }

    pub fn abort_fence(
        &self,
        authority: &Authority,
        key: &CommandKey,
    ) -> Result<AbortFence, ModelError> {
        match self.lookup(authority, key)?.outcome {
            DurableOutcome::TechnicalAborted {
                attempt,
                owners_retired: true,
            } => Ok(AbortFence {
                key: key.clone(),
                attempt,
            }),
            _ => Err(ModelError::AbortUnproven),
        }
    }

    /// A deliberate caller action. The durable attempt compare-and-swap permits one
    /// winner; changed preconditions/body require a deliberate new command identity.
    pub fn retry(
        &mut self,
        authority: &Authority,
        body: &CommandBody,
        fence: &AbortFence,
        activation_id: u64,
    ) -> Result<CommandAttemptId, ModelError> {
        self.check_authority(authority, &fence.key.scope)?;
        if !authority.permissions.command || self.effects_paused {
            return Err(ModelError::PermissionDenied);
        }
        let record = self
            .image
            .commands
            .get(&fence.key)
            .ok_or(ModelError::AbortUnproven)?;
        self.check_result_authority(authority, &fence.key, record)?;
        if &record.body != body {
            return Err(ModelError::ChangedBody);
        }
        if record.outcome
            != (DurableOutcome::TechnicalAborted {
                attempt: fence.attempt,
                owners_retired: true,
            })
        {
            return Err(ModelError::AbortUnproven);
        }
        if body
            .expected_version
            .is_some_and(|expected| expected != self.image.version)
        {
            return Err(ModelError::StaleEdit);
        }
        let generation = fence
            .attempt
            .generation
            .checked_add(1)
            .ok_or(ModelError::Limit)?;
        let attempt = self.start(authority, fence.key.clone(), generation, activation_id)?;
        self.image
            .commands
            .get_mut(&fence.key)
            .ok_or(ModelError::AbortUnproven)?
            .outcome = DurableOutcome::InProgress(attempt);
        Ok(attempt)
    }

    pub fn acquire_query(&self, authority: &Authority) -> Result<QueryView, ModelError> {
        self.check_authority(authority, &authority.scope)?;
        if !authority.permissions.query {
            return Err(ModelError::PermissionDenied);
        }
        Ok(QueryView {
            version: self.image.version,
            physical_owner: self.physical_owner,
            authority: authority.clone(),
            snapshot: self.image.state.clone(),
            returned_bytes: 0,
            returned_entries: 0,
        })
    }

    pub fn query_get(
        &self,
        view: &mut QueryView,
        key: &[u8],
    ) -> Result<Option<Vec<u8>>, ModelError> {
        self.check_key(key)?;
        self.check_authority(&view.authority, &view.authority.scope)?;
        if view.physical_owner != self.physical_owner
            || view.version.incarnation != self.image.version.incarnation
        {
            return Err(ModelError::StaleAttempt);
        }
        let value = view.snapshot.get(key).cloned();
        let bytes = key.len() + value.as_ref().map_or(0, Vec::len);
        if view.returned_entries >= self.limits.scan_entries
            || bytes > self.limits.scan_bytes.saturating_sub(view.returned_bytes)
        {
            return Err(ModelError::Limit);
        }
        view.returned_bytes += bytes;
        view.returned_entries += 1;
        Ok(value)
    }

    pub fn acknowledge_input(&self, key: &CommandKey) -> Result<(), ModelError> {
        let record = self
            .image
            .commands
            .get(key)
            .ok_or(ModelError::AcknowledgementBeforeDurableDisposition)?;
        if !matches!(
            record.outcome,
            DurableOutcome::Committed(_) | DurableOutcome::BusinessRejected(_)
        ) {
            return Err(ModelError::AcknowledgementBeforeDurableDisposition);
        }
        let input = record.input.as_ref().ok_or(ModelError::Invalid)?;
        if self
            .image
            .inbox
            .get(&(input.binding.clone(), input.message_id.clone()))
            != Some(key)
        {
            return Err(ModelError::AcknowledgementBeforeDurableDisposition);
        }
        Ok(())
    }

    #[must_use]
    pub fn durable_image(&self) -> DurableImage {
        self.image.clone()
    }

    /// Ordinary restart retains namespace incarnation/history; it never runs a guest.
    /// An incomplete attempt is recovery-required until an affirmative engine/owner proof.
    pub fn reopen(&mut self) -> Result<(), ModelError> {
        self.physical_owner = self
            .physical_owner
            .checked_add(1)
            .ok_or(ModelError::Limit)?;
        self.active.clear();
        for record in self.image.commands.values_mut() {
            if let DurableOutcome::InProgress(attempt) = record.outcome {
                record.outcome = DurableOutcome::RecoveryRequired(attempt);
            }
        }
        Ok(())
    }

    /// Model's authoritative image proves no terminal envelope exists and the
    /// previous process owner is retired. Real #386/#387 recovery must prove both.
    pub fn prove_uncommitted_after_reopen(
        &mut self,
        authority: &Authority,
        key: &CommandKey,
    ) -> Result<(), ModelError> {
        self.check_authority(authority, &key.scope)?;
        let record = self
            .image
            .commands
            .get_mut(key)
            .ok_or(ModelError::AbortUnproven)?;
        let DurableOutcome::RecoveryRequired(attempt) = record.outcome else {
            return Err(ModelError::AbortUnproven);
        };
        if attempt.physical_owner == self.physical_owner {
            return Err(ModelError::AbortUnproven);
        }
        record.outcome = DurableOutcome::TechnicalAborted {
            attempt,
            owners_retired: true,
        };
        Ok(())
    }

    /// Older-history restore creates a new incarnation and pauses work. Historical
    /// grants are discarded; external effects still require explicit reconciliation.
    pub fn restore_older(
        &mut self,
        mut historical: DurableImage,
        new_incarnation: u64,
    ) -> Result<(), ModelError> {
        if historical.tenant != self.image.tenant
            || historical.namespace != self.image.namespace
            || new_incarnation <= self.image.version.incarnation
            || !self.active.is_empty()
        {
            return Err(ModelError::Invalid);
        }
        historical.version.incarnation = new_incarnation;
        self.image = historical;
        self.grants.clear();
        self.physical_owner = self
            .physical_owner
            .checked_add(1)
            .ok_or(ModelError::Limit)?;
        self.effects_paused = true;
        Ok(())
    }

    /// State schema may evolve independently; no retained result/intent decoder may
    /// disappear. Production also retains inbox/order/checkpoint/payload metadata.
    pub fn change_schema(
        &mut self,
        schema: u16,
        result_decoders: &BTreeSet<u16>,
        intent_decoders: &BTreeSet<u16>,
    ) -> Result<(), ModelError> {
        if schema == 0
            || self
                .image
                .commands
                .values()
                .any(|record| !result_decoders.contains(&record.result_format))
            || self
                .image
                .intents
                .values()
                .any(|intent| !intent_decoders.contains(&intent.format))
        {
            return Err(ModelError::RetainedFormatRequired);
        }
        if self.image.formats.state_schema != schema {
            let generation = self
                .image
                .version
                .generation
                .checked_add(1)
                .ok_or(ModelError::Limit)?;
            self.image.formats.state_schema = schema;
            self.image.version.generation = generation;
        }
        Ok(())
    }

    pub fn expire_result_payload(
        &mut self,
        key: &CommandKey,
        time: RetentionTime,
        required_elapsed: u64,
    ) -> Result<(), ModelError> {
        check_retention_time(time, required_elapsed)?;
        let record = self
            .image
            .commands
            .get_mut(key)
            .ok_or(ModelError::Invalid)?;
        if !matches!(
            record.outcome,
            DurableOutcome::Committed(_) | DurableOutcome::BusinessRejected(_)
        ) {
            return Err(ModelError::LinkedRetention);
        }
        record.payload = None;
        Ok(())
    }

    pub fn collect_command_identity(
        &mut self,
        key: &CommandKey,
        time: RetentionTime,
        required_elapsed: u64,
    ) -> Result<(), ModelError> {
        check_retention_time(time, required_elapsed)?;
        let record = self.image.commands.get(key).ok_or(ModelError::Invalid)?;
        if !matches!(
            record.outcome,
            DurableOutcome::Committed(_) | DurableOutcome::BusinessRejected(_)
        ) || record.input.is_some()
            || self
                .image
                .intents
                .values()
                .any(|intent| intent.command == *key && intent.unresolved)
        {
            return Err(ModelError::LinkedRetention);
        }
        self.image.commands.remove(key);
        Ok(())
    }

    pub fn intent_payload(&self, effect: EffectId) -> Result<&[u8], ModelError> {
        Ok(&self
            .image
            .intents
            .get(&effect)
            .ok_or(ModelError::Invalid)?
            .payload)
    }

    #[must_use]
    pub fn command_count(&self) -> usize {
        self.image.commands.len()
    }

    #[must_use]
    pub fn intent_count(&self) -> usize {
        self.image.intents.len()
    }

    #[must_use]
    pub fn version(&self) -> ViewVersion {
        self.image.version
    }

    fn check_scope(&self, scope: &Scope) -> Result<(), ModelError> {
        if scope.tenant != self.image.tenant
            || scope.namespace != self.image.namespace
            || scope.incarnation != self.image.version.incarnation
        {
            return Err(ModelError::ScopeMismatch);
        }
        if [
            &scope.tenant,
            &scope.namespace,
            &scope.recovery_scope,
            &scope.operation,
        ]
        .iter()
        .any(|part| part.is_empty() || part.len() > 256)
            || scope
                .entity
                .as_ref()
                .is_some_and(|entity| entity.is_empty() || entity.len() > 256)
        {
            return Err(ModelError::Invalid);
        }
        Ok(())
    }

    fn check_authority(&self, authority: &Authority, scope: &Scope) -> Result<(), ModelError> {
        self.check_scope(scope)?;
        if authority.scope != *scope
            || self.grants.get(scope) != Some(&(authority.epoch, authority.permissions))
        {
            return Err(ModelError::PermissionDenied);
        }
        Ok(())
    }

    fn check_result_authority(
        &self,
        authority: &Authority,
        key: &CommandKey,
        record: &CommandRecord,
    ) -> Result<(), ModelError> {
        self.check_authority(authority, &key.scope)?;
        if !authority.permissions.result_read
            || authority.permissions.result_policy != record.result_policy
        {
            return Err(ModelError::PermissionDenied);
        }
        Ok(())
    }

    fn check_key(&self, key: &[u8]) -> Result<(), ModelError> {
        if key.is_empty() || key.len() > self.limits.key_bytes {
            return Err(ModelError::Limit);
        }
        Ok(())
    }

    fn staging(&self, attempt: CommandAttemptId) -> Result<&Activation, ModelError> {
        let active = self.active.get(&attempt).ok_or(ModelError::StaleAttempt)?;
        if active.phase != Phase::Staging {
            return Err(ModelError::StagingClosed);
        }
        self.check_authority(&active.authority, &active.key.scope)?;
        Ok(active)
    }

    fn staging_mut(&mut self, attempt: CommandAttemptId) -> Result<&mut Activation, ModelError> {
        self.staging(attempt)?;
        self.active
            .get_mut(&attempt)
            .ok_or(ModelError::StaleAttempt)
    }
}

fn apply_mutations(
    state: &mut BTreeMap<Vec<u8>, Vec<u8>>,
    mutations: &BTreeMap<Vec<u8>, Option<Vec<u8>>>,
) {
    for (key, value) in mutations {
        if let Some(value) = value {
            state.insert(key.clone(), value.clone());
        } else {
            state.remove(key);
        }
    }
}

fn check_retention_time(time: RetentionTime, required_elapsed: u64) -> Result<(), ModelError> {
    match time {
        RetentionTime::Discontinuous => Err(ModelError::ClockDiscontinuity),
        RetentionTime::QualifiedElapsed(elapsed) if elapsed >= required_elapsed => Ok(()),
        RetentionTime::QualifiedElapsed(_) => Err(ModelError::LinkedRetention),
    }
}

#[cfg(test)]
mod tests;
