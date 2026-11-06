//! Explicit one-shot publication maintenance; no generated mutation identities.
use clap::{Args, Subcommand, ValueEnum};
#[derive(Subcommand)]
pub enum RetentionCommand {
    Snapshot(SnapshotArgs),
    Pin(MutationArgs),
    Unpin(MutationArgs),
    Delete(MutationArgs),
    Assess(AssessArgs),
    Reclaim(ReclaimArgs),
    Operation(LookupArgs),
}
#[derive(Clone, Copy, ValueEnum)]
pub enum Kind {
    Pin,
    Unpin,
    Delete,
    Reclaim,
}
#[derive(Args)]
pub struct Wait {
    /// Total server work deadline, also bounded by the transport deadline.
    #[arg(long, default_value_t=10000, value_parser=clap::value_parser!(u64).range(1..=30000))]
    pub maximum_wait_ms: u64,
}
#[derive(Args)]
pub struct SnapshotArgs {
    /// Exact IDs in the configured tenant. At most 32; duplicates are refused.
    #[arg(long, required=true, action=clap::ArgAction::Append)]
    pub publication: Vec<String>,
    #[command(flatten)]
    pub wait: Wait,
}
#[derive(Args)]
pub struct Selection {
    /// Caller-retained identity. Never generated or automatically retried.
    #[arg(long)]
    pub operation_id: String,
    /// Original catalog fence: exactly 64 lowercase hexadecimal digits.
    #[arg(long)]
    pub catalog_fence: String,
    /// Exact publication:sha256:ID=GENERATION. Repeat for a batch of 1–32.
    #[arg(long, required=true, action=clap::ArgAction::Append)]
    pub target: Vec<String>,
}
#[derive(Args)]
pub struct Work {
    #[arg(long, default_value_t=1024, value_parser=clap::value_parser!(u32).range(1..=1024))]
    pub maximum_files: u32,
    #[arg(long, default_value_t=67108864, value_parser=clap::value_parser!(u64).range(1..=1073741824))]
    pub maximum_bytes_hashed: u64,
}
#[derive(Args)]
pub struct MutationArgs {
    #[command(flatten)]
    pub selection: Selection,
    #[command(flatten)]
    pub wait: Wait,
}
#[derive(Args)]
pub struct AssessArgs {
    /// Reproduce the exact ORIGINAL delete selection, fence and operation ID.
    #[command(flatten)]
    pub deletion: Selection,
    #[command(flatten)]
    pub work: Work,
    #[command(flatten)]
    pub wait: Wait,
}
#[derive(Args)]
pub struct ReclaimArgs {
    /// Reproduce the exact ORIGINAL delete selection, fence and operation ID.
    #[command(flatten)]
    pub deletion: Selection,
    /// Fresh catalog fence from an assessment; never replaces the original fence.
    #[arg(long)]
    pub reclamation_fence: String,
    #[command(flatten)]
    pub work: Work,
    #[command(flatten)]
    pub wait: Wait,
}
#[derive(Args)]
pub struct LookupArgs {
    #[arg(long, value_enum)]
    pub kind: Kind,
    #[arg(long)]
    pub operation_id: String,
}

impl RetentionCommand {
    pub(crate) fn name(&self) -> &'static str {
        match self {
            Self::Snapshot(_) => "release retention snapshot",
            Self::Pin(_) => "release retention pin",
            Self::Unpin(_) => "release retention unpin",
            Self::Delete(_) => "release retention delete",
            Self::Assess(_) => "release retention assess",
            Self::Reclaim(_) => "release retention reclaim",
            Self::Operation(_) => "release retention operation",
        }
    }
}
