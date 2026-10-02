//! Affine optimistic sessions over one actual engine snapshot. Engine accesses
//! run on the protected store's fixed workers. The runtime retains the physical
//! view; sessions own bounded logical buffers and verify the borrowed view's ID.
//! Scope descriptors and cursors never grant policy or commit authority.

mod codec;
mod validation;
use crate::{
    embedded::{AtomicBatch, ExpectedRow, Family, ReadView, RowKey, RowMutation, StoreError},
    namespace::{
        namespace_record_key, NamespacePins, NamespaceRecord, NamespaceStatus, NamespaceVersion,
    },
};
use codec::{Cell, Usage};
use latent_core::{
    transaction_contract::{self as contract, ExpectedVersion, Precondition, Value},
    StateNamespaceId, TenantId,
};
use std::{
    collections::BTreeMap,
    sync::atomic::{AtomicU64, Ordering},
    time::{Duration, Instant},
};
pub use validation::validate_row;
pub use validation::{inspect_usage, StateUsage};
static NEXT_SESSION: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StateError {
    Invalid,
    InvalidCursor,
    Conflict,
    Limit,
    PermissionDenied,
    Closed,
    Expired,
    Corrupt,
    UnsupportedFormat,
    Unavailable,
    RecoveryRequired,
}
impl From<StoreError> for StateError {
    fn from(error: StoreError) -> Self {
        match error {
            StoreError::Invalid => Self::Invalid,
            StoreError::Capacity => Self::Limit,
            StoreError::Conflict => Self::Conflict,
            StoreError::Corrupt => Self::Corrupt,
            StoreError::UnsupportedFormat => Self::UnsupportedFormat,
            StoreError::Unavailable => Self::Unavailable,
            StoreError::CommitUncertain => Self::RecoveryRequired,
            StoreError::SnapshotExpired => Self::Expired,
        }
    }
}
impl StateError {
    #[must_use]
    pub const fn storage_error(self) -> Option<StoreError> {
        match self {
            Self::Corrupt => Some(StoreError::Corrupt),
            Self::UnsupportedFormat => Some(StoreError::UnsupportedFormat),
            Self::Unavailable => Some(StoreError::Unavailable),
            Self::RecoveryRequired => Some(StoreError::CommitUncertain),
            _ => None,
        }
    }
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StateMode {
    Command,
    Query,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StateAccess {
    Read,
    Stage,
    Seal,
}
/// Current sealed policy must authorize acquisition and every operation. Entity
/// selects one key space; namespace generation conservatively covers all entities.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StateScope {
    pub tenant: TenantId,
    pub namespace: StateNamespaceId,
    pub incarnation: u64,
    pub state_schema: String,
    pub entity: Option<String>,
    pub mode: StateMode,
}
#[derive(Debug, Clone, Copy)]
pub struct SessionLimits {
    pub read_bytes: usize,
    pub observed_keys: usize,
    pub staged_keys: usize,
    pub staged_bytes: usize,
    pub host_calls: u32,
    pub open_cursors: usize,
    pub scan_pages: u32,
    pub maximum_age: Duration,
}
impl Default for SessionLimits {
    fn default() -> Self {
        Self {
            read_bytes: 4 * 1024 * 1024,
            observed_keys: 1024,
            staged_keys: 128,
            staged_bytes: contract::STAGED_BYTES,
            host_calls: 256,
            open_cursors: 16,
            scan_pages: 32,
            maximum_age: Duration::from_secs(30),
        }
    }
}
impl SessionLimits {
    fn validate(self) -> Result<Self, StateError> {
        if self.read_bytes == 0
            || self.read_bytes > 16 * 1024 * 1024
            || self.observed_keys == 0
            || self.observed_keys > 1024
            || self.staged_keys == 0
            || self.staged_keys > 128
            || self.staged_bytes == 0
            || self.staged_bytes > contract::STAGED_BYTES
            || self.host_calls == 0
            || self.host_calls > 4096
            || self.open_cursors == 0
            || self.open_cursors > 16
            || self.scan_pages == 0
            || self.scan_pages > 32
            || self.maximum_age.is_zero()
            || self.maximum_age > Duration::from_secs(30)
        {
            return Err(StateError::Invalid);
        }
        Ok(self)
    }
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReadValue {
    pub value: Value,
    pub version: Vec<u8>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StateEntry {
    pub key: Vec<u8>,
    pub value: ReadValue,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PageCursor {
    token: Vec<u8>,
}
impl PageCursor {
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.token
    }
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StatePage {
    pub entries: Vec<StateEntry>,
    pub continuation: Option<PageCursor>,
}
struct Cursor {
    prefix: Vec<u8>,
    after: Vec<u8>,
    overlay_generation: u64,
}
struct Observation {
    original: Option<Vec<u8>>,
    cell: Option<Cell>,
}
struct Candidate {
    key: Vec<u8>,
    encoded: Option<Vec<u8>>,
}

/// No Clone and no commit: seal transfers a validated plan to the complete host
/// coordinator; close is once-only. The affine physical view is owned separately.
pub struct StateSession {
    scope: StateScope,
    namespace: NamespaceRecord,
    namespace_bytes: Vec<u8>,
    usage: Usage,
    usage_bytes: Option<Vec<u8>>,
    view: usize,
    identity: u64,
    limits: SessionLimits,
    opened: Instant,
    closed: bool,
    calls: u32,
    read_charge: usize,
    stage_charge: usize,
    pages: u32,
    overlay_generation: u64,
    next_cursor: u64,
    observations: BTreeMap<Vec<u8>, Observation>,
    staged: BTreeMap<Vec<u8>, Option<Value>>,
    cursors: BTreeMap<Vec<u8>, Cursor>,
}
impl StateSession {
    pub fn open(
        view: &ReadView,
        scope: StateScope,
        limits: SessionLimits,
        authorize: impl FnOnce(&StateScope, StateAccess) -> Result<(), StateError>,
    ) -> Result<Self, StateError> {
        let limits = limits.validate()?;
        if scope.incarnation == 0
            || scope.entity.as_ref().is_some_and(|entity| {
                contract::identity(entity).is_err() || entity.chars().any(char::is_control)
            })
        {
            return Err(StateError::Invalid);
        }
        authorize(&scope, StateAccess::Read)?;
        let namespace_bytes = view
            .get(&namespace_key(&scope)?)?
            .ok_or(StateError::PermissionDenied)?;
        let namespace =
            NamespaceRecord::decode(&namespace_bytes).map_err(|_| StateError::Corrupt)?;
        if namespace.tenant != scope.tenant
            || namespace.id != scope.namespace
            || namespace.version.incarnation != scope.incarnation
            || namespace.state_schema != scope.state_schema
            || namespace.status != NamespaceStatus::Active
        {
            return Err(StateError::PermissionDenied);
        }
        let usage_bytes = view.get(&usage_key(&scope)?)?;
        let usage = usage_bytes
            .as_deref()
            .map(Usage::decode)
            .transpose()?
            .unwrap_or_default();
        let read_charge = namespace_bytes
            .len()
            .checked_add(usage_bytes.as_ref().map_or(0, Vec::len))
            .and_then(|bytes| bytes.checked_mul(2))
            .ok_or(StateError::Limit)?;
        if read_charge > limits.read_bytes
            || usage.keys > namespace.quota.state_keys
            || usage.bytes > namespace.quota.state_bytes
            || usage.tombstone_bytes > namespace.quota.recovery_bytes
        {
            return Err(StateError::Limit);
        }
        let identity = NEXT_SESSION
            .fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
                value.checked_add(1)
            })
            .map_err(|_| StateError::Limit)?;
        Ok(Self {
            scope,
            namespace,
            namespace_bytes,
            usage,
            usage_bytes,
            view: view.identity(),
            identity,
            limits,
            opened: Instant::now(),
            closed: false,
            calls: 0,
            read_charge,
            stage_charge: 0,
            pages: 0,
            overlay_generation: 0,
            next_cursor: 1,
            observations: BTreeMap::new(),
            staged: BTreeMap::new(),
            cursors: BTreeMap::new(),
        })
    }
    #[must_use]
    pub fn scope(&self) -> &StateScope {
        &self.scope
    }
    #[must_use]
    pub fn view_version(&self) -> NamespaceVersion {
        self.namespace.version
    }
    fn access(
        &mut self,
        view: &ReadView,
        kind: StateAccess,
        authorize: impl FnOnce(&StateScope, StateAccess) -> Result<(), StateError>,
    ) -> Result<(), StateError> {
        if self.closed {
            return Err(StateError::Closed);
        }
        if view.identity() != self.view {
            return Err(StateError::Invalid);
        }
        if self.opened.elapsed() > self.limits.maximum_age {
            return Err(StateError::Expired);
        }
        if self.read_charge > self.limits.read_bytes || self.stage_charge > self.limits.staged_bytes
        {
            return Err(StateError::Limit);
        }
        self.calls = self.calls.checked_add(1).ok_or(StateError::Limit)?;
        if self.calls > self.limits.host_calls {
            return Err(StateError::Limit);
        }
        if kind != StateAccess::Read && self.scope.mode == StateMode::Query {
            return Err(StateError::PermissionDenied);
        }
        authorize(&self.scope, kind)
    }
    fn charge_read(&mut self, bytes: usize) -> Result<(), StateError> {
        self.read_charge = self
            .read_charge
            .checked_add(bytes)
            .ok_or(StateError::Limit)?;
        if self.read_charge > self.limits.read_bytes {
            return Err(StateError::Limit);
        }
        Ok(())
    }
    fn observe_raw(&mut self, key: &[u8], raw: Option<Vec<u8>>) -> Result<(), StateError> {
        let length = raw.as_ref().map_or(0, Vec::len);
        self.charge_read(
            length
                .checked_mul(3)
                .and_then(|bytes| bytes.checked_add(key.len()))
                .ok_or(StateError::Limit)?,
        )?;
        if !self.observations.contains_key(key) {
            if self.observations.len() == self.limits.observed_keys {
                return Err(StateError::Limit);
            }
            let cell = raw
                .as_deref()
                .map(|bytes| Cell::decode(bytes, self.namespace.version.generation))
                .transpose()?;
            self.observations.insert(
                key.to_vec(),
                Observation {
                    original: raw,
                    cell,
                },
            );
        }
        Ok(())
    }
    fn observe(&mut self, view: &ReadView, key: &[u8]) -> Result<(), StateError> {
        check_key(key)?;
        if let Some(observation) = self.observations.get(key) {
            let bytes = observation.original.as_ref().map_or(0, Vec::len);
            self.charge_read(
                bytes
                    .checked_mul(2)
                    .and_then(|bytes| bytes.checked_add(key.len()))
                    .ok_or(StateError::Limit)?,
            )?;
            return Ok(());
        }
        let raw = view.get(&state_key(&self.scope, key)?)?;
        self.observe_raw(key, raw)
    }
    fn value(&self, key: &[u8]) -> Result<Option<ReadValue>, StateError> {
        if let Some(value) = self.staged.get(key) {
            return value
                .as_ref()
                .map(|value| {
                    Ok(ReadValue {
                        value: value.clone(),
                        version: codec::version(
                            &self.scope,
                            key,
                            self.namespace
                                .version
                                .generation
                                .checked_add(1)
                                .ok_or(StateError::Limit)?,
                        )?,
                    })
                })
                .transpose();
        }
        self.observations
            .get(key)
            .and_then(|observation| observation.cell.as_ref())
            .and_then(|cell| cell.value.as_ref().map(|value| (cell, value)))
            .map(|(cell, value)| {
                Ok(ReadValue {
                    value: value.clone(),
                    version: codec::version(&self.scope, key, cell.generation)?,
                })
            })
            .transpose()
    }
    pub fn get(
        &mut self,
        view: &ReadView,
        key: &[u8],
        authorize: impl FnOnce(&StateScope, StateAccess) -> Result<(), StateError>,
    ) -> Result<Option<ReadValue>, StateError> {
        self.access(view, StateAccess::Read, authorize)?;
        self.observe(view, key)?;
        self.value(key)
    }
    pub fn put(
        &mut self,
        view: &ReadView,
        key: Vec<u8>,
        value: Value,
        authorize: impl FnOnce(&StateScope, StateAccess) -> Result<(), StateError>,
    ) -> Result<(), StateError> {
        self.stage(view, key, Some(value), authorize)
    }
    pub fn delete(
        &mut self,
        view: &ReadView,
        key: Vec<u8>,
        authorize: impl FnOnce(&StateScope, StateAccess) -> Result<(), StateError>,
    ) -> Result<(), StateError> {
        self.stage(view, key, None, authorize)
    }
    fn stage(
        &mut self,
        view: &ReadView,
        key: Vec<u8>,
        value: Option<Value>,
        authorize: impl FnOnce(&StateScope, StateAccess) -> Result<(), StateError>,
    ) -> Result<(), StateError> {
        self.access(view, StateAccess::Stage, authorize)?;
        check_key(&key)?;
        let cell = Cell {
            generation: self.namespace.version.generation,
            value,
        };
        let encoded = cell.encode()?;
        let charge = encoded
            .len()
            .checked_add(key.len())
            .and_then(|bytes| bytes.checked_mul(2))
            .ok_or(StateError::Limit)?;
        self.stage_charge = self
            .stage_charge
            .checked_add(charge)
            .ok_or(StateError::Limit)?;
        if self.stage_charge > self.limits.staged_bytes
            || (!self.staged.contains_key(&key) && self.staged.len() == self.limits.staged_keys)
        {
            return Err(StateError::Limit);
        }
        self.observe(view, &key)?;
        self.overlay_generation = self
            .overlay_generation
            .checked_add(1)
            .ok_or(StateError::Limit)?;
        self.staged.insert(key, cell.value);
        self.cursors.clear();
        Ok(())
    }
    pub fn check_preconditions(
        &mut self,
        view: &ReadView,
        conditions: &[Precondition],
        mut authorize: impl FnMut(&StateScope, StateAccess) -> Result<(), StateError>,
    ) -> Result<(), StateError> {
        if conditions.len() > contract::PRECONDITIONS {
            return Err(StateError::Limit);
        }
        let mut seen = std::collections::BTreeSet::new();
        for condition in conditions {
            if !seen.insert(&condition.key) {
                return Err(StateError::Invalid);
            }
            let actual = self.get(view, &condition.key, &mut authorize)?;
            let matches = match (&condition.expected, actual) {
                (ExpectedVersion::Absent, None) => true,
                (ExpectedVersion::Present(expected), Some(actual)) => expected == &actual.version,
                _ => false,
            };
            if !matches {
                return Err(StateError::Conflict);
            }
        }
        Ok(())
    }
    pub fn cursor(&self, bytes: &[u8]) -> Result<PageCursor, StateError> {
        if self.closed {
            return Err(StateError::Closed);
        }
        if bytes.len() != 32 || !self.cursors.contains_key(bytes) {
            return Err(StateError::InvalidCursor);
        }
        Ok(PageCursor {
            token: bytes.to_vec(),
        })
    }
    pub fn scan(
        &mut self,
        view: &ReadView,
        prefix: &[u8],
        cursor: Option<&PageCursor>,
        maximum_entries: u32,
        maximum_bytes: usize,
        authorize: impl FnOnce(&StateScope, StateAccess) -> Result<(), StateError>,
    ) -> Result<StatePage, StateError> {
        self.access(view, StateAccess::Read, authorize)?;
        if prefix.len() > contract::KEY_BYTES
            || maximum_entries == 0
            || maximum_entries > contract::PAGE_ENTRIES
            || maximum_bytes == 0
            || maximum_bytes > contract::PAGE_BYTES
        {
            return Err(StateError::Limit);
        }
        self.pages = self.pages.checked_add(1).ok_or(StateError::Limit)?;
        if self.pages > self.limits.scan_pages {
            return Err(StateError::Limit);
        }
        let mut after = if let Some(cursor) = cursor {
            let stored = self
                .cursors
                .get(&cursor.token)
                .ok_or(StateError::InvalidCursor)?;
            if stored.prefix != prefix || stored.overlay_generation != self.overlay_generation {
                return Err(StateError::InvalidCursor);
            }
            let after = stored.after.clone();
            self.cursors.remove(&cursor.token);
            Some(after)
        } else {
            None
        };
        let space = codec::key_prefix(&self.scope)?;
        let mut physical_prefix = space.clone();
        physical_prefix.extend_from_slice(prefix);
        let mut entries = Vec::new();
        let mut encoded_bytes = 0usize;
        loop {
            let Some(candidate) =
                self.next_candidate(view, prefix, &space, &physical_prefix, after.as_deref())?
            else {
                return Ok(StatePage {
                    entries,
                    continuation: None,
                });
            };
            if entries.len() == maximum_entries as usize {
                return Ok(StatePage {
                    entries,
                    continuation: Some(
                        self.make_cursor(prefix, after.ok_or(StateError::Corrupt)?)?,
                    ),
                });
            }
            let key = candidate.key;
            if let Some(encoded) = candidate.encoded {
                self.observe_raw(&key, Some(encoded))?;
            }
            if let Some(value) = self.value(&key)? {
                let amount = key
                    .len()
                    .checked_add(
                        Cell {
                            generation: self.namespace.version.generation,
                            value: Some(value.value.clone()),
                        }
                        .encode()?
                        .len(),
                    )
                    .and_then(|bytes| bytes.checked_add(value.version.len() + 16))
                    .ok_or(StateError::Limit)?;
                if amount > maximum_bytes.saturating_sub(encoded_bytes) {
                    if entries.is_empty() {
                        return Err(StateError::Limit);
                    }
                    return Ok(StatePage {
                        entries,
                        continuation: Some(
                            self.make_cursor(prefix, after.ok_or(StateError::Corrupt)?)?,
                        ),
                    });
                }
                encoded_bytes += amount;
                entries.push(StateEntry {
                    key: key.clone(),
                    value,
                });
            }
            after = Some(key);
        }
    }

    fn next_candidate(
        &mut self,
        view: &ReadView,
        prefix: &[u8],
        space: &[u8],
        physical_prefix: &[u8],
        after: Option<&[u8]>,
    ) -> Result<Option<Candidate>, StateError> {
        let physical_after = after.map(|after| {
            let mut key = space.to_vec();
            key.extend_from_slice(after);
            key
        });
        let raw = view.scan_after(
            Family::State,
            physical_prefix,
            physical_after.as_deref(),
            1,
            2 * 1024 * 1024 + 4096,
        )?;
        let engine = raw
            .rows
            .into_iter()
            .next()
            .map(|(key, value)| (key.key[space.len()..].to_vec(), value));
        if let Some((key, value)) = &engine {
            if key.is_empty() || key.len() > contract::KEY_BYTES || value.len() > codec::CELL_BYTES
            {
                return Err(StateError::Corrupt);
            }
            self.charge_read(
                value
                    .len()
                    .checked_mul(2)
                    .and_then(|bytes| bytes.checked_add(key.len()))
                    .ok_or(StateError::Limit)?,
            )?;
        }
        let lower = after.map_or(std::ops::Bound::Included(prefix), std::ops::Bound::Excluded);
        let overlay = self
            .staged
            .range::<[u8], _>((lower, std::ops::Bound::Unbounded))
            .next()
            .filter(|(key, _)| key.starts_with(prefix))
            .map(|(key, _)| key.clone());
        let key = match (engine.as_ref(), overlay.as_ref()) {
            (Some((key, _)), Some(staged)) => Some(std::cmp::min(key, staged).clone()),
            (Some((key, _)), None) => Some(key.clone()),
            (None, Some(staged)) => Some(staged.clone()),
            (None, None) => None,
        };
        Ok(key.map(|key| {
            let encoded =
                engine.and_then(|(engine_key, value)| (engine_key == key).then_some(value));
            Candidate { key, encoded }
        }))
    }
    fn make_cursor(&mut self, prefix: &[u8], after: Vec<u8>) -> Result<PageCursor, StateError> {
        if self.cursors.len() == self.limits.open_cursors {
            return Err(StateError::Limit);
        }
        let sequence = self.next_cursor;
        self.next_cursor = sequence.checked_add(1).ok_or(StateError::Limit)?;
        let mut token = Vec::with_capacity(32);
        for value in [
            self.identity,
            self.view as u64,
            sequence,
            self.overlay_generation,
        ] {
            token.extend_from_slice(&value.to_le_bytes());
        }
        self.cursors.insert(
            token.clone(),
            Cursor {
                prefix: prefix.to_vec(),
                after,
                overlay_generation: self.overlay_generation,
            },
        );
        Ok(PageCursor { token })
    }
    /// The runtime's physical-view guard queues actual destruction on a worker.
    pub fn close(&mut self) -> Result<(), StateError> {
        if self.closed {
            return Err(StateError::Closed);
        }
        self.closed = true;
        self.observations.clear();
        self.staged.clear();
        self.cursors.clear();
        Ok(())
    }
    pub fn seal(
        mut self,
        view: &ReadView,
        authorize: impl FnOnce(&StateScope, StateAccess) -> Result<(), StateError>,
    ) -> Result<StatePlan, StateError> {
        self.access(view, StateAccess::Seal, authorize)?;
        self.closed = true;
        let next_generation = self
            .namespace
            .version
            .generation
            .checked_add(1)
            .ok_or(StateError::Limit)?;
        let mut usage = self.usage;
        let mut mutations = Vec::with_capacity(self.staged.len());
        for (key, value) in self.staged {
            let observation = self.observations.get(&key).ok_or(StateError::Corrupt)?;
            if let Some(cell) = &observation.cell {
                let amount = (key.len()
                    + observation
                        .original
                        .as_ref()
                        .ok_or(StateError::Corrupt)?
                        .len()) as u64;
                if cell.value.is_some() {
                    usage.keys = usage.keys.checked_sub(1).ok_or(StateError::Corrupt)?;
                    usage.bytes = usage.bytes.checked_sub(amount).ok_or(StateError::Corrupt)?;
                } else {
                    usage.tombstones =
                        usage.tombstones.checked_sub(1).ok_or(StateError::Corrupt)?;
                    usage.tombstone_bytes = usage
                        .tombstone_bytes
                        .checked_sub(amount)
                        .ok_or(StateError::Corrupt)?;
                }
            }
            let present = value.is_some();
            let encoded = Cell {
                generation: next_generation,
                value,
            }
            .encode()?;
            let amount = (key.len() + encoded.len()) as u64;
            if present {
                usage.keys = usage.keys.checked_add(1).ok_or(StateError::Limit)?;
                usage.bytes = usage.bytes.checked_add(amount).ok_or(StateError::Limit)?;
            } else {
                usage.tombstones = usage.tombstones.checked_add(1).ok_or(StateError::Limit)?;
                usage.tombstone_bytes = usage
                    .tombstone_bytes
                    .checked_add(amount)
                    .ok_or(StateError::Limit)?;
            }
            mutations.push(RowMutation {
                key: state_key(&self.scope, &key)?,
                value: Some(encoded),
            });
        }
        if usage.keys > self.namespace.quota.state_keys
            || usage.bytes > self.namespace.quota.state_bytes
            || usage.tombstone_bytes > self.namespace.quota.recovery_bytes
        {
            return Err(StateError::Limit);
        }
        let expectation = ExpectedRow {
            key: namespace_key(&self.scope)?,
            value: Some(self.namespace_bytes),
        };
        let usage_expectation = ExpectedRow {
            key: usage_key(&self.scope)?,
            value: self.usage_bytes,
        };
        let mut namespace = self.namespace;
        namespace.version.generation = next_generation;
        Ok(StatePlan {
            scope: self.scope,
            namespace,
            expectation,
            usage_expectation,
            usage: usage.encode(),
            mutations,
        })
    }
}
/// Host coordinator consumes this once, alongside command/results/intents/inbox.
/// There is no independent business commit method.
pub struct StatePlan {
    scope: StateScope,
    namespace: NamespaceRecord,
    expectation: ExpectedRow,
    usage_expectation: ExpectedRow,
    usage: Vec<u8>,
    mutations: Vec<RowMutation>,
}
impl StatePlan {
    #[must_use]
    pub fn scope(&self) -> &StateScope {
        &self.scope
    }
    #[must_use]
    pub fn version(&self) -> NamespaceVersion {
        self.namespace.version
    }
    #[must_use]
    pub fn pins(&self) -> NamespacePins {
        self.namespace.pins
    }
    pub fn append_to(
        mut self,
        batch: &mut AtomicBatch,
        pins: NamespacePins,
    ) -> Result<NamespaceVersion, StateError> {
        let old = self.namespace.pins;
        if pins.retained_results < old.retained_results
            || pins.unresolved_effects < old.unresolved_effects
            || pins.payload_references < old.payload_references
            || pins.inbox_protection < old.inbox_protection
        {
            return Err(StateError::Invalid);
        }
        self.namespace.pins = pins;
        let namespace = self.namespace.encode().map_err(|_| StateError::Corrupt)?;
        batch.expectations.push(self.expectation.clone());
        batch.expectations.push(self.usage_expectation.clone());
        batch.mutations.push(RowMutation {
            key: self.expectation.key,
            value: Some(namespace),
        });
        batch.mutations.push(RowMutation {
            key: self.usage_expectation.key,
            value: Some(self.usage),
        });
        batch.mutations.extend(self.mutations);
        Ok(self.namespace.version)
    }
}
fn check_key(key: &[u8]) -> Result<(), StateError> {
    if key.is_empty() || key.len() > contract::KEY_BYTES {
        Err(StateError::Limit)
    } else {
        Ok(())
    }
}
fn namespace_key(scope: &StateScope) -> Result<RowKey, StateError> {
    Ok(RowKey {
        family: Family::Namespace,
        key: namespace_record_key(&scope.tenant, &scope.namespace)
            .map_err(|_| StateError::Invalid)?,
    })
}
fn state_key(scope: &StateScope, key: &[u8]) -> Result<RowKey, StateError> {
    check_key(key)?;
    let mut bytes = codec::key_prefix(scope)?;
    bytes.extend_from_slice(key);
    Ok(RowKey {
        family: Family::State,
        key: bytes,
    })
}
fn usage_key(scope: &StateScope) -> Result<RowKey, StateError> {
    let mut key = b"state-usage-v1\0".to_vec();
    key.extend_from_slice(
        &namespace_record_key(&scope.tenant, &scope.namespace).map_err(|_| StateError::Invalid)?,
    );
    key.extend_from_slice(&scope.incarnation.to_le_bytes());
    Ok(RowKey {
        family: Family::Maintenance,
        key,
    })
}

#[cfg(test)]
mod tests;
