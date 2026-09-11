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
}

#[derive(Subcommand)]
pub enum DeploymentCommand {
    Apply(ApplyArgs),
    Get(IdArgs),
    List(ServicePageArgs),
    Delete(DeleteArgs),
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
}

#[derive(Args)]
pub struct ApplyArgs {
    pub file: PathBuf,
    /// Omitted: unconditional; zero: must be absent; positive: exact object version.
    #[arg(long)]
    pub expected_generation: Option<u64>,
}

#[derive(Args)]
pub struct DeleteArgs {
    pub id: String,
    #[arg(long)]
    pub expected_generation: Option<u64>,
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
