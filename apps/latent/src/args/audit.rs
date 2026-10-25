pub mod maintenance;
use clap::{Args, Subcommand, ValueEnum};
#[derive(Subcommand)]
pub enum AuditCommand {
    Query(QueryArgs),
    /// Exclusive stopped-node maintenance, authorized by private-filesystem ownership.
    #[command(subcommand)]
    Maintenance(maintenance::MaintenanceCommand),
    /// Verify or query one operator-held sealed epoch without contacting a node.
    #[command(subcommand)]
    Archive(maintenance::ArchiveCommand),
}
impl AuditCommand {
    pub const fn is_local(&self) -> bool {
        !matches!(self, Self::Query(_))
    }
    pub const fn name(&self) -> &'static str {
        match self {
            Self::Query(_) => "audit query",
            Self::Maintenance(command) => command.name(),
            Self::Archive(command) => command.name(),
        }
    }
}
#[derive(Clone, Copy, ValueEnum)]
pub enum Scope {
    Tenant,
    Node,
}
#[derive(Args)]
pub struct QueryArgs {
    #[arg(long, value_enum, default_value = "tenant")]
    pub scope: Scope,
    #[arg(long, value_parser = ["verification-accepted", "verification-rejected", "release-revoked", "release-retired", "cache-hit", "cache-miss", "cache-corruption", "rollout-started", "rollout-stage-changed", "rollout-paused", "rollout-aborted", "promotion-accepted", "promotion-rejected", "rollback-accepted", "rollback-rejected"])]
    pub kind: Option<String>,
    #[arg(long)]
    pub actor: Option<String>,
    /// Durable accepted-at timestamp, not a producer's occurred-at timestamp.
    #[arg(long)]
    pub from_unix_millis: Option<u64>,
    #[arg(long)]
    pub to_unix_millis: Option<u64>,
    #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u32).range(..=128))]
    pub page_size: u32,
    #[arg(long)]
    pub page_token: Option<String>,
}
