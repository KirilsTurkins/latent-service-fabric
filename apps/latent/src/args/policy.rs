use crate::error::Failure;
use clap::{Args, Subcommand, ValueEnum};
use std::path::PathBuf;

#[derive(Clone, Copy, ValueEnum)]
pub enum PolicyKind {
    Policy,
    ProviderBinding,
}
#[derive(Args)]
pub struct PolicyArgs {
    #[arg(long, value_enum, default_value = "policy", global = true)]
    pub kind: PolicyKind,
    #[command(subcommand)]
    pub command: PolicyCommand,
}
#[derive(Subcommand)]
pub enum PolicyCommand {
    Apply {
        #[arg(long)]
        id: String,
        #[arg(long, value_name = "FILE", value_hint = clap::ValueHint::FilePath)]
        file: PathBuf,
        #[arg(long)]
        operation_id: String,
        #[arg(long)]
        expected_generation: u64,
    },
    Get {
        #[arg(long)]
        id: String,
    },
    List {
        #[arg(long,default_value_t=16,value_parser=clap::value_parser!(u32).range(1..=32))]
        page_size: u32,
        #[arg(long)]
        page_token: Option<String>,
    },
    Revoke {
        #[arg(long)]
        id: String,
        #[arg(long)]
        operation_id: String,
        #[arg(long)]
        expected_generation: u64,
    },
    Operation {
        #[arg(long)]
        operation_id: String,
    },
    /// Explain rules for this authenticated identity; this grants no execution permission.
    Explain {
        #[arg(long)]
        id: String,
        #[arg(long)]
        provider_binding: String,
        #[arg(long)]
        service: String,
        #[arg(long)]
        publication_id: String,
        #[arg(long)]
        capability: String,
        #[arg(long)]
        operation: String,
        #[arg(long, value_name = "FILE", value_hint = clap::ValueHint::FilePath)]
        resource: PathBuf,
        #[arg(long)]
        additional_policy: Vec<String>,
    },
}
impl PolicyArgs {
    pub fn validate(&self) -> Result<(), Failure> {
        use super::validation::{identifier, path_argument};
        match &self.command {
            PolicyCommand::Apply {
                id,
                file,
                operation_id,
                ..
            } => {
                identifier(id, 256)?;
                identifier(operation_id, 256)?;
                path_argument(file)
            }
            PolicyCommand::Get { id } => identifier(id, 256),
            PolicyCommand::List { page_token, .. } => {
                if page_token.as_ref().is_some_and(|v| v.len() != 117) {
                    return Err(super::validation::invalid());
                }
                Ok(())
            }
            PolicyCommand::Revoke {
                id,
                operation_id,
                expected_generation,
            } => {
                identifier(id, 256)?;
                identifier(operation_id, 256)?;
                if *expected_generation == 0 {
                    return Err(super::validation::invalid());
                }
                Ok(())
            }
            PolicyCommand::Operation { operation_id } => identifier(operation_id, 256),
            PolicyCommand::Explain {
                id,
                provider_binding,
                service,
                publication_id,
                capability,
                operation,
                resource,
                additional_policy,
            } => {
                if matches!(self.kind, PolicyKind::ProviderBinding) || additional_policy.len() > 7 {
                    return Err(super::validation::invalid());
                }
                for value in [
                    id,
                    provider_binding,
                    service,
                    publication_id,
                    capability,
                    operation,
                ] {
                    identifier(value, 256)?;
                }
                for value in additional_policy {
                    identifier(value, 256)?;
                }
                path_argument(resource)
            }
        }
    }
    pub fn name(&self) -> &'static str {
        match self.command {
            PolicyCommand::Apply { .. } => "policy apply",
            PolicyCommand::Get { .. } => "policy get",
            PolicyCommand::List { .. } => "policy list",
            PolicyCommand::Revoke { .. } => "policy revoke",
            PolicyCommand::Operation { .. } => "policy operation",
            PolicyCommand::Explain { .. } => "policy explain",
        }
    }
}
