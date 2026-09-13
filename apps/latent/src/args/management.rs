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
    Get(DigestArgs),
    List(ServicePageArgs),
    Lifecycle(DigestArgs),
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
}

#[derive(Subcommand)]
pub enum ActivationCommand {
    Get(IdArgs),
    Cancel(CancelArgs),
}

#[derive(Subcommand)]
pub enum NodeCommand {
    Get(IdArgs),
    List(NodeListArgs),
}

#[derive(Args)]
pub struct FileArgs {
    pub file: PathBuf,
}

#[derive(Args)]
pub struct IdArgs {
    pub id: String,
}

#[derive(Args)]
pub struct DigestArgs {
    pub digest: String,
}

#[derive(Args)]
pub struct PublishArgs {
    #[arg(long)]
    pub manifest: PathBuf,
    #[arg(long)]
    pub component: PathBuf,
    #[arg(long)]
    pub contracts: PathBuf,
    #[command(flatten)]
    pub operation: super::release::OptionalReleaseOperation,
}

#[derive(Args)]
pub struct ApplyArgs {
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
