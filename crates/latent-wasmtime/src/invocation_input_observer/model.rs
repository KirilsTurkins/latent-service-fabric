use latent_core::ActivationId;
use serde::Serialize;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InvocationInputPhase {
    RawOwnerCreated,
    BeforeCallExport,
    GuestCallStart,
    RawOwnerDropped,
    InvocationFinished,
    InvocationDropped,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InvocationInputDropReason {
    BeforeGuestCall,
    OwnerScopeExit,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct InvocationInputIdentity {
    pub token: u8,
    pub activation_id: ActivationId,
}

/// Actual raw-vector observations; capacities are Rust-visible bytes, not RSS.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct InvocationInputRecord {
    pub sequence: u64,
    pub token: u8,
    pub phase: InvocationInputPhase,
    pub observed_nanos: u64,
    pub raw_length_bytes: Option<u64>,
    pub raw_capacity_bytes: Option<u64>,
    pub drop_reason: Option<InvocationInputDropReason>,
    pub live_invocations: u64,
    pub live_raw_owners: u64,
    pub live_raw_capacity_bytes: u64,
    pub maximum_live_raw_owners: u64,
    pub maximum_live_raw_capacity_bytes: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct InvocationInputSnapshot {
    pub enabled: bool,
    pub overflowed: bool,
    pub maximum_identities: usize,
    pub maximum_identity_bytes: usize,
    pub maximum_records: usize,
    pub observed_nanos: u64,
    pub identities: Vec<InvocationInputIdentity>,
    pub records: Vec<InvocationInputRecord>,
    pub started_invocations: u64,
    pub finished_invocations: u64,
    pub dropped_invocations: u64,
    pub live_invocations: u64,
    pub live_raw_owners: u64,
    pub live_raw_capacity_bytes: u64,
    pub maximum_live_raw_owners: u64,
    pub maximum_live_raw_capacity_bytes: u64,
}

/// The existing conservative context-validation charge, excluding raw payload.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct InvocationContextCharge {
    pub maximum_bytes: usize,
    pub charged_bytes: usize,
    pub remaining_bytes: usize,
}
