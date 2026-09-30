use std::path::PathBuf;

use clap::{Args, Subcommand};

#[derive(Subcommand)]
pub enum ValidateCommand {
    Capsule(FileArgs),
    Deployment(FileArgs),
}

#[derive(Subcommand)]
pub enum ReleaseCommand {
    Publish(PublishArgs),
    Get(PublicationArgs),
    List(ServicePageArgs),
    Lifecycle(PublicationArgs),
    Operation(OperationIdArgs),
    PublishPackage(super::release::PublishPackageArgs),
    Revoke(super::release::ChangeReleaseArgs),
    Retire(super::release::ChangeReleaseArgs),
    RenewEvidence(super::release::RenewEvidenceArgs),
}

#[derive(Subcommand)]
pub enum DeploymentCommand {
    Apply(ApplyArgs),
    Get(DeploymentGetArgs),
    List(ServicePageArgs),
    Delete(DeleteArgs),
    Operation(OperationIdArgs),
}

#[derive(Subcommand)]
pub enum RouteCommand {
    Get(RouteGetArgs),
    /// Inspect an immutable typed/HTTP target without invoking or binding it.
    Target(TargetInspectionArgs),
}

#[derive(Args)]
pub struct TargetInspectionArgs {
    #[arg(long)]
    pub service: String,
    #[arg(long)]
    pub contract: String,
    #[arg(long)]
    pub function: String,
    #[arg(long)]
    pub route: Option<String>,
    #[arg(long)]
    pub revision: Option<String>,
    /// Exact publication:sha256: identity in the authenticated tenant.
    #[arg(long)]
    pub publication: Option<String>,
    /// Evaluate this hypothetical routing key; absence returns candidates only.
    #[arg(long)]
    pub routing_key: Option<String>,
    /// Validate and compile the selected component without materialization.
    #[arg(long)]
    pub include_preparation: bool,
    /// One total wait across every candidate. Zero selects 10 seconds.
    #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u64).range(..=30_000))]
    pub maximum_wait_millis: u64,
}

#[derive(Subcommand)]
pub enum ActivationCommand {
    Get(IdArgs),
    Cancel(CancelArgs),
    /// Inspect retained authorized lineage and safe operator diagnostics.
    Tree(ActivationTreeArgs),
    /// Discover retained actual ingress roots in the authenticated tenant.
    Roots(ActivationRootsArgs),
}

#[derive(Args)]
pub struct ActivationTreeArgs {
    pub id: String,
    #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u32).range(..=128))]
    pub page_size: u32,
    #[arg(long)]
    pub page_token: Option<String>,
}

#[derive(Args)]
pub struct ActivationRootsArgs {
    #[arg(long)]
    pub service: String,
    #[arg(long)]
    pub from_unix_millis: Option<u64>,
    #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u32).range(..=128))]
    pub page_size: u32,
    #[arg(long)]
    pub page_token: Option<String>,
}

#[derive(Subcommand)]
pub enum NodeCommand {
    Get(IdArgs),
    List(NodeListArgs),
}

#[derive(Args)]
pub struct FileArgs {
    #[arg(value_hint = clap::ValueHint::FilePath)]
    pub file: PathBuf,
}

#[derive(Args)]
pub struct IdArgs {
    pub id: String,
}

#[derive(Args)]
pub struct PublicationArgs {
    /// Exact publication ID in the configured authenticated tenant.
    #[arg(long)]
    pub publication: String,
}

#[derive(Args)]
pub struct PublishArgs {
    #[arg(long, value_hint = clap::ValueHint::FilePath)]
    pub manifest: PathBuf,
    #[arg(long, value_hint = clap::ValueHint::FilePath)]
    pub component: PathBuf,
    #[arg(long, value_hint = clap::ValueHint::FilePath)]
    pub contracts: PathBuf,
    #[command(flatten)]
    pub operation: super::release::OptionalReleaseOperation,
}

#[derive(Args)]
pub struct ApplyArgs {
    #[arg(value_hint = clap::ValueHint::FilePath)]
    pub file: PathBuf,
    /// Omitted: unconditional; zero: must be absent; positive: exact object version.
    #[arg(long)]
    pub expected_generation: Option<u64>,
    #[command(flatten)]
    pub operation: DeploymentOperationArgs,
}

#[derive(Args)]
pub struct DeleteArgs {
    pub id: String,
    #[arg(long)]
    pub expected_generation: Option<u64>,
    #[command(flatten)]
    pub operation: DeploymentOperationArgs,
}

#[derive(Args, Default)]
pub struct DeploymentOperationArgs {
    #[arg(long, requires_all = ["expected_state_version", "expected_generation"])]
    pub operation_id: Option<String>,
    #[arg(long, requires = "operation_id")]
    pub expected_state_version: Option<u64>,
}

#[derive(Args)]
pub struct DeploymentGetArgs {
    pub id: String,
    /// Obtain the coherent global state version needed for managed mutation CAS.
    #[arg(long)]
    pub operation_snapshot: bool,
}

#[derive(Args)]
pub struct OperationIdArgs {
    pub operation_id: String,
}

#[derive(Args)]
pub struct ServicePageArgs {
    #[arg(long)]
    pub service: Option<String>,
    /// Zero selects the node's configured default. One page is returned.
    #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u32).range(..=1000))]
    pub page_size: u32,
    #[arg(long)]
    pub page_token: Option<String>,
}

#[derive(Args)]
pub struct RouteGetArgs {
    #[arg(long)]
    pub generation: Option<u64>,
}

#[derive(Args)]
pub struct CancelArgs {
    pub id: String,
    #[arg(long, default_value = "operator cancellation")]
    pub reason: String,
}

#[derive(Args)]
pub struct NodeListArgs {
    #[arg(long)]
    pub trust_class: Option<String>,
    #[arg(long)]
    pub region: Option<String>,
    #[arg(long)]
    pub zone: Option<String>,
    #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u32).range(..=1000))]
    pub page_size: u32,
    #[arg(long)]
    pub page_token: Option<String>,
}
