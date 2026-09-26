use std::path::PathBuf;

use clap::{Args, Subcommand};

use super::validation::{identifier, invalid, path_argument};
use crate::error::Failure;

#[derive(Args)]
pub struct TriggerMutation {
    #[arg(long)]
    pub operation_id: String,
    #[arg(long)]
    pub expected_generation: u64,
    #[arg(long)]
    pub expected_state_version: u64,
}

#[derive(Subcommand)]
pub enum TriggerCommand {
    Apply {
        #[arg(value_hint = clap::ValueHint::FilePath)]
        file: PathBuf,
        #[command(flatten)]
        mutation: TriggerMutation,
    },
    Get {
        id: String,
    },
    List {
        #[arg(long)]
        service: Option<String>,
        #[arg(long, default_value_t = 16, value_parser = clap::value_parser!(u32).range(1..=32))]
        page_size: u32,
        #[arg(long)]
        page_token: Option<String>,
    },
    Delete {
        id: String,
        #[command(flatten)]
        mutation: TriggerMutation,
    },
    Operation {
        operation_id: String,
    },
}

impl TriggerCommand {
    pub fn name(&self) -> &'static str {
        match self {
            Self::Apply { .. } => "trigger apply",
            Self::Get { .. } => "trigger get",
            Self::List { .. } => "trigger list",
            Self::Delete { .. } => "trigger delete",
            Self::Operation { .. } => "trigger operation",
        }
    }

    pub fn validate(&self) -> Result<(), Failure> {
        match self {
            Self::Apply { file, mutation } => {
                mutation.validate(false)?;
                path_argument(file)
            }
            Self::Get { id } => identifier(id, 128),
            Self::Delete { id, mutation } => {
                identifier(id, 128)?;
                mutation.validate(true)
            }
            Self::Operation { operation_id } => identifier(operation_id, 128),
            Self::List {
                service,
                page_token,
                ..
            } => {
                optional(service.as_ref(), 128)?;
                optional(page_token.as_ref(), 128)
            }
        }
    }
}

impl TriggerMutation {
    fn validate(&self, delete: bool) -> Result<(), Failure> {
        identifier(&self.operation_id, 128)?;
        if (delete && self.expected_generation == 0)
            || self.expected_generation == u64::MAX
            || self.expected_state_version == u64::MAX
        {
            return Err(invalid());
        }
        Ok(())
    }
}

#[derive(Subcommand)]
pub enum CapabilityCommand {
    List {
        #[arg(long)]
        deployment: String,
        #[arg(long)]
        provider: Option<String>,
        #[arg(long)]
        contract_prefix: Option<String>,
        #[arg(long)]
        include_node_usage: bool,
        #[arg(long, default_value_t = 16, value_parser = clap::value_parser!(u32).range(1..=128))]
        page_size: u32,
        #[arg(long)]
        page_token: Option<String>,
    },
    Explain {
        #[arg(long)]
        deployment: String,
        #[arg(long)]
        capability: String,
        #[arg(long)]
        operation: String,
        #[arg(long, value_hint = clap::ValueHint::FilePath)]
        resource: PathBuf,
    },
}

impl CapabilityCommand {
    pub fn name(&self) -> &'static str {
        match self {
            Self::List { .. } => "capability list",
            Self::Explain { .. } => "capability explain",
        }
    }

    pub fn validate(&self) -> Result<(), Failure> {
        match self {
            Self::List {
                deployment,
                provider,
                contract_prefix,
                page_token,
                ..
            } => {
                identifier(deployment, 256)?;
                optional(provider.as_ref(), 128)?;
                optional(contract_prefix.as_ref(), 128)?;
                optional(page_token.as_ref(), 160)
            }
            Self::Explain {
                deployment,
                capability,
                operation,
                resource,
            } => {
                identifier(deployment, 256)?;
                identifier(capability, 128)?;
                identifier(operation, 64)?;
                path_argument(resource)
            }
        }
    }
}

fn optional(value: Option<&String>, maximum: usize) -> Result<(), Failure> {
    if let Some(value) = value {
        identifier(value, maximum)?;
        if !value.is_ascii() {
            return Err(invalid());
        }
    }
    Ok(())
}
