//! Explicit single-operation command grammar.

pub mod audit;
mod invoke;
mod package;
pub mod phase3;
pub mod policy;
pub mod release;
pub mod rollout;
pub mod web;
pub use package::{PackageCommand, PackagePullArgs, PackagePushArgs};
mod management;
#[cfg(test)]
mod tests;
mod validation;

use std::path::PathBuf;

use clap::{Parser, Subcommand, ValueEnum};

pub use invoke::{InvokeArgs, InvokeBudgetProfile};
pub use management::{
    ActivationCommand, ApplyArgs, DeploymentCommand, NodeCommand, PublicationArgs, PublishArgs,
    ReleaseCommand, RouteCommand, ServicePageArgs, ValidateCommand,
};
#[cfg(test)]
pub use management::{CancelArgs, DeleteArgs, DeploymentOperationArgs, FileArgs, IdArgs};
#[cfg(test)]
pub use release::OptionalReleaseOperation;

#[derive(Parser)]
#[command(
    name = "latent",
    version,
    about = "Bounded local developer and operator client"
)]
pub struct Cli {
    /// Explicit JSON credential profile file; no automatic discovery.
    #[arg(long, global = true, value_name = "FILE", value_hint = clap::ValueHint::FilePath)]
    pub config: Option<PathBuf>,
    #[arg(long, global = true, value_name = "NAME")]
    pub profile: Option<String>,
    /// Override the selected profile's literal loopback HTTP endpoint.
    #[arg(long, global = true, value_name = "URL")]
    pub endpoint: Option<String>,
    #[arg(long, global = true)]
    pub tenant: Option<String>,
    #[arg(long, global = true, value_enum, default_value = "human")]
    pub output: OutputFormat,
    /// Suppress human success chatter while retaining invocation payloads; incompatible with JSON.
    #[arg(long, global = true)]
    pub quiet: bool,
    #[arg(long, global = true, value_parser = clap::value_parser!(u64).range(1..=300_000))]
    pub connect_timeout_ms: Option<u64>,
    #[arg(long, global = true, value_parser = clap::value_parser!(u64).range(1..=300_000))]
    pub rpc_timeout_ms: Option<u64>,
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, ValueEnum)]
pub enum OutputFormat {
    Human,
    Json,
}

#[derive(Subcommand)]
pub enum Command {
    /// Print an offline completion script; never installs files or contacts a node.
    #[command(
        after_help = "Writes only shell source. --quiet preserves the script; --output json is rejected. Installation and removal: docs/cli-completions.md"
    )]
    Completions {
        #[arg(value_enum)]
        shell: crate::completions::CompletionShell,
    },
    #[command(subcommand)]
    Web(web::WebCommand),
    #[command(subcommand)]
    Trigger(phase3::TriggerCommand),
    #[command(subcommand)]
    Capability(phase3::CapabilityCommand),
    /// Manage bounded tenant policies and provider binding metadata.
    Policy(policy::PolicyArgs),
    #[command(subcommand)]
    Rollout(rollout::RolloutCommand),
    #[command(subcommand)]
    Audit(audit::AuditCommand),
    #[command(subcommand)]
    Package(PackageCommand),
    /// Validate a local manifest without contacting a node.
    #[command(subcommand)]
    Validate(ValidateCommand),
    #[command(subcommand)]
    Release(ReleaseCommand),
    #[command(subcommand)]
    Deployment(DeploymentCommand),
    #[command(subcommand)]
    Route(RouteCommand),
    /// Invoke once; no automatic retries or activation ID generation.
    Invoke(Box<InvokeArgs>),
    #[command(subcommand)]
    Activation(ActivationCommand),
    #[command(subcommand)]
    Node(NodeCommand),
}
