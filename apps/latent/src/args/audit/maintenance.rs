//! Explicit local-filesystem operator commands; no credential-profile lookup.
use super::Scope;
use crate::{args::Cli, error::Failure};
use clap::{Args, Subcommand};
use std::{
    path::{Component, Path, PathBuf},
    time::Duration,
};

#[derive(Subcommand)]
pub enum MaintenanceCommand {
    /// Inspect an existing stopped journal without reserving future capacity.
    Status(JournalArgs),
    /// Seal the current epoch and resume the exact original interrupted rollover.
    Rollover(RolloverArgs),
    /// Verify and list the finite local archive suffix for one journal identity.
    Custody(CustodyArgs),
    /// Transfer the oldest archive, verify its durable copy, then release local capacity.
    Transfer(TransferArgs),
}

#[derive(Subcommand)]
pub enum ArchiveCommand {
    /// Verify exactly one sealed epoch. This is not complete observation history.
    Verify(ArchiveArgs),
    /// Query one explicitly selected sealed epoch as its filesystem operator.
    Query(ArchiveQueryArgs),
}

#[derive(Args)]
pub struct LocalArgs {
    /// Acknowledge that authorization comes from effective-UID private-filesystem ownership, not tenant RPC claims.
    #[arg(long, required = true)]
    pub local_operator: bool,
    /// Cooperative deadline. A blocked physical I/O owner is never reported as released.
    #[arg(long, default_value_t = 60, value_parser = clap::value_parser!(u64).range(1..=120))]
    pub deadline_seconds: u64,
}
impl LocalArgs {
    pub fn timeout(&self) -> Duration {
        Duration::from_secs(self.deadline_seconds)
    }
    fn validate(&self, cli: &Cli) -> Result<(), Failure> {
        if !self.local_operator
            || !(1..=120).contains(&self.deadline_seconds)
            || cli.config.is_some()
            || cli.profile.is_some()
            || cli.endpoint.is_some()
            || cli.connect_timeout_ms.is_some()
            || cli.rpc_timeout_ms.is_some()
            || cli.phase4
        {
            return Err(invalid());
        }
        Ok(())
    }
}

#[derive(Args)]
pub struct JournalArgs {
    #[command(flatten)]
    pub local: LocalArgs,
    #[arg(long, value_name = "DIRECTORY", value_hint = clap::ValueHint::DirPath)]
    pub journal: PathBuf,
}
#[derive(Args)]
pub struct RolloverArgs {
    #[command(flatten)]
    pub journal: JournalArgs,
    #[arg(long, value_name = "DIRECTORY", value_hint = clap::ValueHint::DirPath)]
    pub archives: PathBuf,
    /// Exact active epoch from the stopped-owner status; retain this value on retry.
    #[arg(long)]
    pub expected_epoch: String,
    /// Explicit 128-bit lowercase hex identity; retain this value on retry.
    #[arg(long)]
    pub operation_id: String,
}
#[derive(Args)]
pub struct CustodyArgs {
    #[command(flatten)]
    pub local: LocalArgs,
    #[arg(long, value_name = "DIRECTORY", value_hint = clap::ValueHint::DirPath)]
    pub archives: PathBuf,
    #[arg(long)]
    pub journal_id: String,
}
#[derive(Args)]
pub struct TransferArgs {
    #[command(flatten)]
    pub journal: JournalArgs,
    #[arg(long, value_name = "DIRECTORY", value_hint = clap::ValueHint::DirPath)]
    pub archives: PathBuf,
    /// One distinct private directory in operator-held durable custody.
    #[arg(long, value_name = "DIRECTORY", value_hint = clap::ValueHint::DirPath)]
    pub destination: PathBuf,
    #[arg(long)]
    pub epoch: String,
    #[arg(long)]
    pub expected_seal: String,
    #[arg(long)]
    pub operation_id: String,
}
#[derive(Args)]
pub struct ArchiveArgs {
    #[command(flatten)]
    pub local: LocalArgs,
    #[arg(long, value_name = "DIRECTORY", value_hint = clap::ValueHint::DirPath)]
    pub archive: PathBuf,
    #[arg(long)]
    pub epoch: String,
}
#[derive(Args)]
pub struct ArchiveQueryArgs {
    #[command(flatten)]
    pub archive: ArchiveArgs,
    /// Explicit scope filter. --tenant is required only for tenant scope and grants no authority.
    #[arg(long, value_enum)]
    pub scope: Scope,
    #[arg(long)]
    pub actor: Option<String>,
    #[arg(long)]
    pub from_unix_millis: Option<u64>,
    #[arg(long)]
    pub to_unix_millis: Option<u64>,
    #[arg(long, default_value_t = 128, value_parser = clap::value_parser!(u32).range(1..=128))]
    pub page_size: u32,
    #[arg(long, default_value_t = 65536, value_parser = clap::value_parser!(u32).range(32768..=262144))]
    pub maximum_bytes: u32,
    #[arg(long)]
    pub page_token: Option<String>,
}

impl MaintenanceCommand {
    pub fn validate(&self, cli: &Cli) -> Result<(), Failure> {
        if cli.tenant.is_some() {
            return Err(invalid());
        }
        match self {
            Self::Status(args) => journal(args, cli),
            Self::Rollover(args) => {
                journal(&args.journal, cli)?;
                path(&args.archives)?;
                hex(&args.expected_epoch, 32)?;
                hex(&args.operation_id, 32)
            }
            Self::Custody(args) => {
                args.local.validate(cli)?;
                path(&args.archives)?;
                hex(&args.journal_id, 32)
            }
            Self::Transfer(args) => {
                journal(&args.journal, cli)?;
                path(&args.archives)?;
                path(&args.destination)?;
                hex(&args.epoch, 32)?;
                hex(&args.expected_seal, 64)?;
                hex(&args.operation_id, 32)
            }
        }
    }
    pub const fn name(&self) -> &'static str {
        match self {
            Self::Status(_) => "audit maintenance status",
            Self::Rollover(_) => "audit maintenance rollover",
            Self::Custody(_) => "audit maintenance custody",
            Self::Transfer(_) => "audit maintenance transfer",
        }
    }
    pub const fn mutation(&self) -> bool {
        matches!(self, Self::Rollover(_) | Self::Transfer(_))
    }
}
impl ArchiveCommand {
    pub fn validate(&self, cli: &Cli) -> Result<(), Failure> {
        let args = match self {
            Self::Verify(args) => args,
            Self::Query(args) => &args.archive,
        };
        args.local.validate(cli)?;
        path(&args.archive)?;
        hex(&args.epoch, 32)?;
        match self {
            Self::Verify(_) if cli.tenant.is_some() => Err(invalid()),
            Self::Verify(_) => Ok(()),
            Self::Query(args) => {
                match (&args.scope, &cli.tenant) {
                    (Scope::Tenant, Some(tenant))
                        if !tenant.is_empty()
                            && tenant.len() <= 128
                            && !tenant.chars().any(char::is_control) => {}
                    (Scope::Node, None) => {}
                    _ => return Err(invalid()),
                }
                if args.actor.as_ref().is_some_and(|actor| {
                    actor.is_empty() || actor.len() > 512 || actor.chars().any(char::is_control)
                }) || args
                    .page_token
                    .as_ref()
                    .is_some_and(|token| token.is_empty() || token.len() > 256 || !token.is_ascii())
                    || !(1..=128).contains(&args.page_size)
                    || !(32768..=262144).contains(&args.maximum_bytes)
                    || args
                        .from_unix_millis
                        .zip(args.to_unix_millis)
                        .is_some_and(|(a, b)| a > b)
                {
                    return Err(invalid());
                }
                Ok(())
            }
        }
    }
    pub const fn name(&self) -> &'static str {
        match self {
            Self::Verify(_) => "audit archive verify",
            Self::Query(_) => "audit archive query",
        }
    }
}
fn journal(args: &JournalArgs, cli: &Cli) -> Result<(), Failure> {
    args.local.validate(cli)?;
    path(&args.journal)
}
fn hex(value: &str, length: usize) -> Result<(), Failure> {
    if value.len() != length
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid());
    }
    Ok(())
}
fn path(value: &Path) -> Result<(), Failure> {
    if value.as_os_str().is_empty()
        || value.as_os_str().len() > 4096
        || value.components().count() > 128
        || value
            .components()
            .any(|part| matches!(part, Component::ParentDir))
        || value
            .to_str()
            .is_none_or(|value| value.chars().any(char::is_control))
    {
        return Err(invalid());
    }
    Ok(())
}
fn invalid() -> Failure {
    Failure::local("invalid-audit-maintenance-input", "Use explicit bounded local-operator selectors without RPC credentials; preserve original operation identities when recovering.")
}
