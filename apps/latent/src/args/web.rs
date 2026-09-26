use std::path::PathBuf;

use clap::Subcommand;

use super::{
    release::{PublishPackageArgs, ReleaseMutation},
    validation::{identifier, invalid, path_argument},
};
use crate::error::Failure;

#[derive(Subcommand)]
pub enum WebCommand {
    Publish(PublishPackageArgs),
    Get {
        #[arg(long)]
        publication: String,
    },
    Prepare {
        #[arg(long)]
        publication: String,
        #[arg(long, value_parser = clap::value_parser!(u64).range(1..))]
        lifecycle_generation: u64,
        #[arg(long, value_parser = clap::value_parser!(u64).range(1..=300_000))]
        maximum_wait_ms: u64,
    },
    Operation {
        operation_id: String,
    },
    Revoke {
        #[arg(long)]
        publication: String,
        #[command(flatten)]
        operation: ReleaseMutation,
    },
    Retire {
        #[arg(long)]
        publication: String,
        #[command(flatten)]
        operation: ReleaseMutation,
    },
    RenewEvidence {
        #[arg(long)]
        publication: String,
        #[arg(long)]
        package_digest: String,
        #[arg(long)]
        evidence: PathBuf,
        #[command(flatten)]
        operation: ReleaseMutation,
    },
}

impl WebCommand {
    pub fn name(&self) -> &'static str {
        match self {
            Self::Publish(_) => "web publish",
            Self::Get { .. } => "web get",
            Self::Prepare { .. } => "web prepare",
            Self::Operation { .. } => "web operation",
            Self::Revoke { .. } => "web revoke",
            Self::Retire { .. } => "web retire",
            Self::RenewEvidence { .. } => "web renew-evidence",
        }
    }

    pub fn validate(&self) -> Result<(), Failure> {
        match self {
            Self::Publish(arguments) => {
                path_argument(&arguments.directory)?;
                if let Some(path) = &arguments.evidence {
                    path_argument(path)?;
                }
                identifier(&arguments.operation_id, 128)?;
                if arguments.expected_generation != 0 {
                    return Err(invalid());
                }
                Ok(())
            }
            Self::Get { publication } => selected(publication),
            Self::Prepare {
                publication,
                lifecycle_generation,
                maximum_wait_ms,
            } => {
                selected(publication)?;
                if *lifecycle_generation == 0 || !(1..=300_000).contains(maximum_wait_ms) {
                    return Err(invalid());
                }
                Ok(())
            }
            Self::Operation { operation_id } => identifier(operation_id, 128),
            Self::Revoke {
                publication,
                operation,
            }
            | Self::Retire {
                publication,
                operation,
            } => mutation(publication, operation),
            Self::RenewEvidence {
                publication,
                package_digest,
                evidence,
                operation,
            } => {
                mutation(publication, operation)?;
                identifier(package_digest, 71)?;
                package_digest
                    .parse::<latent_core::PackageDigest>()
                    .map_err(|_| invalid())?;
                path_argument(evidence)
            }
        }
    }
}

fn selected(publication: &str) -> Result<(), Failure> {
    identifier(publication, latent_core::PublicationId::TEXT_BYTES)?;
    publication
        .parse::<latent_core::PublicationId>()
        .map_err(|_| invalid())?;
    Ok(())
}

fn mutation(publication: &str, operation: &ReleaseMutation) -> Result<(), Failure> {
    selected(publication)?;
    identifier(&operation.operation_id, 128)?;
    if operation.expected_generation == 0 || operation.expected_generation == u64::MAX {
        return Err(invalid());
    }
    Ok(())
}
