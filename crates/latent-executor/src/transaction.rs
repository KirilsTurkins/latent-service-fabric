//! Engine-neutral activation-scoped state/intent access. Implementations must
//! retain the original authority, deadline, ledger and physical store owners;
//! these descriptive DTOs do not grant execution or commitment authority.

use latent_core::{transaction_contract::Value, ActivationBudget, ActivationId, BoxFuture};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Command,
    Query,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StateFailure {
    PermissionDenied,
    InvalidKey,
    InvalidValue,
    InvalidLimit,
    InvalidCursor,
    StaleInput,
    Conflict,
    ReadBudgetExhausted,
    WriteBudgetExhausted,
    HandleClosed,
    WrongActivation,
    WrongMode,
    UnsupportedVersion,
    Cancelled,
    Unavailable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IntentFailure {
    PermissionDenied,
    InvalidBinding,
    InvalidOperation,
    InvalidPayload,
    InvalidExpiry,
    CountLimit,
    ByteLimit,
    HandleClosed,
    WrongActivation,
    WrongMode,
    UnsupportedProfile,
    Cancelled,
    Unavailable,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ViewIdentity {
    pub namespace: String,
    pub incarnation: String,
    pub version: Vec<u8>,
    pub state_schema: String,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CommandInfo {
    pub view: ViewIdentity,
    pub command_id: String,
    pub attempt_id: String,
    pub entity: Option<String>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VersionedValue {
    pub value: Value,
    pub version: Vec<u8>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    pub key: Vec<u8>,
    pub value: VersionedValue,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PageInfo {
    pub view: ViewIdentity,
    pub entry_count: u32,
    pub encoded_bytes: u64,
    pub has_more: bool,
    pub next_cursor: Option<Vec<u8>>,
}
#[derive(Debug)]
pub struct Page {
    pub info: PageInfo,
    pub entries: Vec<Entry>,
}
#[derive(Debug)]
pub struct Intent {
    pub binding: String,
    pub operation: String,
    pub payload: Value,
    pub expires_at_unix_millis: Option<u64>,
}

/// Keeps the configured host's real byte reservation through canonical lowering
/// or page-resource destruction. Only trusted host adapters construct owners.
pub struct RetainedTransfer {
    _owner: Box<dyn Send + Sync>,
}
impl RetainedTransfer {
    #[must_use]
    pub fn new(owner: Box<dyn Send + Sync>) -> Self {
        Self { _owner: owner }
    }
}

/// One host-selected mode and scope for one real activation. Acquisition is
/// once-only even after guest drop; every method rechecks current authority.
/// No method exposes a namespace selector, native view, provider or commit.
pub trait TransactionHost: Send + Sync {
    fn activation_id(&self) -> &ActivationId;
    fn mode(&self) -> Mode;
    fn budget(&self) -> &ActivationBudget;
    fn acquire(&self, mode: Mode) -> Result<(), StateFailure>;
    fn release(&self, mode: Mode);
    fn view_identity(&self) -> Result<ViewIdentity, StateFailure>;
    fn command_info(&self) -> Result<CommandInfo, StateFailure>;
    fn authorize_read(&self) -> Result<(), StateFailure>;
    fn retain_transfer(&self, bytes: usize) -> Result<RetainedTransfer, StateFailure>;
    fn read<'a>(
        &'a self,
        key: Vec<u8>,
    ) -> BoxFuture<'a, Result<Option<VersionedValue>, StateFailure>>;
    fn scan<'a>(
        &'a self,
        prefix: Vec<u8>,
        limit: u32,
        cursor: Option<Vec<u8>>,
    ) -> BoxFuture<'a, Result<Page, StateFailure>>;
    fn put<'a>(&'a self, key: Vec<u8>, value: Value) -> BoxFuture<'a, Result<(), StateFailure>>;
    fn delete<'a>(&'a self, key: Vec<u8>) -> BoxFuture<'a, Result<(), StateFailure>>;
    fn stage<'a>(&'a self, intent: Intent) -> BoxFuture<'a, Result<u32, IntentFailure>>;
    /// Invoked by the real Store's host-state destructor after guest references
    /// are severed. This closes guest access; pending physical IO stays owned.
    fn finish_guest_access(&self);
}
